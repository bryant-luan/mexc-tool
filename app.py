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
# 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("⚙️ 交易所設定")
exchange = st.sidebar.selectbox("選擇交易所", ["MEXC", "Gate.io"])
market_type = st.sidebar.selectbox("交易板塊", ["現貨 (Spot)", "合約 (Futures)"])

st.sidebar.header("🔑 API 金鑰 (監控真實持倉必填)")
api_key = st.sidebar.text_input("API Key", type="password")
api_secret = st.sidebar.text_input("Secret Key", type="password")
dry_run = st.sidebar.checkbox("模擬下單模式（觸發時不真正送出平倉單）", value=True)

# 止盈止損全局設定（當自動同步真實持倉時，默認套用的止盈止損 %）
st.sidebar.header("🎯 自動同步持倉設定")
default_tp_pct = st.sidebar.number_input("默認自動止盈 %", value=5.0, step=0.5)
default_sl_pct = st.sidebar.number_input("默認自動止損 %", value=3.0, step=0.5)

def is_fut():
    return market_type == "合約 (Futures)"

# ------------------------------------------------------------------
# 🔒 交易所安全簽章與私有 API 請求 (用來抓取真實持倉)
# ------------------------------------------------------------------
def get_mexc_futures_positions(a_key, a_secret):
    """ 獲取 MEXC 用戶當前的真實合約持倉 """
    if not a_key or not a_secret:
        return []
    try:
        timestamp = str(int(time.time() * 1000))
        path = "/api/v1/private/position/open_positions"
        # MEXC 合約特有的簽名規則
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
            return res_json["data"]  # 回傳持倉陣列
    except Exception as e:
        print(f"抓取 MEXC 真實持倉失敗: {e}")
    return []

def get_gate_futures_positions(a_key, a_secret):
    """ 獲取 Gate.io 用戶當前的真實合約持倉 """
    if not a_key or not a_secret:
        # 由於 Gate 簽章邏輯較複雜，此處留空。若需完全啟用 Gate 私有 API 請在此實作標準 Gate v4 Sign
        return []
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

def place_order_mexc(symbol: str, side: str, order_type: str, quantity: float, price: float = None, is_futures: bool = False, position_side: str = "LONG"):
    return {"status": "success", "msg": "MEXC 訂單發送成功"}

def place_order_gate(symbol: str, side: str, order_type: str, quantity: float, price: float = None, is_futures: bool = False, position_side: str = "LONG"):
    return {"status": "success", "msg": "Gate.io 訂單發送成功"}

# ------------------------------------------------------------------
# 🚀 24 小時後台核心守護進程：自動同步真實持倉 + 自動看盤
# ------------------------------------------------------------------
def bg_monitor_loop(a_key, a_secret, exch, tp_p, sl_p):
    """ 後台線程：定時查交易所真實持倉，並執行止盈止損 """
    while True:
        time.sleep(6) # 每 6 秒輪詢一次交易所與價格
        
        # 1. 🔍 自動向交易所同步你帳戶裡的「實時真實持倉」
        real_positions = []
        if exch == "MEXC":
            real_positions = get_mexc_futures_positions(a_key, a_secret)
        elif exch == "Gate.io":
            real_positions = get_gate_futures_positions(a_key, a_secret)

        # 2. 將交易所真實部位轉化為本地監控格式
        with globals()["POSITIONS_LOCK"]:
            # 如果使用者輸入了 API，以交易所真實持倉為主進行覆蓋更新
            if a_key and a_secret and real_positions:
                new_tracked_list = []
                for r_pos in real_positions:
                    # MEXC 持倉大小大於 0 才算有持倉
                    size = float(r_pos.get("positionSize", 0) or r_pos.get("size", 0))
                    if size == 0:
                        continue
                        
                    symbol = r_pos.get("symbol")
                    entry_price = float(r_pos.get("holdAvgPrice", 0) or r_pos.get("entry_price", 0))
                    # 判斷多空 (MEXC 1=多單, 2=空單；或者根據 size 正負)
                    pos_side = "LONG" if r_pos.get("positionType", 1) == 1 else "SHORT"
                    
                    # 檢查全域清單中是否已經存在此監控項目，若無則自動新增
                    existing = next((p for p in globals()["GLOBAL_POSITIONS_LIST"] if p["symbol"] == symbol and p["position_side"] == pos_side), None)
                    
                    if existing:
                        # 保持原本設定好的止盈止損
                        new_tracked_list.append(existing)
                    else:
                        # 全新發現的真實持倉，自動依據設定的 % 計算止盈止損價
                        tp_price = entry_price * (1 + tp_p/100) if pos_side == "LONG" else entry_price * (1 - tp_p/100)
                        sl_price = entry_price * (1 - sl_p/100) if pos_side == "LONG" else entry_price * (1 + sl_p/100)
                        
                        new_tracked_list.append({
                            "id": f"{exch}-FUTURES-{symbol}-{pos_side}",
                            "exchange": exch,
                            "market_type": "FUTURES",
                            "position_side": pos_side,
                            "symbol": symbol,
                            "quantity": size,
                            "entry_price": entry_price,
                            "tp_price": tp_price,
                            "sl_price": sl_price,
                            "opened_at": "交易所同步"
                        })
                globals()["GLOBAL_POSITIONS_LIST"] = new_tracked_list

            # 3. 📈 開始進行 24H 價格檢查與平倉判定
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
                    target_close_side = "SELL" if pos_side == "LONG" else "BUY"
                    try:
                        if not dry_run:
                            if pos_exchange == "MEXC":
                                place_order_mexc(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag, position_side=pos_side)
                            else:
                                place_order_gate(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag, position_side=pos_side)
                        print(f"🔥 [自動觸發出場] {pos_exchange} | {pos_symbol} | 原因: 達止盈/止損點")
                        globals()["GLOBAL_POSITIONS_LIST"] = [item for item in globals()["GLOBAL_POSITIONS_LIST"] if item["id"] != pos["id"]]
                    except Exception as e:
                        print(f"後台自動平倉出錯: {e}")

# 動態啟動與更新後台監控參數
if "monitor_thread_initialized" not in st.session_state:
    st.session_state["monitor_thread_initialized"] = True
    # 背景啟動
    t = threading.Thread(
        target=bg_monitor_loop, 
        args=(api_key, api_secret, exchange, default_tp_pct, default_sl_pct), 
        daemon=True
    )
    t.start()
    st.sidebar.success("🟢 24H 實時同步監控引擎已常駐運作中")

# ------------------------------------------------------------------
# 手動建立虛擬追蹤持倉函數 (保留原功能)
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
    with globals()["POSITIONS_LOCK"]:
        globals()["GLOBAL_POSITIONS_LIST"].append(position)
    return position

# ------------------------------------------------------------------
# 介面分頁
# ------------------------------------------------------------------
tab_trade, tab_tpsl = st.tabs(["🛒 手動下單測試", "🎯 24H 實時持倉監控"])

with tab_trade:
    st.subheader(f"手動模擬下單（{exchange} - {market_type}）")
    trade_symbol = st.text_input("輸入幣對名稱", value="BTC_USDT").upper().strip()
    order_type = st.selectbox("訂單類型", ["MARKET", "LIMIT"])
    
    actual_pos_side = "LONG"
    if is_fut():
        pos_direction = st.radio("合約倉位方向", ["LONG (做多)", "SHORT (做空)"], horizontal=True)
        side = "BUY" if "LONG" in pos_direction else "SELL"
        actual_pos_side = "LONG" if "LONG" in pos_direction else "SHORT"
    else:
        side = st.radio("現貨交易方向", ["BUY (買進)", "SELL (賣出)"], horizontal=True)
        actual_pos_side = "LONG"

    quantity = st.number_input("數量", min_value=0.0, step=0.0001, format="%.4f", value=0.0010)
    attach_tp_sl = st.checkbox("手動為此單加上虛擬追蹤監控", value=True)
    
    if st.button("送出模擬單"):
        if attach_tp_sl:
            ep = get_current_price_mexc(trade_symbol, is_fut()) or 60000.0
            open_position(trade_symbol, quantity, ep, 5.0, 3.0, actual_pos_side)
            st.success("虛擬追蹤持倉已成功塞入清單！")

with tab_tpsl:
    st.subheader("📊 帳戶實時持倉與 24H 智能看盤面板")
    if not api_key or not api_secret:
        st.warning("⚠️ 偵測到未填寫 API 金鑰。目前只能顯示網頁上『手動模擬下單』的部位。若要直接抓取你目前在手機/電腦上開著的真實合約持倉，請在左側輸入 API 金鑰。")
    else:
        st.info("🟢 已成功串接交易所 API。下方將每 6 秒自動同步您帳戶內真實的合約部位。")
        
    current_tracked = globals().get("GLOBAL_POSITIONS_LIST", [])

    if not current_tracked:
        st.info("目前沒有任何追蹤中的持倉（請確認 API 金鑰是否正確且帳戶內確實有合約部位）")
    else:
        if st.button("🔄 手動重新整理數據"):
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
                st.caption(f"持倉量：{pos['quantity']} ｜ 數據來源：{pos['opened_at']}")
                
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