import time
import hmac
import hashlib
import requests

MEXC_FUT_URL = "https://contract.mexc.com"

def mexc_headers_and_sign(path, a_key, a_secret, body_str=""):
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{a_key}{timestamp}{body_str}"
    signature = hmac.new(a_secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()
    return {"ApiKey": a_key, "Request-Time": timestamp, "Signature": signature, "Content-Type": "application/json"}

def place_mexc_futures_order(a_key, a_secret, symbol, side, order_type, vol):
    import json
    path = "/api/v1/private/order/submit"
    payload = {
        "symbol": symbol,
        "price": 0,  
        "vol": int(vol),
        "leverage": 10,
        "side": int(side),  # 1=開多, 4=平多
        "type": int(order_type), 
        "openType": 1,
    }
    body_str = json.dumps(payload, separators=(',', ':'))
    headers = mexc_headers_and_sign(path, a_key, a_secret, body_str=body_str)
    try:
        resp = requests.post(f"{MEXC_FUT_URL}{path}", headers=headers, data=body_str, timeout=5)
        return resp.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def fetch_mexc_positions(a_key, a_secret):
    try:
        path = "/api/v1/private/position/open_positions"
        headers = mexc_headers_and_sign(path, a_key, a_secret)
        resp = requests.get(f"{MEXC_FUT_URL}{path}", headers=headers, timeout=5)
        res_json = resp.json()
        if res_json.get("success"):
            return {"success": True, "data": res_json.get("data", [])}
        return {"success": False, "msg": res_json.get("message")}
    except Exception as e:
        return {"success": False, "msg": str(e)}