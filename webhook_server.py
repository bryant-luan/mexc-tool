"""
TradingView -> MEXC 自動下單 Webhook 伺服器

用法：
    1. 設定環境變數（不要把金鑰寫死在程式碼裡）：
        export MEXC_API_KEY="你的 API Key"
        export MEXC_API_SECRET="你的 Secret Key"
        export WEBHOOK_SECRET="自己設定的密鑰，越複雜越好"
        export DRY_RUN="true"   # 先用 true 測試，確認無誤後再改成 false

    2. 安裝套件：
        pip install flask requests

    3. 啟動伺服器：
        python webhook_server.py
       預設監聽 0.0.0.0:5000，正式環境請放到有 HTTPS 的主機/反向代理後面。

    4. 在 TradingView 警報設定 Webhook URL，例如：
        https://你的網域/webhook
       訊息內容（Message）填：
        {
          "secret": "自己設定的密鑰",
          "symbol": "BTCUSDT",
          "side": "BUY",
          "type": "MARKET",
          "quantity": "0.001"
        }
"""

import os
import time
import hmac
import hashlib
import logging

import requests
from flask import Flask, request, jsonify

BASE_URL = "https://api.mexc.com"

API_KEY = os.environ.get("MEXC_API_KEY", "")
API_SECRET = os.environ.get("MEXC_API_SECRET", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tv_webhook")

app = Flask(__name__)


def sign_params(params: dict, secret: str) -> str:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


def place_order(symbol: str, side: str, order_type: str, quantity: float, price: float = None):
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
    }
    if order_type == "LIMIT":
        if price is None:
            raise ValueError("限價單需要提供價格")
        params["price"] = price
        params["timeInForce"] = "GTC"

    if DRY_RUN:
        logger.info("DRY_RUN 模式，模擬下單參數：%s", params)
        return {"dry_run": True, "would_send": params}

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    params["signature"] = sign_params(params, API_SECRET)

    headers = {"X-MEXC-APIKEY": API_KEY}
    resp = requests.post(f"{BASE_URL}/api/v3/order", headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


@app.route("/webhook", methods=["POST"])
def webhook():
    if not API_KEY or not API_SECRET:
        logger.error("尚未設定 MEXC_API_KEY / MEXC_API_SECRET 環境變數")
        return jsonify({"error": "server not configured"}), 500

    if not WEBHOOK_SECRET:
        logger.error("尚未設定 WEBHOOK_SECRET，拒絕所有請求以策安全")
        return jsonify({"error": "server not configured"}), 500

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid json"}), 400

    if data.get("secret") != WEBHOOK_SECRET:
        logger.warning("收到密鑰錯誤的請求，來源 IP：%s", request.remote_addr)
        return jsonify({"error": "unauthorized"}), 401

    try:
        symbol = data["symbol"]
        side = data["side"].upper()
        order_type = data.get("type", "MARKET").upper()
        quantity = float(data["quantity"])
        price = float(data["price"]) if "price" in data and data["price"] not in (None, "") else None

        if side not in ("BUY", "SELL"):
            return jsonify({"error": "side must be BUY or SELL"}), 400
        if quantity <= 0:
            return jsonify({"error": "quantity must be > 0"}), 400

        result = place_order(symbol, side, order_type, quantity, price)
        logger.info("下單結果：%s", result)
        return jsonify({"status": "ok", "result": result})

    except (KeyError, ValueError) as e:
        return jsonify({"error": f"bad request: {e}"}), 400
    except requests.exceptions.RequestException as e:
        logger.exception("呼叫 MEXC API 失敗")
        return jsonify({"error": f"mexc api error: {e}"}), 502


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "dry_run": DRY_RUN})


if __name__ == "__main__":
    if DRY_RUN:
        logger.info("目前為 DRY_RUN 模式，不會送出真實訂單")
    else:
        logger.warning("目前為正式模式，會送出真實訂單！")
    app.run(host="0.0.0.0", port=5000)
