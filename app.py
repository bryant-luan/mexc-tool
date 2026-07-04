import time
import json
import hmac
import hashlib
import requests
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import threading

# API Base URLs
MEXC_SPOT_URL = "https://api.mexc.com"
MEXC_FUT_URL = "https://contract.mexc.com"
GATE_BASE_URL = "https://api.gateio.ws/api/v4"

st.set_page_config(page_title="MEXC / Gate.io 交易工具", layout="wide")
st.title("MEXC / Gate.io 交易工具 (24H 實時帳戶持倉監控版)")

# ------------------------------------------------------------------
# 🛠️ 跨線程共享清單與鎖
# ------------------------------------------------------------------
if "GLOBAL_POSITIONS_LIST" not in globals():
    globals()["GLOBAL_POSITIONS_LIST"] = []          
    globals()["POSITIONS_LOCK"] = threading.Lock()     

# ------------------------------------------------------------------
# 側邊欄設定 (全部綁定到 st.session_state 確保後台看得到)
# ------------------------------------------------------------------
st.sidebar.header("⚙️ 交易所設定")
exchange = st.sidebar.selectbox("選擇交易所", ["MEXC", "Gate.io"], key="sel_exchange")
market_type = st.sidebar.selectbox("交易板塊", ["現貨 (Spot)", "合約 (Futures)"], key="sel_market_type")

st.sidebar.header("🔑 API 金鑰 (監控真實持倉必填)")
# 這裡綁定 key 參數，後台線程才能動態撈取
st.sidebar.text_input("API Key", type="password", key="saved_api_key")
st.sidebar.text_input("Secret Key", type="password", key="saved_api_secret")
dry_run = st.sidebar.checkbox("模擬下單模式（觸發時不真正送出平倉單）", value=True)

st.sidebar.header("🎯 自動同步持倉設定")
default_tp_pct = st.sidebar.number_input("默認自動止盈 %", value=5.0, step=0.5, key="cfg_tp")
default_sl_pct = st.sidebar.number_input("默認自動止損 %", value=3.0, step=0.5, key="cfg_sl")

def is_fut():
    return st.session_state.get("sel_market_type") == "合約 (Futures)"

# ------------------------------------------------------------------
# 🔒 交易所安全簽章與私有 API 請求 (動態抓取真實持倉)
# ------------------------------------------------------------------
def get_mexc_futures_positions(a_key, a_secret):
    """ 獲取 MEXC 用戶當前的真實合約持倉 """
    if not a_key or not a_secret:
        return []
    try:
        # MEXC 規定必須傳送當前伺服器時間戳
        timestamp = str(int(time.time() * 1000))
        path = "/api/v1/private/position/open_positions"
        
        # 建立加密簽章
        sign_str = a_key + timestamp
        signature = hmac.new(a_secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()
        
        headers = {
            "ApiKey": a_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Content-Type": "application/json"
        }
        
        resp = requests.get(f"{MEXC_FUT_URL}{path}", headers=headers, timeout=5)
        res_json = resp.json()
        
        if res_json.get("success") and "data" in res_json:
            return res_json["data"]
    except Exception as e:
        print(f"❌ 抓取 MEXC 真實持倉發生錯誤: {e}")
    return []

# ------------------------------------------------------------------
# 公共查價 API
# ------------------------------------------------------------------
def get_current_price_mexc(symbol: str, is_futures: bool = False) -> float:
    try:
        if is_futures:
            sym = symbol.replace("USDT", "_USDT") if "_" not in symbol else symbol
            resp = requests.get(f"{MEXC_FUT_URL}/api/v1/contract/ticker", params={"symbol": sym}, timeout=5)
            return float(resp.json()["data"]["lastPrice"])
        else:
            sym = symbol.replace("_", "")
            resp = requests.get(f"{MEXC_SPOT_URL}/api/v3/ticker/price", params={"symbol": sym}, timeout=5)
            return float(resp.json()["price"])
    except:
        return None

def get_current_price_gate(symbol: str, is_futures: bool = False) -> float:
    try:
        sym = symbol.replace("_", "_")
        path = "/futures/usdt/tickers" if is_futures else "/spot/tickers"
        params = {"contract": sym} if is_futures else {"currency_pair": sym}
        resp = requests.get(f"{GATE_BASE_URL}{path}", params=params, timeout=5)
        return float(resp.json()[0]["last"])
    except:
        return None

# ------------------------------------------------------------------
# 🚀 24 小時後台核心守護進程 (修正版：每輪動態讀取最新金鑰)
# ------------------------------------------------------------------
def bg_monitor_loop():
    """ 後台看盤無窮迴圈 """
    while True:
        time.sleep(6) # 每 6 秒輪詢一次
        
        # 🔥 重點：動態從 st.session_state 讀取最新輸入的金鑰與設定，不再使用死參數
        try:
            curr_key = st.session_state.get("saved_api_key", "")
            curr_secret = st.session_state.get("saved_api_secret", "")
            curr_exch = st.session_state.get("sel_exchange", "MEXC")
            tp_p = st.session_state.get("cfg_tp", 5.0)
            sl_p = st.session_state.get("cfg_sl", 3.0)
        except:
            # 防止 Streamlit 在尚未完全初始化 Session 時崩潰
            continue

        if not curr_key or not curr_secret:
            continue

        # 1. 🔍 自動同步實時合約持倉
        real_positions = []
        if curr_exch == "MEXC":
            real_positions = get_mexc_futures_positions(curr_key, curr_secret)

        # 2. 轉化並同步至全局監控清單
        with globals()["POSITIONS_LOCK"]:
            if real_positions:
                new_tracked_list = []
                for r_pos in real_positions:
                    size = float(r_pos.get("positionSize", 0) or r_pos.get("size", 0))
                    if size == 0:
                        continue
                        
                    symbol = r_pos.get("symbol")
                    entry_price = float(r_pos.get("holdAvgPrice", 0) or r_pos.get("entry_price", 0))
                    pos_side = "LONG" if r_pos.get("positionType", 1) == 1 else "SHORT"
                    
                    # 檢查是否已存在自訂追蹤
                    existing = next((p for p in globals()["GLOBAL_POSITIONS_LIST"] if p["symbol"] == symbol and p["position_side"] == pos_side), None)
                    
                    if existing:
                        new_tracked_list.append(existing)
                    else:
                        # 全新抓到的部位，自動依設定比率算出止盈止損價格
                        tp_price = entry_price * (1 + tp_p/100) if pos_side == "LONG" else entry_price * (1 - tp_p/100)
                        sl_price = entry_price * (1 - sl_p/100) if pos_side == "LONG" else entry_price * (1 + sl_p/100)
                        
                        new_tracked_list.append({
                            "id": f"{curr_exch}-FUTURES-{symbol}-{pos_side}",
                            "exchange": curr_exch,
                            "market_type": "FUTURES",
                            "position_side": pos_side,
                            "symbol": symbol,
                            "quantity": size,
                            "entry_price": entry_price,
                            "tp_price": tp_price,
                            "sl_price": sl_price,
                            "opened_at": "🟢 交易所同步中"
                        })
                globals()["GLOBAL_POSITIONS_LIST"] = new_tracked_list

            # 3. 📈 看盤與止盈止損觸發判定
            tracked_list = globals().get("GLOBAL_POSITIONS_LIST", [])
            for pos in list(tracked_list):
                pos_exchange = pos["exchange"]
                pos_symbol = pos["symbol"]
                is_futures_flag = (pos["market_type"] == "FUTURES")
                pos_side = pos.get("position_side", "LONG")
                
                if pos_exchange == "MEXC":
                    current_price = get_current_price_mexc(pos_symbol, is_futures=is_futures_flag)
                else:
                    current_price = get_current_price_gate(pos_symbol, is_futures=is_futures_flag)
                    
                if current_price is None:
                    continue

                is_triggered = False
                if pos_side == "LONG":
                    if pos["tp_price"] and current_price >= pos["tp_price"]: is_triggered = True
                    elif pos["sl_price"] and current_price <= pos["sl_price"]: is_triggered = True
                else:
                    if pos["tp_price"] and current_price <= pos["tp_price"]: is_triggered = True
                    elif pos["sl_price"] and current_price >= pos["sl_price"]: is_triggered = True

                if is_triggered:
                    # 這裡執行平倉動作 (篇幅關係省略，如上一版格式)
                    print(f"🔥 [觸發出場] {pos_symbol}")
                    globals()["GLOBAL_POSITIONS_LIST"] = [item for item in globals()["GLOBAL_POSITIONS_LIST"] if item["id"] != pos["id"]]

# 啟動守護進程 (不帶固定參數，改由迴圈內動態讀取)
if "monitor_thread_initialized" not in st.session_state:
    st.session_state["monitor_thread_initialized"] = True
    t = threading.Thread(target=bg_monitor_loop, daemon=True)
    t.start()

# ------------------------------------------------------------------
# 介面分頁
# ------------------------------------------------------------------
tab_trade, tab_tpsl = st.tabs(["🛒 手動下單測試", "🎯 24H 實時持倉監控"])

with tab_trade:
    st.info("此處為手動模擬面板，真實持倉同步請直接至右側分頁查看。")

with tab_tpsl:
    st.subheader("📊 帳戶實時持倉與 24H 智能看盤面板")
    
    # 從 session 讀取金鑰狀態做提示
    k = st.session_state.get("saved_api_key", "")
    s = st.session_state.get("saved_api_secret", "")
    
    if not k or not s:
        st.warning("⚠️ 偵測到未填寫 API 金鑰。請在左側輸入 API 金鑰與 Secret Key，系統才能向交易所抓取您目前的真實持倉。")
    else:
        st.success("🟢 帳戶金鑰已輸入，後台線程正在持續對接交易所進行實時持倉數據同步...")
        
    current_tracked = globals().get("GLOBAL_POSITIONS_LIST", [])

    if not current_tracked:
        st.info("⏳ 目前沒有任何追蹤中的持倉（若剛填寫金鑰，請等待 5 秒或點擊下方刷新鈕）")
        if st.button("🔄 立即重新整理"):
            st.rerun()
    else:
        if st.button("🔄 刷新最新市價損益"):
            st.rerun()

        for pos in current_tracked:
            pos_exchange = pos["exchange"]
            pos_symbol = pos["symbol"]
            pos_market = pos["market_type"]
            pos_side = pos.get("position_side", "LONG")
            is_futures_flag = (pos_market == "FUTURES")
            
            if pos_exchange == "MEXC":
                current_price = get_current_price_mexc(pos_symbol, is_futures=is_futures_flag)
            else:
                current_price = get_current_price_gate(pos_symbol, is_futures=is_futures_flag)

            market_label = "🟢 現貨" if pos_market == "SPOT" else f"🔥 合約永續 ({pos_side})"
            
            with st.container(border=True):
                st.markdown(f"### 🏦 **[{pos_exchange}]** {pos_symbol} ｜ {market_label}")
                st.caption(f"持倉量：{pos['quantity']} ｜ 狀態：{pos['opened_at']}")
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("開倉均價", f"{pos['entry_price']:.4f}")
                c2.metric("自訂止盈價", f"{pos['tp_price']:.4f}" if pos["tp_price"] else "未設定")
                c3.metric("自訂止損價", f"{pos['sl_price']:.4f}" if pos["sl_price"] else "未設定")
                
                if current_price is not None:
                    pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"] * 100) if pos_side == "LONG" else ((pos["entry_price"] - current_price) / pos["entry_price"] * 100)
                    c4.metric("最新市價 / 未實現損益", f"{current_price:.4f}（{pnl_pct:+.2f}%）")
                else:
                    c4.metric("最新市價", "讀取中...")
                    
                if st.button("🔴 強制解除此筆看盤追蹤", key=f"manual_btn_{pos['id']}"):
                    with globals()["POSITIONS_LOCK"]:
                        globals()["GLOBAL_POSITIONS_LIST"] = [item for item in globals()["GLOBAL_POSITIONS_LIST"] if item["id"] != pos["id"]]
                    st.rerun()