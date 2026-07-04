import time
import hmac
import hashlib
import requests
import streamlit as st
import pandas as pd
from datetime import datetime

# 交易所 Base URL
MEXC_FUT_URL = "https://contract.mexc.com"

# 🤖 Freqtrade 預設連線
FREQTRADE_API_URL = "http://127.0.0.1:8080/api/v1"
FREQ_USER = "admin"
FREQ_PASS = "your_password"

st.set_page_config(page_title="MEXC 智慧量化終端", layout="wide")
st.title("🎛️ 智能量化、實時持倉與 CryptoQuant 自動跟單終端")

# ------------------------------------------------------------------
# ⚙️ 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 CryptoQuant 智慧跟單設定")
cq_api_key = st.sidebar.text_input("CryptoQuant Token", type="password", value="demo_mode", key="cq_token")
auto_trade_enabled = st.sidebar.toggle("🤖 啟用巨鯨雷達「自動下單」", value=False)
whale_threshold = st.sidebar.number_input("自動下單觸發值 (Whale Ratio > 顯示值)", value=0.55, step=0.01)
auto_trade_vol = st.sidebar.number_input("自動下單張數 (Vol)", value=1, min_value=1)
auto_trade_symbol = st.sidebar.selectbox("自動下單幣種", ["GWEI_USDT", "BTC_USDT", "ETH_USDT"])

st.sidebar.header("🎯 MEXC 止盈止損基準")
tp_pct = st.sidebar.number_input("自動止盈 %", value=5.0, step=0.5)
sl_pct = st.sidebar.number_input("自動止損 %", value=3.0, step=0.5)

# 初始化自動下單的安全狀態鎖（防止 8 秒重整一次就重複下單）
if "last_triggered_time" not in st.session_state:
    st.session_state.last_triggered_time = ""
if "auto_trade_logs" not in st.session_state:
    st.session_state.auto_trade_logs = []

# ------------------------------------------------------------------
# 🔒 MEXC 官方簽章加密與下單邏輯
# ------------------------------------------------------------------
def mexc_headers_and_sign(path, a_key, a_secret, body_str=""):
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{a_key}{timestamp}{body_str}"
    signature = hmac.new(a_secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()
    return {"ApiKey": a_key, "Request-Time": timestamp, "Signature": signature, "Content-Type": "application/json"}

def place_mexc_futures_order(a_key, a_secret, symbol, side, order_type, vol, price=0):
    import json
    path = "/api/v1/private/order/submit"
    payload = {
        "symbol": symbol,
        "price": float(price) if order_type == 1 else 0,
        "vol": int(vol),
        "leverage": 10,
        "side": int(side),
        "type": int(order_type),
        "openType": 1,
    }
    body_str = json.dumps(payload, separators=(',', ':'))
    headers = mexc_headers_and_sign(path, a_key, a_secret, body_str=body_str)
    try:
        resp = requests.post(f"{MEXC_FUT_URL}{path}", headers=headers, data=body_str, timeout=5)
        return resp.json()
    except Exception as e:
        return {"success": False, "message": f"連線異常: {str(e)}"}

def fetch_mexc_positions(a_key, a_secret):
    if not a_key or not a_secret: return {"success": False, "msg": "未輸入 API 金鑰"}
    try:
        path = "/api/v1/private/position/open_positions"
        headers = mexc_headers_and_sign(path, a_key, a_secret)
        resp = requests.get(f"{MEXC_FUT_URL}{path}", headers=headers, timeout=5)
        return resp.json()
    except Exception as e: return {"success": False, "msg": str(e)}

# ------------------------------------------------------------------
# 🕵️ CryptoQuant 鏈上數據抓取
# ------------------------------------------------------------------
def fetch_cryptoquant_data(token):
    if not token or token == "demo_mode":
        import random
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 隨機產生指標，讓你有機會觸發自動下單測試
        mock_ratio = round(random.uniform(0.48, 0.62), 2)
        return [
            {"date": now_str, "交易所合約流入量(Inflow)": random.randint(1500, 2600), "巨鯨交易比率(Whale Ratio)": mock_ratio, "市場訊號": "大戶異動"}
        ]
    try:
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get("https://api.cryptoquant.com/v1/btc/exchange-flows/inflow", headers=headers, timeout=5)
        if resp.status_code == 200: return resp.json().get("result", {}).get("data", [])
        return []
    except Exception: return []

# ------------------------------------------------------------------
# 🗂️ 四個分頁定義
# ------------------------------------------------------------------
tab_mexc, tab_order, tab_freqtrade, tab_whale = st.tabs([
    "🚀 MEXC 實時持倉", "⚡ MEXC 電腦版快捷下單", "🤖 Freqtrade 策略控制台", "🕵️ CryptoQuant 巨鯨雷達"
])

# ==========================================
# 【背景核心：CryptoQuant 自動下單監聽引擎】
# ==========================================
# 無論切換到哪個分頁，這段程式碼在每次重整時都會偷偷在背景檢查指標！
cq_data = fetch_cryptoquant_data(cq_api_key)
if cq_data and auto_trade_enabled:
    latest_data = cq_data[0]
    current_whale_ratio = latest_data["巨鯨交易比率(Whale Ratio)"]
    current_data_time = latest_data["date"]
    
    # 💥 條件觸發：如果當前巨鯨比率高於設定值，且這一秒的數據還沒下過單
    if current_whale_ratio > whale_threshold and st.session_state.last_triggered_time != current_data_time:
        if not api_key or not api_secret:
            st.sidebar.error("🚨 巨鯨雷達觸發！但因未填寫 MEXC API，自動下單失敗。")
        else:
            # 執行自動下單 (預設高勝率巨鯨出現時自動開多單 side=1, 市價單 order_type=5)
            order_res = place_mexc_futures_order(
                api_key, api_secret, 
                symbol=auto_trade_symbol, 
                side=1, order_type=5, 
                vol=auto_trade_vol
            )
            
            # 紀錄 log
            log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if order_res.get("success"):
                log_msg = f"✅ 【自動下單成功】時間: {log_time} | 指標值: {current_whale_ratio} | 標的: {auto_trade_symbol} | 張數: {auto_trade_vol} | 訂單ID: {order_res.get('data')}"
            else:
                log_msg = f"❌ 【自動下單失敗】時間: {log_time} | 原因: {order_res.get('message')}"
            
            st.session_state.auto_trade_logs.insert(0, log_msg)
            # 鎖定這個時間戳記，防止 8 秒後重複下單
            st.session_state.last_triggered_time = current_data_time

# ==========================================
# 【分頁一：MEXC 實時持倉】
# ==========================================
with tab_mexc:
    if not api_key or not api_secret: st.warning("👋 請在左側輸入您的 MEXC API 金鑰。")
    else:
        res = fetch_mexc_positions(api_key, api_secret)
        if res.get("success"):
            active_positions = [(p, float(p.get("holdVol", 0))) for p in res.get("data", []) if float(p.get("holdVol", 0)) > 0]
            if not active_positions: st.info("⏳ 目前沒有任何開倉中的合約部位。")
            else:
                for pos, size in active_positions:
                    with st.container(border=True):
                        st.markdown(f"#### 🪙 {pos.get('symbol')} ｜ 持倉: {int(size)} 張 ｜ 未實現盈虧: `{pos.get('unRealizedPnl')} USDT`")

# ==========================================
# 【分頁二：快捷下單】 & 【分頁三：Freqtrade】
# ==========================================
with tab_order:
    st.markdown("### ⚡ MEXC 手動快捷下單（已與自動化共存）")
with tab_freqtrade:
    st.markdown("### 🤖 Freqtrade 遠端監控")

# ==========================================
# 【分頁四：🕵️ CryptoQuant 巨鯨雷達 + 自動跟單日誌】
# ==========================================
with tab_whale:
    st.markdown("### 🕵️ CryptoQuant 鏈上自動化量化雷達")
    
    if cq_data:
        latest = cq_data[0]
        c1, c2 = st.columns(2)
        c1.metric("實時巨鯨交易比率 (Whale Ratio)", f"{latest['巨鯨交易比率(Whale Ratio)']}")
        c2.metric("自動下單狀態", "🟢 監聽自動下單中" if auto_trade_enabled else "⚪ 已關閉自動化")
        
        # 顯示自動下單日誌牆
        st.markdown("#### 📜 巨鯨雷達 - 自動下單執行日誌 (實時更新)")
        if st.session_state.auto_trade_logs:
            for log in st.session_state.auto_trade_logs:
                if "成功" in log: st.success(log)
                else: st.error(log)
        else:
            st.info("💡 目前尚無觸發紀錄。當前巨鯨指標高於側邊欄設定的臨界值時，下單紀錄會立刻噴在這裡。")

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制 (8秒)
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()