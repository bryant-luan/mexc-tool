"""
exchange/gate_base.py

Gate.io 共用的簽名 / HTTP 請求邏輯，供 GateSpotExchange 與
GateFuturesExchange 共用繼承，避免簽名程式碼重複兩份。

這個類別本身仍是抽象的（沒有實作 BaseExchange 全部的抽象方法），
不能直接被實體化，只能當作 GateSpotExchange / GateFuturesExchange 的父類別。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Dict

import requests

from exchange.base import (
    BaseExchange,
    ExchangeException,
    AuthenticationError,
    NetworkException,
)


class GateAPIBase(BaseExchange):
    """Gate.io API 簽名與請求的共用邏輯"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        super().__init__(api_key=api_key, api_secret=api_secret, testnet=testnet)

        self.base_url = (
            "https://fx-api-testnet.gateio.ws" if testnet
            else "https://api.gateio.ws"
        )
        self.session = requests.Session()
        self.timeout = 10

    # ------------------------------------------------------------
    # Symbol 格式轉換： "BTC/USDT" <-> "BTC_USDT"
    # ------------------------------------------------------------

    @staticmethod
    def to_contract(symbol: str) -> str:
        """外部統一格式 -> Gate.io 格式（現貨/合約都用底線分隔）"""
        return symbol.replace("/", "_").upper()

    @staticmethod
    def to_symbol(contract: str) -> str:
        """Gate.io 格式 -> 外部統一格式"""
        return contract.replace("_", "/").upper()

    # ------------------------------------------------------------
    # 簽名 / 底層請求
    # ------------------------------------------------------------

    def _sign(self, method: str, url_path: str, query_string: str = "", body: str = "") -> dict:
        t = str(int(time.time()))
        hashed_payload = hashlib.sha512(body.encode("utf-8")).hexdigest()
        sign_string = "\n".join([method, url_path, query_string, hashed_payload, t])
        sign = hmac.new(
            self.api_secret.encode("utf-8"),
            sign_string.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return {
            "KEY": self.api_key,
            "Timestamp": t,
            "SIGN": sign,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _raw_request(self, method: str, url_path: str, params: dict = None, body: dict = None):
        params = params or {}
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        body_str = json.dumps(body) if body else ""
        headers = self._sign(method, url_path, query_string, body_str)
        url = self.base_url + url_path

        try:
            resp = self.session.request(
                method, url, headers=headers, params=params,
                data=body_str if body else None, timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise NetworkException(str(e))

        try:
            data = resp.json()
        except ValueError:
            raise ExchangeException(f"無法解析回應內容: {resp.text[:200]}")

        if resp.status_code in (401, 403):
            raise AuthenticationError(f"Gate 驗證失敗 [{resp.status_code}]: {data}")

        if resp.status_code >= 400:
            raise ExchangeException(f"Gate API 錯誤 [{resp.status_code}]: {data}")

        return data

    def safe_call(self, func, *args, **kwargs):
        """比照 MEXCExchange.safe_call，統一透過 retry + 例外轉換"""
        try:
            return self.retry(func, *args, **kwargs)
        except (AuthenticationError, NetworkException, ExchangeException):
            raise
        except Exception as e:
            raise ExchangeException(str(e))
