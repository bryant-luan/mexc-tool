"""
exchange/gate_spot.py

Gate.io 現貨（Spot）Exchange
與 GateFuturesExchange 共用 GateAPIBase 的簽名邏輯，端點改用 /spot/...

⚠️ 現貨帳戶沒有「持倉」概念（沒有槓桿、沒有做空），
只有「餘額」。這裡把非零餘額包裝成跟合約 get_positions() 一致的
格式，方便 position_poller.py 用同一套邏輯處理，但欄位意義不同：
- side 固定是 "spot"
- entry_price / unrealised_pnl 為 None：
  Gate.io 現貨帳戶餘額 API 本身不會回傳成本價，
  要算真正的損益需要另外拉歷史成交紀錄計算加權平均成本，
  這裡先不做（如果你需要，之後可以再加）。
"""

from __future__ import annotations

import logging
from typing import Dict, List

from exchange.base import ExchangeException, OrderException
from exchange.gate_base import GateAPIBase


class GateSpotExchange(GateAPIBase):
    """Gate.io 現貨 Exchange"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        super().__init__(api_key=api_key, api_secret=api_secret, testnet=testnet)
        self.logger = logging.getLogger("GateSpot")

        self.symbol_cache: List[str] = []
        self.pairs_cache: Dict[str, dict] = {}
        self.load_markets()

    # ==================================================
    # Market Cache
    # ==================================================

    def load_markets(self):
        try:
            pairs = self.safe_call(self._raw_request, "GET", "/api/v4/spot/currency_pairs")
            self.pairs_cache = {p["id"]: p for p in pairs if p.get("trade_status") == "tradable"}
            self.symbol_cache = [self.to_symbol(pid) for pid in self.pairs_cache.keys()]
            self.logger.info("Loaded %s spot pairs", len(self.symbol_cache))
        except Exception as e:
            raise ExchangeException(str(e))

    # ==================================================
    # Public
    # ==================================================

    def ping(self):
        try:
            self._raw_request("GET", "/api/v4/spot/currency_pairs", params={"limit": 1})
            return True
        except Exception:
            return False

    def get_symbols(self) -> List[str]:
        return self.symbol_cache

    def get_exchange_info(self):
        return self.pairs_cache

    def get_symbol_info(self, symbol: str):
        pair = self.to_contract(symbol)
        if pair not in self.pairs_cache:
            raise ExchangeException(f"Unknown Symbol : {symbol}")
        return self.pairs_cache[pair]

    def get_price(self, symbol: str) -> float:
        ticker = self.get_ticker(symbol)
        return float(ticker.get("last", 0))

    def get_ticker(self, symbol: str) -> Dict:
        pair = self.to_contract(symbol)
        data = self.safe_call(
            self._raw_request, "GET", "/api/v4/spot/tickers", {"currency_pair": pair}
        )
        return data[0] if data else {}

    def get_klines(self, symbol: str, interval: str, limit: int = 500):
        pair = self.to_contract(symbol)
        return self.safe_call(
            self._raw_request, "GET", "/api/v4/spot/candlesticks",
            {"currency_pair": pair, "interval": interval, "limit": limit},
        )

    # ==================================================
    # Account
    # ==================================================

    def get_balance(self):
        data = self.safe_call(self._raw_request, "GET", "/api/v4/spot/accounts")
        total_available = sum(float(b.get("available", 0)) for b in data)
        total_locked = sum(float(b.get("locked", 0)) for b in data)
        return {
            "available": total_available,
            "locked": total_locked,
            "raw": data,
        }

    def get_positions(self):
        """
        現貨沒有「持倉」，這裡把非零餘額包裝成跟合約一致的格式，
        方便 position_poller.py 共用同一套變化偵測邏輯。
        symbol 欄位在現貨情況下是幣種本身（如 "BTC"），不是交易對。
        """
        data = self.safe_call(self._raw_request, "GET", "/api/v4/spot/accounts")
        holdings = []
        for b in data:
            available = float(b.get("available", 0))
            locked = float(b.get("locked", 0))
            total = available + locked
            if total <= 0:
                continue
            holdings.append({
                "symbol": b.get("currency", "?"),
                "side": "spot",
                "size": total,
                "entry_price": None,
                "leverage": "-",
                "unrealised_pnl": None,
                "liq_price": "-",
                "raw": b,
            })
        return holdings

    def get_open_orders(self):
        return self.safe_call(
            self._raw_request, "GET", "/api/v4/spot/open_orders"
        )

    # ==================================================
    # Orders
    # ==================================================

    def place_market_order(self, symbol: str, side: str, quantity: float):
        side = self.validate_side(side)
        quantity = self.validate_quantity(quantity)
        pair = self.to_contract(symbol)

        body = {
            "currency_pair": pair,
            "side": side.lower(),
            "type": "market",
            "amount": str(quantity),
            "time_in_force": "ioc",
        }
        try:
            return self.safe_call(self._raw_request, "POST", "/api/v4/spot/orders", body=body)
        except ExchangeException as e:
            raise OrderException(f"市價單送出失敗: {e}")

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float):
        side = self.validate_side(side)
        quantity = self.validate_quantity(quantity)
        price = self.validate_price(price)
        pair = self.to_contract(symbol)

        body = {
            "currency_pair": pair,
            "side": side.lower(),
            "type": "limit",
            "amount": str(quantity),
            "price": str(price),
            "time_in_force": "gtc",
        }
        try:
            return self.safe_call(self._raw_request, "POST", "/api/v4/spot/orders", body=body)
        except ExchangeException as e:
            raise OrderException(f"限價單送出失敗: {e}")

    def cancel_order(self, order_id: str, symbol: str):
        pair = self.to_contract(symbol)
        try:
            return self.safe_call(
                self._raw_request, "DELETE", f"/api/v4/spot/orders/{order_id}",
                params={"currency_pair": pair},
            )
        except ExchangeException as e:
            raise OrderException(f"取消訂單失敗: {e}")

    def get_order(self, order_id: str, symbol: str):
        pair = self.to_contract(symbol)
        return self.safe_call(
            self._raw_request, "GET", f"/api/v4/spot/orders/{order_id}",
            params={"currency_pair": pair},
        )
