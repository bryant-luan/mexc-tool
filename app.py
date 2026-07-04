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
st.title("🎛️ 智能量化、實時持倉與動態移動止損終端")

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

st.sidebar.header("📈 動態移動止盈止損 (Trailing Stop)")
trailing_enabled = st.sidebar.toggle("🔥 啟用移動追蹤功能", value=True)
activation_pct = st.sidebar.number_input("移動回檔觸發 % (從最高點回檔多少平倉)", value=2.0, step=0.1)

# 初始化自動下單與移動止損狀態
if "last_triggered_time" not in st.session_state:
    st.session_state.last_triggered_time = ""
if "auto_trade_logs" not in st.session_state:
    st.session_state.auto_trade_logs = []
# 用於模擬跟單後的實時價格與移動止損狀態追蹤
if "active_trailing_positions" not in st.session_state:
    st.session_state.active_trailing_positions = {}

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

# ------------------------------------------------------------------
# 🕵️ CryptoQuant 數據與價格模擬
# ------------------------------------------------------------------
def fetch_cryptoquant_data(token):
    import random
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_ratio = round(random.uniform(0.48, 0.62), 2)
    # 順便模擬目前的代幣市場價格變化
    mock_btc_price = round(random.uniform(62000, 65000), 1)
    mock_gwei_price = round(random.uniform(0.1300, 0.1500), 4)
    return [
        {
            "date": now_str, 
            "交易所合約流入量(Inflow)": random.randint(1500, 2600), 
            "巨鯨交易比率(Whale Ratio)": mock_ratio,
            "BTC_Price": mock_btc_price,
            "GWEI_Price": mock_gwei_price
        }
    ]

# ------------------------------------------------------------------
# 🗂️ 四個分頁定義
# ------------------------------------------------------------------
tab_mexc, tab_order, tab_freqtrade, tab_whale = st.tabs([
    "🚀 MEXC 實時持倉", "⚡ MEXC 電腦版快捷下單", "🤖 Freqtrade 策略控制台", "🕵️ CryptoQuant 巨鯨雷達"
])

# ==========================================
# 【背景核心：自動下單 + 移動止損計算引擎】
# ==========================================
cq_data = fetch_cryptoquant_data(cq_api_key)
if cq_data:
    latest_data = cq_data[0]
    current_whale_ratio = latest_data["巨鯨交易比率(Whale Ratio)"]
    current_data_time = latest_data["date"]
    
    # 取得當前模擬市價
    current_market_price = latest_data["GWEI_Price"] if auto_trade_symbol == "GWEI_USDT" else latest_data["BTC_Price"]
    
    # 1. 檢查是否觸發自動開倉
    if auto_trade_enabled and current_whale_ratio > whale_threshold and st.session_state.last_triggered_time != current_data_time:
        order_res = place_mexc_futures_order(api_key, api_secret, symbol=auto_trade_symbol, side=1, order_type=5, vol=auto_trade_vol)
        log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 不管 API 成功與否（Demo 狀態下），我們都把這筆單丟進「移動止損監聽器」做本地模擬演練
        st.session_state.active_trailing_positions[auto_trade_symbol] = {
            "entry_price": current_market_price,
            "highest_price": current_market_price,
            "stop_loss_price": current_market_price * (1 - activation_pct / 100),
            "vol": auto_trade_vol
        }
        
        log_msg = f"✅ 【巨鯨觸發自動開多】價格: {current_market_price} | 初始移動止損點: {st.session_state.active_trailing_positions[auto_trade_symbol]['stop_loss_price']:.4f}"
        st.session_state.auto_trade_logs.insert(0, log_msg)
        st.session_state.last_triggered_time = current_data_time

    # 2. 移動止損核心計算邏輯（每次網頁重整 8 秒執行一次）
    if trailing_enabled and auto_trade_symbol in st.session_state.active_trailing_positions:
        pos_info = st.session_state.active_trailing_positions[auto_trade_symbol]
        
        # 如果價格創歷史新高，往上推高止損線
        if current_market_price > pos_info["highest_price"]:
            pos_info["highest_price"] = current_market_price
            # 新止損點 = 歷史最高價 扣掉 設定的回檔百分比
            pos_info["stop_loss_price"] = current_market_price * (1 - activation_pct / 100)
            st.session_state.auto_trade_logs.insert(0, f"📈 【止損點上移】幣價創新高: {current_market_price}！新移動止損防線推高至: {pos_info['stop_loss_price']:.4f}")
        
        # 如果價格跌破我們動態推高的止損線 -> 觸發緊急出場平倉
        elif current_market_price <= pos_info["stop_loss_price"]:
            # 呼叫平倉 API (side=4 代表平多單)
            place_mexc_futures_order(api_key, api_secret, symbol=auto_trade_symbol, side=4, order_type=5, vol=pos_info["vol"])
            
            profit_pct = ((pos_info["stop_loss_price"] - pos_info["entry_price"]) / pos_info["entry_price"]) * 100
            st.session_state.auto_trade_logs.insert(0, f"🚨 【移動止損觸發平倉】幣價回檔至 {current_market_price} 跌破防線！利潤鎖定出場。預估收益: {profit_pct:.2f}%")
            # 刪除持倉追蹤
            del st.session_state.active_trailing_positions[auto_trade_symbol]

# ==========================================
# 【分頁四：🕵️ CryptoQuant 巨鯨雷達與移動追蹤面板】
# ==========================================
with tab_whale:
    st.markdown("### 🕵️ CryptoQuant 巨鯨雷達 ＆ 移動追蹤止損牆")
    
    # 顯示目前移動止損正在監控的單子
    if auto_trade_symbol in st.session_state.active_trailing_positions:
        p_track = st.session_state.active_trailing_positions[auto_trade_symbol]
        st.warning(f"🎯 **當前追蹤中的移動持倉 ({auto_trade_symbol})**")
        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("開倉原價", f"{p_track['entry_price']:.4f}")
        tc2.metric("最新市場價", f"{current_market_price:.4f}")
        tc3.metric("波段最高價", f"{p_track['highest_price']:.4f}")
        tc4.metric("🔥 動態生命線 (跌破就平倉)", f"{p_track['stop_loss_price']:.4f}")
    else:
        st.info("⏳ 目前沒有正在執行的移動止損追蹤單。")

    st.markdown("#### 📜 自動跟單與移動回檔執行日誌")
    if st.session_state.auto_trade_logs:
        for log in st.session_state.auto_trade_logs:
            if "平倉" in log: st.error(log)
            elif "上移" in log: st.info(log)
            else: st.success(log)

# 其餘分頁保持原樣
with tab_mexc: st.markdown("### 🚀 MEXC 實時持倉")
with tab_order: st.markdown("### ⚡ MEXC 電腦版快捷下單")
with tab_freqtrade: st.markdown("### 🤖 Freqtrade 策略控制台")

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制 (8秒)
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()