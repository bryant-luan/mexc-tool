from flask import Flask, request, jsonify
import json
import os
import time
import hmac
import hashlib
import logging
import requests

app = Flask(__name__)

# MEXC 配置
BASE_URL = "https://api.mexc.com"
API_KEY = os.environ.get("MEXC_API_KEY", "")
API_SECRET = os.environ.get("MEXC_API_SECRET", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

# GATE 持倉
gate_positions = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

def sign_params(params: dict, secret: str) -> str:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

def place_order(symbol: str, side: str, order_type: str, quantity: float, price: float = None):
    params = {"symbol": symbol, "side": side, "type": order_type, "quantity": quantity}
    if order_type == "LIMIT" and price:
        params["price"] = price
        params["timeInForce"] = "GTC"
    if DRY_RUN:
        logger.info("DRY_RUN: %s", params)
        return {"dry_run": True}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    params["signature"] = sign_params(params, API_SECRET)
    headers = {"X-MEXC-APIKEY": API_KEY}
    resp = requests.post(f"{BASE_URL}/api/v3/order", headers=headers, params=params)
    return resp.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Gate.io 持倉:", json.dumps(data, indent=2))
    gate_positions[data.get('symbol')] = data
    if data.get("secret") == WEBHOOK_SECRET and API_KEY:
        place_order(data["symbol"], data["side"], data.get("type", "MARKET"), float(data["quantity"]))
    return jsonify({"status": "success"})

@app.route('/gate_positions', methods=['GET'])
def get_gate():
    return jsonify(gate_positions)

if __name__ == '__main__':
    print("Webhook 伺服器運行中...")
    app.run(host='0.0.0.0', port=5000)