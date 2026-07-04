"""
TradingView -> Gate.io 24 小時自動下單 + 止盈止損 常駐伺服器

用法：
    1. 設定環境變數（不要把金鑰寫死在程式碼裡）：
        export GATE_API_KEY="你的 Gate.io API Key"
        export GATE_API_SECRET="你的 Gate.io Secret Key"
        export WEBHOOK_SECRET="自己設定的密鑰，越複雜越好"
        export DRY_RUN="true"           # 先用 true 測試，確認無誤後再改成 false
        export POLL_INTERVAL_SECONDS="10"   # 背景檢查止盈/止損的頻率（秒），選填，預設 10

    2. 安裝套件：
        pip install flask requests

    3. 啟動伺服器：
        python gate_webhook_server.py
       預設監聽 0.0.0.0:5001，正式環境請放到有 HTTPS 的主機/反向代理後面，
       並讓它用 systemd / supervisor / pm2 之類的方式常駐、掛掉自動重啟。

    4. 在 TradingView 警報設定 Webhook URL，例如：
        https://你的網域/webhook
       開倉並自動附加止盈止損（做多，之後偵測到就自動市價賣出）：
        {
          "secret": "自己設定的密鑰",
          "symbol": "BTC_USDT",
          "side": "BUY",
          "type": "MARKET",
          "quantity": "10",
          "take_profit_pct": 5,
          "stop_loss_pct": 3
        }
        - Gate.io 市價 BUY 的 quantity 是「要花費的計價幣金額」（上例代表花 10 USDT 買進）
        - Gate.io 市價 SELL 的 quantity 是「要賣出的幣本身數量」

       只想單純下單、不附加止盈止損，就不要放 take_profit_pct / stop_loss_pct 欄位。

       手動出場某個幣對的持倉（例如想提早收手）：
        {
          "secret": "自己設定的密鑰",
          "action": "close",
          "symbol": "BTC_USDT"
        }

    5. 查看目前追蹤中的持倉（GET，需帶 secret）：
        https://你的網域/positions?secret=自己設定的密鑰

伺服器啟動後會另外開一條背景執行緒，每隔 POLL_INTERVAL_SECONDS 秒巡邏一次所有持倉，
價格觸及止盈或止損就自動用市價單平倉，達到「24 小時自動下單 + 止盈止損」的效果。
"""

import os
import time
import json
import hmac
import hashlib
import logging
import threading

import requests
from flask import Flask, request, jsonify

GATE_BASE_URL = "https://api.gateio.ws/api/v4"

API_KEY = os.environ.get("GATE_API_KEY", "")
API_SECRET = os.environ.get("GATE_API_SECRET", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gate_tv_webhook")

app = Flask(__name__)

# 持倉存放在記憶體中；伺服器重啟就會清空，如需重啟後還原，可自行改成寫入檔案或資料庫
positions = []
positions_lock = threading.Lock()


# ------------------------------------------------------------------
# Gate.io APIv4 簽名與請求
# ------------------------------------------------------------------
def gate_sign(method: str, url_path: str, query_string: str = "", payload_string: str = ""):
    ts = str(time.time())
    hashed_payload = hashlib.sha512((payload_string or "").encode("utf-8")).hexdigest()
    sign_str = f"{method}\n{url_path}\n{query_string}\n{hashed_payload}\n{ts}"
    sign = hmac.new(API_SECRET.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha512).hexdigest()
    return {"KEY": API_KEY, "Timestamp": ts, "SIGN": sign}


def gate_request(method: str, path: str, query_params: dict = None, body: dict = None):
    url_path = f"/api/v4{path}"
    query_string = "&".join(f"{k}={v}" for k, v in (query_params or {}).items())
    payload_string = json.dumps(body) if body is not None else ""

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    headers.update(gate_sign(method, url_path, query_string, payload_string))

    full_url = f"{GATE_BASE_URL}{path}"
    if query_string:
        full_url += f"?{query_string}"

    resp = requests.request(
        method, full_url, headers=headers,
        data=payload_string if body is not None else None, timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_current_price(symbol: str) -> float:
    resp = requests.get(f"{GATE_BASE_URL}/spot/tickers", params={"currency_pair": symbol}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError("查無此幣對報價")
    return float(data[0]["last"])


def place_order(symbol: str, side: str, order_type: str, quantity, price=None):
    body = {"currency_pair": symbol, "side": side.lower(), "amount": str(quantity)}
    if order_type.upper() == "LIMIT":
        if price is None:
            raise ValueError("限價單需要提供價格")
        body["type"] = "limit"
        body["price"] = str(price)
        body["time_in_force"] = "gtc"
    else:
        body["type"] = "market"
        body["time_in_force"] = "ioc"

    if DRY_RUN:
        logger.info("DRY_RUN 模式，模擬下單參數：%s", body)
        return {"dry_run": True, "would_send": body}

    return gate_request("POST", "/spot/orders", body=body)


# ------------------------------------------------------------------
# 持倉（止盈/止損）管理
# ------------------------------------------------------------------
def add_position(symbol: str, quantity: float, entry_price: float, tp_pct, sl_pct):
    tp_price = entry_price * (1 + tp_pct / 100) if tp_pct and float(tp_pct) > 0 else None
    sl_price = entry_price * (1 - sl_pct / 100) if sl_pct and float(sl_pct) > 0 else None
    position = {
        "id": f"{symbol}-{int(time.time() * 1000)}",
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "opened_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with positions_lock:
        positions.append(position)
    logger.info("新增持倉追蹤：%s", position)
    return position


def close_position_by_id(position_id: str, reason: str):
    with positions_lock:
        pos = next((p for p in positions if p["id"] == position_id), None)
    if pos is None:
        return None

    try:
        result = place_order(pos["symbol"], "SELL", "MARKET", pos["quantity"])
        with positions_lock:
            positions[:] = [p for p in positions if p["id"] != position_id]
        logger.info("持倉 %s 已因「%s」出場，結果：%s", position_id, reason, result)
        return result
    except (requests.exceptions.RequestException, ValueError):
        logger.exception("平倉失敗：%s", position_id)
        return None


def close_positions_by_symbol(symbol: str, reason: str):
    with positions_lock:
        targets = [p for p in positions if p["symbol"] == symbol]
    results = []
    for pos in targets:
        results.append(close_position_by_id(pos["id"], reason))
    return results


def monitor_loop():
    """背景執行緒：定期檢查所有持倉是否觸及止盈/止損，觸及就自動市價出場"""
    logger.info("止盈/止損監控執行緒已啟動，每 %s 秒巡邏一次", POLL_INTERVAL_SECONDS)
    while True:
        try:
            with positions_lock:
                snapshot = list(positions)

            for pos in snapshot:
                try:
                    current_price = get_current_price(pos["symbol"])
                except requests.exceptions.RequestException:
                    logger.warning("取得 %s 價格失敗，略過本輪檢查", pos["symbol"])
                    continue

                if pos["tp_price"] and current_price >= pos["tp_price"]:
                    logger.info("%s 觸及止盈（現價 %.8f >= 止盈 %.8f）", pos["symbol"], current_price, pos["tp_price"])
                    close_position_by_id(pos["id"], "止盈")
                elif pos["sl_price"] and current_price <= pos["sl_price"]:
                    logger.info("%s 觸及止損（現價 %.8f <= 止損 %.8f）", pos["symbol"], current_price, pos["sl_price"])
                    close_position_by_id(pos["id"], "止損")

        except Exception:
            logger.exception("監控迴圈發生未預期錯誤，將於下一輪繼續")

        time.sleep(POLL_INTERVAL_SECONDS)


# ------------------------------------------------------------------
# API 路由
# ------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    if not API_KEY or not API_SECRET:
        logger.error("尚未設定 GATE_API_KEY / GATE_API_SECRET 環境變數")
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

    action = data.get("action", "order")

    try:
        if action == "close":
            symbol = data["symbol"]
            results = close_positions_by_symbol(symbol, "手動 Webhook 出場")
            return jsonify({"status": "ok", "closed": len(results), "results": results})

        symbol = data["symbol"]
        side = data["side"].upper()
        order_type = data.get("type", "MARKET").upper()
        quantity = data["quantity"]
        price = data.get("price")
        tp_pct = data.get("take_profit_pct")
        sl_pct = data.get("stop_loss_pct")

        if side not in ("BUY", "SELL"):
            return jsonify({"error": "side must be BUY or SELL"}), 400

        result = place_order(symbol, side, order_type, quantity, price)
        logger.info("下單結果：%s", result)

        position = None
        if side == "BUY" and (tp_pct or sl_pct):
            entry_price = float(price) if (order_type == "LIMIT" and price) else get_current_price(symbol)
            position = add_position(symbol, float(quantity), entry_price, tp_pct, sl_pct)

        return jsonify({"status": "ok", "result": result, "position": position})

    except (KeyError, ValueError) as e:
        return jsonify({"error": f"bad request: {e}"}), 400
    except requests.exceptions.RequestException as e:
        logger.exception("呼叫 Gate.io API 失敗")
        return jsonify({"error": f"gate api error: {e}"}), 502


@app.route("/positions", methods=["GET"])
def list_positions():
    if request.args.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    with positions_lock:
        return jsonify({"positions": positions, "dry_run": DRY_RUN})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "dry_run": DRY_RUN, "poll_interval_seconds": POLL_INTERVAL_SECONDS})


if __name__ == "__main__":
    if DRY_RUN:
        logger.info("目前為 DRY_RUN 模式，不會送出真實訂單")
    else:
        logger.warning("目前為正式模式，會送出真實訂單！")

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    app.run(host="0.0.0.0", port=5001)
