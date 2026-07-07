"""
exchange/mexc_futures.py

MEXC USDT 永續合約 Exchange
簽名邏輯依 app.py 內已驗證可用的寫法：sign_str = api_key + timestamp，HMAC-SHA256。

⚠️ MEXC 合約下單 API（/private/order/submit）欄位比 Gate.io 複雜
（side 用 1/2/3/4 表示開多/平空/開空/平多，還有 openType/leverage），
這裡的下單方法先實作基本版本並在文件裡標註清楚，正式使用前務必先在小額測試。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Dict, List

import requests

from exchange.base import (
    BaseExchange,
    ExchangeException,
    AuthenticationError,
    NetworkException,
    OrderException,
)


class MEXCFuturesExchange(BaseExchange):
    """MEXC USDT 永續合約 Exchange"""

    BASE_URL = "https://contract.mexc.com"

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        super().__init__(api_key=api_key, api_secret=api_secret, testnet=testnet)
        self.logger = logging.getLogger("MEXCFutures")
        self.session = requests.Session()
        self.timeout = 10

    # ==================================================
    # Symbol 格式轉換："BTC/USDT" <-> MEXC 合約格式 "BTC_USDT"
    # ==================================================

    @staticmethod
    def to_contract(symbol: str) -> str:
        return symbol.replace("/", "_").upper()

    @staticmethod
    def to_symbol(contract: str) -> str:
        return contract.replace("_", "/").upper()

    # ==================================================
    # 簽名 / 底層請求
    # ==================================================

    def _sign(self, timestamp: str, extra: str = "") -> str:
        sign_str = f"{self.api_key}{timestamp}{extra}"
        return hmac.new(
            self.api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _signed_request(self, method: str, path: str, params: dict = None, body: dict = None):
        timestamp = str(int(time.time() * 1000))
        # MEXC 合約簽名：GET 用排序後的 query string，POST 用 JSON body 字串
        if method == "GET":
            extra = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        else:
            import json
            extra = json.dumps(body) if body else ""

        signature = self._sign(timestamp, extra)
        headers = {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Content-Type": "application/json",
        }
        url = self.BASE_URL + path

        try:
            if method == "GET":
                resp = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
            else:
                resp = self.session.post(url, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise NetworkException(str(e))

        try:
            data = resp.json()
        except ValueError:
            raise ExchangeException(f"無法解析回應內容: {resp.text[:200]}")

        if resp.status_code in (401, 403):
            raise AuthenticationError(f"MEXC 驗證失敗 [{resp.status_code}]: {data}")

        if not data.get("success", True) and "code" in data:
            raise ExchangeException(f"MEXC 合約 API 錯誤: {data}")

        return data.get("data", data)

    def safe_call(self, func, *args, **kwargs):
        try:
            return self.retry(func, *args, **kwargs)
        except (AuthenticationError, NetworkException, ExchangeException):
            raise
        except Exception as e:
            raise ExchangeException(str(e))

    # ==================================================
    # Public
    # ==================================================

    def ping(self):
        try:
            resp = self.session.get(f"{self.BASE_URL}/api/v1/contract/ping", timeout=self.timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def get_symbols(self) -> List[str]:
        data = self.safe_call(self._public_get, "/api/v1/contract/detail")
        return [self.to_symbol(c["symbol"]) for c in data] if isinstance(data, list) else []

    def _public_get(self, path: str, params: dict = None):
        resp = self.session.get(f"{self.BASE_URL}{path}", params=params, timeout=self.timeout)
        data = resp.json()
        return data.get("data", data)

    def get_exchange_info(self):
        return self.safe_call(self._public_get, "/api/v1/contract/detail")

    def get_symbol_info(self, symbol: str):
        contract = self.to_contract(symbol)
        data = self.get_exchange_info()
        for c in data:
            if c.get("symbol") == contract:
                return c
        raise ExchangeException(f"Unknown Symbol : {symbol}")

    def get_price(self, symbol: str) -> float:
        ticker = self.get_ticker(symbol)
        return float(ticker.get("lastPrice", 0))

    def get_ticker(self, symbol: str) -> Dict:
        contract = self.to_contract(symbol)
        return self.safe_call(self._public_get, "/api/v1/contract/ticker", {"symbol": contract})

    def get_klines(self, symbol: str, interval: str, limit: int = 500):
        contract = self.to_contract(symbol)
        return self.safe_call(
            self._public_get, f"/api/v1/contract/kline/{contract}", {"interval": interval}
        )

    # ==================================================
    # Account
    # ==================================================

    def get_balance(self):
        data = self.safe_call(self._signed_request, "GET", "/api/v1/private/account/assets")
        return {"raw": data}

    def get_positions(self):
        """
        回傳目前所有非零合約持倉，格式對齊 GateFuturesExchange：
        {symbol, side(long/short), size, entry_price, leverage, unrealised_pnl, liq_price, raw}
        """
        data = self.safe_call(
            self._signed_request, "GET", "/api/v1/private/position/open_positions"
        )
        positions = []
        for item in data or []:
            size = float(item.get("holdVol", 0))
            if size <= 0:
                continue
            # positionType: 1 = 多, 2 = 空
            side = "long" if item.get("positionType") == 1 else "short"
            positions.append({
                "symbol": self.to_symbol(item.get("symbol", "")),
                "side": side,
                "size": size,
                "entry_price": float(item.get("openPrice", 0)),
                "leverage": item.get("leverage", "-"),
                "unrealised_pnl": float(item.get("realisedPnL", item.get("unrealized_pnl", 0)) or 0),
                "liq_price": item.get("liquidatePrice", "-"),
                "raw": item,
            })
        return positions

    def get_open_orders(self):
        return self.safe_call(
            self._signed_request, "GET", "/api/v1/private/order/list/open_orders"
        )

    # ==================================================
    # Orders
    # ==================================================

    def place_market_order(self, symbol: str, side: str, quantity: float):
        side = self.validate_side(side)
        quantity = self.validate_quantity(quantity)
        contract = self.to_contract(symbol)
        # side: 1=開多 3=開空（簡化版本，僅支援開倉，平倉請用交易所介面或另外擴充）
        mexc_side = 1 if side == "BUY" else 3
        body = {"symbol": contract, "side": mexc_side, "type": 5, "openType": 1, "vol": quantity, "leverage": 1}
        try:
            return self.safe_call(self._signed_request, "POST", "/api/v1/private/order/submit", body=body)
        except ExchangeException as e:
            raise OrderException(f"MEXC 合約市價單送出失敗: {e}")

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float):
        side = self.validate_side(side)
        quantity = self.validate_quantity(quantity)
        price = self.validate_price(price)
        contract = self.to_contract(symbol)
        mexc_side = 1 if side == "BUY" else 3
        body = {
            "symbol": contract, "side": mexc_side, "type": 1, "openType": 1,
            "vol": quantity, "price": price, "leverage": 1,
        }
        try:
            return self.safe_call(self._signed_request, "POST", "/api/v1/private/order/submit", body=body)
        except ExchangeException as e:
            raise OrderException(f"MEXC 合約限價單送出失敗: {e}")

    def cancel_order(self, order_id: str, symbol: str):
        try:
            return self.safe_call(
                self._signed_request, "POST", "/api/v1/private/order/cancel", body=[order_id]
            )
        except ExchangeException as e:
            raise OrderException(f"取消訂單失敗: {e}")

    def get_order(self, order_id: str, symbol: str):
        return self.safe_call(
            self._signed_request, "GET", "/api/v1/private/order/get/" + str(order_id)
        )
