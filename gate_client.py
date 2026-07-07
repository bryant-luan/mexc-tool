"""
gate_client.py
Gate.io USDT 合約 API 客戶端（含簽名驗證）

Gate.io v4 API 的私有端點（如查詢持倉、下單）都需要 HMAC-SHA512 簽名，
單純帶 API Key 在 header 裡是不夠的，這是原本程式碼會失敗的主因。
"""

import hashlib
import hmac
import time
import json
import requests
from config import API_KEY, API_SECRET, BASE_URL


class GateClient:
    def __init__(self, api_key: str = API_KEY, api_secret: str = API_SECRET,
                 base_url: str = BASE_URL, timeout: int = 10):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # 簽名邏輯（依官方文件：sign_string = method + "\n" + url + "\n" + query + "\n" + hash(body) + "\n" + timestamp）
    # ------------------------------------------------------------------
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

    def _request(self, method: str, url_path: str, params: dict = None, body: dict = None):
        params = params or {}
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        body_str = json.dumps(body) if body else ""
        headers = self._sign(method, url_path, query_string, body_str)
        url = self.base_url + url_path

        resp = self.session.request(
            method, url, headers=headers, params=params,
            data=body_str if body else None, timeout=self.timeout,
        )
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise

        if resp.status_code >= 400:
            raise RuntimeError(f"Gate API 錯誤 [{resp.status_code}]: {data}")
        return data

    # ------------------------------------------------------------------
    # 公開方法
    # ------------------------------------------------------------------
    def get_position(self, contract: str, settle: str = "usdt") -> dict:
        """查詢單一合約持倉"""
        url_path = f"/api/v4/futures/{settle}/positions/{contract}"
        return self._request("GET", url_path)

    def get_all_positions(self, settle: str = "usdt") -> list:
        """查詢帳戶下所有合約持倉（只回傳有持倉的部位）"""
        url_path = f"/api/v4/futures/{settle}/positions"
        data = self._request("GET", url_path)
        return [p for p in data if float(p.get("size", 0)) != 0]

    def get_ticker(self, contract: str, settle: str = "usdt") -> dict:
        """查詢即時價格（公開端點，不需簽名，這裡沿用同一個 client 方便使用）"""
        url_path = f"/api/v4/futures/{settle}/tickers"
        data = self._request("GET", url_path, params={"contract": contract})
        return data[0] if data else {}

    def place_order(self, contract: str, size: int, price: str = "0",
                     tif: str = "gtc", settle: str = "usdt", reduce_only: bool = False) -> dict:
        """
        送出委託單。
        size > 0 為做多，size < 0 為做空；price="0" 代表市價單。
        使用前務必先在測試網或小額測試，避免誤下單造成損失。
        """
        url_path = f"/api/v4/futures/{settle}/orders"
        body = {
            "contract": contract,
            "size": size,
            "price": price,
            "tif": tif,
            "reduce_only": reduce_only,
        }
        return self._request("POST", url_path, body=body)
