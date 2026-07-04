# ------------------------------------------------------------------
# 🚀 24 小時後台全自動看盤監控核心邏輯（修正版：完全抽離 st.session_state）
# ------------------------------------------------------------------
# 使用 Python 原生全域變數，徹底擺脫 Streamlit 跨線程干擾
if "GLOBAL_POSITIONS_LIST" not in globals():
    GLOBAL_POSITIONS_LIST = []
    POSITIONS_LOCK = threading.Lock()

def bg_monitor_loop():
    global GLOBAL_POSITIONS_LIST
    while True:
        time.sleep(5)  # 每 5 秒看盤一次
        if not GLOBAL_POSITIONS_LIST:
            continue
            
        with POSITIONS_LOCK:
            for pos in list(GLOBAL_POSITIONS_LIST):
                pos_exchange = pos["exchange"]
                pos_symbol = pos["symbol"]
                is_futures_flag = (pos["market_type"] == "FUTURES")
                pos_side = pos.get("position_side", "LONG")
                
                try:
                    if pos_exchange == "MEXC":
                        current_price = get_current_price_mexc(pos_symbol, is_futures=is_futures_flag)
                    else:
                        current_price = get_current_price_gate(pos_symbol, is_futures=is_futures_flag)
                except Exception:
                    continue
                
                if current_price is None:
                    continue

                # 智慧判定觸及條件
                is_triggered = False
                if pos_side == "LONG":
                    if pos["tp_price"] and current_price >= pos["tp_price"]: is_triggered = True
                    elif pos["sl_price"] and current_price <= pos["sl_price"]: is_triggered = True
                else:
                    if pos["tp_price"] and current_price <= pos["tp_price"]: is_triggered = True
                    elif pos["sl_price"] and current_price >= pos["sl_price"]: is_triggered = True

                # 觸及則自動平倉
                if is_triggered:
                    target_close_side = "SELL" if pos_side == "LONG" else "BUY"
                    try:
                        if pos_exchange == "MEXC":
                            place_order_mexc(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag)
                        else:
                            place_order_gate(pos_symbol, target_close_side, "MARKET", pos["quantity"], is_futures=is_futures_flag)
                        
                        # 移除持倉
                        GLOBAL_POSITIONS_LIST = [item for item in GLOBAL_POSITIONS_LIST if item["id"] != pos["id"]]
                        print(f"🔥 [後台自動出場成功] {pos_exchange} {pos_symbol}")
                    except Exception as e:
                        print(f"⚠️ [後台平倉失敗] {e}")

# 啟動後台守護進程
if "monitor_started" not in st.session_state:
    st.session_state["monitor_started"] = True
    t = threading.Thread(target=bg_monitor_loop, daemon=True)
    t.start()

# 覆寫開倉追蹤函數
def open_position(symbol: str, quantity: float, entry_price: float, tp_pct: float, sl_pct: float, pos_side: str = "LONG"):
    global GLOBAL_POSITIONS_LIST
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
    with POSITIONS_LOCK:
        GLOBAL_POSITIONS_LIST.append(position)
    return position

# ------------------------------------------------------------------
# Tab 4 前端渲染面版
# ------------------------------------------------------------------
with tab_tpsl:
    st.subheader("📊 24H 智能看盤與跨交易所監控面板")
    st.info("💡 系統正透過 Python 後台守護線程 24 小時全自動監控持倉，即使關閉網頁也持續運行！")
    
    # 讀取原生全域變數，確保畫面與後台同步
    current_tracked = GLOBAL_POSITIONS_LIST

    if not current_tracked:
        st.info("目前沒有任何追蹤中的持倉（現貨 / 合約）")
    else:
        if st.button("🔄 刷新最新市價損益"):
            st.rerun()

        for pos in current_tracked:
            # [這裡保持上一版渲染卡片的 c1, c2, c3, c4 代碼即可...]
            # (手動平倉按鈕內，也請改為操作 GLOBAL_POSITIONS_LIST 進行刪除)
            pass