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
import threading  # 新增：引入多線程模組

# API Base URLs
MEXC_SPOT_URL = "https://api.mexc.com"
MEXC_FUT_URL = "https://contract.mexc.com"
GATE_BASE_URL = "https://api.gateio.ws/api/v4"

st.set_page_config(page_title="24H自動監控交易工具", layout="wide")
st.title("MEXC / Gate.io 交易工具 (支援24H自動合約/現貨監控)")

# ------------------------------------------------------------------
# 全域執行緒鎖與 Session 初始
# ------------------------------------------------------------------
if "positions_lock" not in st.session_state:
    st.session_state["positions_lock"] = threading.Lock()

if "positions" not in st.session_state:
    st.session_state["positions"] = []

# 建立一個全域參照，方便後台線程存取（因為 Streamlit 重新渲染時 session_state 在非主線程可能存取受限）
if "global_positions" not in st.sidebar.__self__:
    # 這裡我們借用一個全域變數空間來跨線程共享資料
    st.sidebar.__self__.global_positions = []

# 同步 session_state 到全域參照
st.sidebar.__self__.global_positions = st.session_state["positions"]
position_lock = st.session_state["positions_lock"]

# --- [請保留你原有的 API 請求與下單函式：get_current_price_mexc, place_order_mexc, get_current_price_gate, place_order_gate 等] ---
# (為了篇幅，此處省略前面已寫過的 API 封裝，請維持上一版內容)

# ------------------------------------------------------------------
# 🚀 24 小時後台全自動看盤監控核心邏輯
# ------------------------------------------------------------------
def bg_monitor_loop():
    """ 24小時在後台默默執行的無窮迴圈（每 5 秒看盤一次） """
    while True:
        time.sleep(5)  # 看盤頻率（秒），可自行調整
        
        # 取得目前所有的持倉
        tracked_list = st.sidebar.__self__.global_positions
        if not tracked_list:
            continue
            
        triggered_any = False
        
        with position_lock:
            for pos in list(tracked_list):  # 使用 list 복사 避免遍歷時被修改
                pos_exchange = pos["exchange"]
                pos_symbol = pos["symbol"]
                pos_market = pos["market_type"]       # "SPOT" 或 "FUTURES"
                pos_side = pos.get("position_side", "LONG") # "LONG" 或 "SHORT"
                
                is_futures_flag = (pos_market == "FUTURES")
                
                # 1. 抓取最新價格
                try:
                    if pos_exchange == "MEXC":
                        current_price = get_current_price_mexc(pos_symbol, is_futures=is_futures_flag)
                    else:
                        current_price = get_current_price_gate(pos_symbol, is_futures=is_futures_flag)
                except Exception:
                    continue  # 網路超時或查價失敗，跳過這次等下一輪
                
                if current_price is None:
                    continue

                # 2. 智慧判定是否觸及止盈止損條件
                is_triggered = False
                trigger_reason = ""
                
                if pos_side == "LONG":  # 現貨或合約做多
                    if pos["tp_price"] and current_price >= pos["tp_price"]:
                        is_triggered = True
                        trigger_reason = "止盈"
                    elif pos["sl_price"] and current_price <= pos["sl_price"]:
                        is_triggered = True
                        trigger_reason = "止損"
                else:  # 合約做空 (SHORT)
                    if pos["tp_price"] and current_price <= pos["tp_price"]:
                        is_triggered = True
                        trigger_reason = "止盈"
                    elif pos["sl_price"] and current_price >= pos["sl_price"]:
                        is_triggered = True
                        trigger_reason = "止損"

                # 3. 如果觸及條件，後台「自動」發送平倉單！
                if is_triggered:
                    target_close_side = "SELL" if pos_side == "LONG" else "BUY"
                    try:
                        if pos_exchange == "MEXC":
                            place_order_mexc(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag)
                        else:
                            place_order_gate(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag)
                        
                        # 從追蹤清單移除
                        st.sidebar.__self__.global_positions = [item for item in st.sidebar.__self__.global_positions if item["id"] != pos["id"]]
                        st.session_state["positions"] = st.sidebar.__self__.global_positions
                        triggered_any = True
                        print(f"[🔥 後台自動觸發] {pos_exchange} {pos_symbol} ({pos_market}) 已自動 {trigger_reason} 出場！")
                    except Exception as e:
                        print(f"[⚠️ 後台平倉失敗] {pos_symbol}: {e}")
                        
        # 如果有仓位被自动触发平仓，重新刷新前端
        if triggered_any:
            try:
                st.rerun()
            except:
                pass

# 啟動後台看盤線程（確保全域只啟動一個，不會重複創建）
if "monitor_thread_started" not in st.sidebar.__self__:
    monitor_thread = threading.Thread(target=bg_monitor_loop, daemon=True)
    monitor_thread.start()
    st.sidebar.__self__.monitor_thread_started = True
    st.sidebar.success("🟢 24H 後台全自動看盤監控引擎：已啟動")


# ------------------------------------------------------------------
# Tab 4：止盈止損監控前端面板
# ------------------------------------------------------------------
# 把原本的開倉邏輯函數加上 Lock 保護
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
    
    with position_lock:
        st.session_state["positions"].append(position)
        st.sidebar.__self__.global_positions = st.session_state["positions"]
    return position


with tab_tpsl:
    st.subheader("📊 24H 智能看盤與止盈止損監控面板 (現貨/合約多空雙向)")
    st.info("💡 系統已開啟「24小時後台自動看盤模式」。即使不點擊刷新或關閉網頁，後台仍會每 5 秒幫您檢查並自動平倉出場！")

    # 讀取最新的持倉資料
    all_tracked_positions = st.session_state["positions"]

    if not all_tracked_positions:
        st.info("目前沒有任何追蹤中的持倉（現貨/合約）")
    else:
        # 提供手動刷新按鈕（主要是用來看最新價格與未實現損益）
        if st.button("🔄 手動刷新最新價格與損益"):
            st.rerun()

        for pos in all_tracked_positions:
            pos_exchange = pos["exchange"]
            pos_symbol = pos["symbol"]
            pos_market = pos["market_type"]
            pos_side = pos.get("position_side", "LONG")
            
            is_futures_flag = (pos_market == "FUTURES")
            
            # 動態匹配查價與平倉
            if pos_exchange == "MEXC":
                price_func = lambda sym: get_current_price_mexc(sym, is_futures=is_futures_flag)
                close_func = lambda sym, q, s_inner: place_order_mexc(sym, s_inner, "MARKET", q, is_futures=is_futures_flag)
            else:
                price_func = lambda sym: get_current_price_gate(sym, is_futures=is_futures_flag)
                close_func = lambda sym, q, s_inner: place_order_gate(sym, s_inner, "MARKET", q, is_futures=is_futures_flag)

            try:
                current_price = price_func(pos_symbol)
            except:
                current_price = None

            market_label = "🟢 現貨" if pos_market == "SPOT" else f"🔥 合約永續 ({pos_side})"
            
            with st.container(border=True):
                st.markdown(
                    f"### 🏦 **[{pos_exchange}]** {pos_symbol} ｜ {market_label}\n"
                    f"數量：{pos['quantity']} ｜ 建立時間：{pos['opened_at']}"
                )
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("進場價", f"{pos['entry_price']:.6f}")
                c2.metric("止盈價", f"{pos['tp_price']:.6f}" if pos["tp_price"] else "未設定")
                c3.metric("止損價", f"{pos['sl_price']:.6f}" if pos["sl_price"] else "未設定")
                
                if current_price is not None:
                    if pos_side == "LONG":
                        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                    else:
                        pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100
                    c4.metric("目前價 / 損益", f"{current_price:.6f}（{pnl_pct:+.2f}%）")
                else:
                    c4.metric("目前價", "查詢失敗")

                # 手動強制平倉按鈕邏輯
                if st.button("🔴 緊急手動平倉", key=f"manual_close_{pos['id']}"):
                    target_close_side = "SELL" if pos_side == "LONG" else "BUY"
                    with position_lock:
                        try:
                            result = close_func(pos["symbol"], pos["quantity"], target_close_side)
                            st.session_state["positions"] = [item for item in st.session_state["positions"] if item["id"] != pos["id"]]
                            st.sidebar.__self__.global_positions = st.session_state["positions"]
                            st.success("手動市價平倉成功！")
                            st.json(result)
                            st.rerun()
                        except Exception as e:
                            st.error(f"平倉失敗：{e}")