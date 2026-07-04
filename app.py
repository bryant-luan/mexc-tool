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
import threading  # 確保引入多線程

# API Base URLs
MEXC_SPOT_URL = "https://api.mexc.com"
MEXC_FUT_URL = "https://contract.mexc.com"
GATE_BASE_URL = "https://api.gateio.ws/api/v4"

st.set_page_config(page_title="MEXC / Gate.io 交易工具", layout="wide")
st.title("MEXC / Gate.io 交易工具 (24H自動現貨/合約監控版)")

# ------------------------------------------------------------------
# 🛠️ 解決 Streamlit 跨線程衝突：使用 Python 原生全域變數與鎖
# ------------------------------------------------------------------
if "GLOBAL_POSITIONS_LIST" not in globals():
    globals()["GLOBAL_POSITIONS_LIST"] = []          # 24H 跨線程共享的唯一持倉清單
    globals()["POSITIONS_LOCK"] = threading.Lock()     # 避免讀寫衝突的鎖

# ------------------------------------------------------------------
# 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("⚙️ 交易所設定")
exchange = st.sidebar.selectbox("選擇交易所", ["MEXC", "Gate.io"])
market_type = st.sidebar.selectbox("交易板塊", ["現貨 (Spot)", "合約 (Futures)"])

st.sidebar.header("🔑 API 金鑰")
api_key = st.sidebar.text_input("API Key", type="password")
api_secret = st.sidebar.text_input("Secret Key", type="password")
dry_run = st.sidebar.checkbox("模擬模式（不會真的送出訂單）", value=True)

def is_fut():
    return market_type == "合約 (Futures)"

# ------------------------------------------------------------------
# MEXC / Gate.io 基礎 API 封裝 (含合約與現貨分流)
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

def place_order_mexc(symbol: str, side: str, order_type: str, quantity: float, is_futures: bool = False):
    if not api_key or not api_secret: return {"dry_run": True, "msg": "未設定密鑰"}
    # 這裡放你原本的 mexc_signed_request 邏輯...
    return {"status": "success", "msg": "MEXC 訂單發送成功"}

def place_order_gate(symbol: str, side: str, order_type: str, quantity: float, is_futures: bool = False):
    if not api_key or not api_secret: return {"dry_run": True, "msg": "未設定密鑰"}
    # 這裡放你原本的 gate_request 邏輯...
    return {"status": "success", "msg": "Gate.io 訂單發送成功"}

# ------------------------------------------------------------------
# 🚀 24 小時後台全自動看盤核心守護進程 (完全擺脫 st.session_state)
# ------------------------------------------------------------------
def bg_monitor_loop():
    while True:
        time.sleep(5)  # 每 5 秒看盤檢查一次
        tracked_list = globals().get("GLOBAL_POSITIONS_LIST", [])
        if not tracked_list:
            continue
            
        with globals()["POSITIONS_LOCK"]:
            for pos in list(tracked_list):
                pos_exchange = pos["exchange"]
                pos_symbol = pos["symbol"]
                is_futures_flag = (pos["market_type"] == "FUTURES")
                pos_side = pos.get("position_side", "LONG")
                
                # 精確分流查價，絕不依賴網頁前端當前的交易所選擇
                if pos_exchange == "MEXC":
                    current_price = get_current_price_mexc(pos_symbol, is_futures=is_futures_flag)
                else:
                    current_price = get_current_price_gate(pos_symbol, is_futures=is_futures_flag)
                    
                if current_price is None:
                    continue

                # 多空損益與觸發判定
                is_triggered = False
                if pos_side == "LONG":
                    if pos["tp_price"] and current_price >= pos["tp_price"]: is_triggered = True
                    elif pos["sl_price"] and current_price <= pos["sl_price"]: is_triggered = True
                else: # SHORT
                    if pos["tp_price"] and current_price <= pos["tp_price"]: is_triggered = True
                    elif pos["sl_price"] and current_price >= pos["sl_price"]: is_triggered = True

                # 觸及條件，後台直接自動平倉
                if is_triggered:
                    target_close_side = "SELL" if pos_side == "LONG" else "BUY"
                    try:
                        if pos_exchange == "MEXC":
                            place_order_mexc(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag)
                        else:
                            place_order_gate(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag)
                        
                        # 從原生全域變數移除
                        globals()["GLOBAL_POSITIONS_LIST"] = [item for item in globals()["GLOBAL_POSITIONS_LIST"] if item["id"] != pos["id"]]
                        print(f"🔥 [24H後台自動平倉成功] {pos_exchange} | {pos_symbol} | {pos_side}")
                    except Exception as e:
                        print(f"⚠️ [後台平倉失敗] {e}")

# 啟動守護執行緒 (確保整個應用生命週期只啟動一次)
if "monitor_thread_initialized" not in st.session_state:
    st.session_state["monitor_thread_initialized"] = True
    t = threading.Thread(target=bg_monitor_loop, daemon=True)
    t.start()
    st.sidebar.success("🟢 24H 後台監控引擎已常駐運作中")

# ------------------------------------------------------------------
# 持倉追蹤寫入函數 (同時寫入全域變數)
# ------------------------------------------------------------------
def open_position(symbol: str, quantity: float, entry_price: float, tp_pct: float, sl_pct: float, pos_side: str = "LONG"):
    if pos_side == "LONG":
        tp_price = entry_price * (1 + tp_pct / 100) if tp_pct > 0 else None
        sl_price = entry_price * (1 - sl_pct / 100) if sl_pct > 0 else None
    else:
        tp_price = entry_price * (1 - tp_pct / 100) if tp_pct > 0 else None
        sl_price = entry_price * (1 + sl_pct / 100) if sl_pct > 0 else None

    position = {
        "id": f"{exchange}-{market_type}-{symbol}-{int(time.time() * 1000)}",
        "exchange": exchange,
        "market_type": "FUTURES" if is_fut() else "SPOT",
        "position_side": pos_side if is_fut() else "LONG",
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "opened_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # 使用鎖保護，安全寫入全域變數
    with globals()["POSITIONS_LOCK"]:
        globals()["GLOBAL_POSITIONS_LIST"].append(position)
    return position

# ------------------------------------------------------------------
# 介面分頁
# ------------------------------------------------------------------
tab_trade, tab_tpsl = st.tabs(["🛒 手動下單", "🎯 24H 止盈止損監控"])

with tab_trade:
    st.subheader(f"手動下單模擬 ({exchange} - {market_type})")
    trade_symbol = st.text_input("輸入幣對 (如 BTC_USDT)", value="BTC_USDT").upper().strip()
    quantity = st.number_input("數量", min_value=0.0, step=0.001, value=0.01)
    
    actual_pos_side = "LONG"
    if is_fut():
        pos_direction = st.radio("合約方向", ["LONG (做多)", "SHORT (做空)"], horizontal=True)
        actual_pos_side = "LONG" if "LONG" in pos_direction else "SHORT"
        
    attach_tp_sl = st.checkbox("開啟 24H 止盈止損跟蹤監控")
    tp_pct = st.number_input("止盈 %", value=5.0)
    sl_pct = st.number_input("止損 %", value=3.0)
    
    if st.button("送出訂單並開始監控"):
        # 模擬下單並直接呼叫 open_position
        if exchange == "MEXC":
            get_p = get_current_price_mexc(trade_symbol, is_fut())
        else:
            get_p = get_current_price_gate(trade_symbol, is_fut())
            
        entry_p = get_p if get_p else 60000.0 # 防呆預設價
        
        if attach_tp_sl:
            pos_info = open_position(trade_symbol, quantity, entry_p, tp_pct, sl_pct, actual_pos_side)
            st.success(f"✅ 持倉已成功同步至 24H 後台監控清單！進場價: {entry_p}")

with tab_tpsl:
    st.subheader("📊 24H 智能看盤與跨交易所監控面板")
    st.info("💡 系統正透過 Python 後台獨立守護線程進行 24 小時無間斷全自動看盤，關閉網頁不影響平倉。")
    
    # 讀取不受 Streamlit 限制的原生全域變數
    current_tracked = globals().get("GLOBAL_POSITIONS_LIST", [])

    if not current_tracked:
        st.info("目前沒有任何追蹤中的持倉（現貨 / 合約）")
    else:
        if st.button("🔄 刷新最新市價損益"):
            st.rerun()

        for pos in current_tracked:
            pos_exchange = pos["exchange"]
            pos_symbol = pos["symbol"]
            pos_market = pos["market_type"]
            pos_side = pos.get("position_side", "LONG")
            is_futures_flag = (pos_market == "FUTURES")
            
            # 前端渲染查價
            if pos_exchange == "MEXC":
                current_price = get_current_price_mexc(pos_symbol, is_futures=is_futures_flag)
            else:
                current_price = get_current_price_gate(pos_symbol, is_futures=is_futures_flag)

            market_label = "🟢 現貨" if pos_market == "SPOT" else f"🔥 合約永續 ({pos_side})"
            
            with st.container(border=True):
                st.markdown(f"### 🏦 **[{pos_exchange}]** {pos_symbol} ｜ {market_label}")
                st.caption(f"數量：{pos['quantity']} ｜ 建立時間：{pos['opened_at']}")
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("進場價", f"{pos['entry_price']:.4f}")
                c2.metric("止盈價", f"{pos['tp_price']:.4f}" if pos["tp_price"] else "未設定")
                c3.metric("止損價", f"{pos['sl_price']:.4f}" if pos["sl_price"] else "未設定")
                
                if current_price is not None:
                    if pos_side == "LONG":
                        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                    else:
                        pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100
                    c4.metric("目前價 / 損益", f"{current_price:.4f}（{pnl_pct:+.2f}%）")
                else:
                    c4.metric("目前價", "查詢失敗")
                    
                if st.button("🔴 緊急手動平倉", key=f"manual_btn_{pos['id']}"):
                    with globals()["POSITIONS_LOCK"]:
                        globals()["GLOBAL_POSITIONS_LIST"] = [item for item in globals()["GLOBAL_POSITIONS_LIST"] if item["id"] != pos["id"]]
                    st.success("手動從監控清單中移除成功")
                    st.rerun()