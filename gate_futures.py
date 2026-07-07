"""
exchange/gate_futures.py

Gate.io USDT 永續合約 Exchange
與 MEXCExchange 對齊同一套 BaseExchange 介面。

symbol 格式對外統一採用 ccxt 風格 "BTC/USDT"，
內部會自動轉換成 Gate.io 合約格式 "BTC_USDT"。
"""

from __future__ import annotations

import logging
from typing import Dict, List

from exchange.base import (
    ExchangeException,
    OrderException,
)
from exchange.gate_base import GateAPIBase


class GateFuturesExchange(GateAPIBase):
    """Gate.io USDT 永續合約 Exchange"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False, settle: str = "usdt"):
        super().__init__(api_key=api_key, api_secret=api_secret, testnet=testnet)
        self.logger = logging.getLogger("GateFutures")
        self.settle = settle

        self.symbol_cache: List[str] = []
        self.contracts_cache: Dict[str, dict] = {}
        self.load_markets()

    # ==================================================
    # Market Cache
    # ==================================================

    def load_markets(self):
        try:
            contracts = self.safe_call(
                self._raw_request, "GET", f"/api/v4/futures/{self.settle}/contracts"
            )
            self.contracts_cache = {c["name"]: c for c in contracts}
            self.symbol_cache = [self.to_symbol(name) for name in self.contracts_cache.keys()]
            self.logger.info("Loaded %s contracts", len(self.symbol_cache))
        except Exception as e:
            raise ExchangeException(str(e))

    # ==================================================
    # Public
    # ==================================================

    def ping(self):
        try:
            self._raw_request("GET", f"/api/v4/futures/{self.settle}/contracts", params={"limit": 1})
            return True
        except Exception:
            return False

    def get_symbols(self) -> List[str]:
        return self.symbol_cache

    def get_exchange_info(self):
        return self.contracts_cache

    def get_symbol_info(self, symbol: str):
        contract = self.to_contract(symbol)
        if contract not in self.contracts_cache:
            raise ExchangeException(f"Unknown Symbol : {symbol}")
        return self.contracts_cache[contract]

    def get_price(self, symbol: str) -> float:
        ticker = self.get_ticker(symbol)
        return float(ticker.get("last", 0))

    def get_ticker(self, symbol: str) -> Dict:
        contract = self.to_contract(symbol)
        data = self.safe_call(
            self._raw_request, "GET", f"/api/v4/futures/{self.settle}/tickers",
            {"contract": contract},
        )
        return data[0] if data else {}

    def get_klines(self, symbol: str, interval: str, limit: int = 500):
        contract = self.to_contract(symbol)
        return self.safe_call(
            self._raw_request, "GET", f"/api/v4/futures/{self.settle}/candlesticks",
            {"contract": contract, "interval": interval, "limit": limit},
        )

    # ==================================================
    # Account
    # ==================================================

    def get_balance(self):
        data = self.safe_call(
            self._raw_request, "GET", f"/api/v4/futures/{self.settle}/accounts"
        )
        return {
            "total": float(data.get("total", 0)),
            "available": float(data.get("available", 0)),
            "unrealised_pnl": float(data.get("unrealised_pnl", 0)),
            "raw": data,
        }

    def get_positions(self):
        """回傳目前所有非零合約持倉（槓桿倉位），格式統一：
        {symbol, side(long/short), size, entry_price, leverage, unrealised_pnl, liq_price, raw}
        """
        data = self.safe_call(
            self._raw_request, "GET", f"/api/v4/futures/{self.settle}/positions"
        )
        positions = []
        for p in data:
            size = float(p.get("size", 0))
            if size == 0:
                continue
            positions.append({
                "symbol": self.to_symbol(p.get("contract", "")),
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "entry_price": float(p.get("entry_price", 0)),
                "leverage": p.get("leverage", "-"),
                "unrealised_pnl": float(p.get("unrealised_pnl", 0)),
                "liq_price": p.get("liq_price", "-"),
                "raw": p,
            })
        return positions

    def get_open_orders(self):
        return self.safe_call(
            self._raw_request, "GET", f"/api/v4/futures/{self.settle}/orders",
            {"status": "open"},
        )

    # ==================================================
    # Orders
    # ==================================================

    def place_market_order(self, symbol: str, side: str, quantity: float):
        side = self.validate_side(side)
        quantity = self.validate_quantity(quantity)
        contract = self.to_contract(symbol)
        size = int(quantity) if side == "BUY" else -int(quantity)

        body = {"contract": contract, "size": size, "price": "0", "tif": "ioc"}
        try:
            return self.safe_call(
                self._raw_request, "POST", f"/api/v4/futures/{self.settle}/orders", body=body
            )
        except ExchangeException as e:
            raise OrderException(f"市價單送出失敗: {e}")

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float):
        side = self.validate_side(side)
        quantity = self.validate_quantity(quantity)
        price = self.validate_price(price)
        contract = self.to_contract(symbol)
        size = int(quantity) if side == "BUY" else -int(quantity)

        body = {"contract": contract, "size": size, "price": str(price), "tif": "gtc"}
        try:
            return self.safe_call(
                self._raw_request, "POST", f"/api/v4/futures/{self.settle}/orders", body=body
            )
        except ExchangeException as e:
            raise OrderException(f"限價單送出失敗: {e}")

    def cancel_order(self, order_id: str, symbol: str):
        try:
            return self.safe_call(
                self._raw_request, "DELETE", f"/api/v4/futures/{self.settle}/orders/{order_id}",
            )
        except ExchangeException as e:
            raise OrderException(f"取消訂單失敗: {e}")

    def get_order(self, order_id: str, symbol: str):
        return self.safe_call(
            self._raw_request, "GET", f"/api/v4/futures/{self.settle}/orders/{order_id}",
        )


# 向後相容別名（先前版本叫 GateExchange）
GateExchange = GateFuturesExchange
