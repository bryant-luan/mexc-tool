# ------------------------------------------------------------------
# Tab 4：止盈止損監控（已修改：同時顯示 MEXC 與 Gate.io 持倉）
# ------------------------------------------------------------------
with tab_tpsl:
    st.subheader("跨交易所止盈止損監控")
    st.caption(
        "這裡列出的持倉只存在於這次瀏覽器工作階段（重新整理網頁、App 重啟都會清空）。\n"
        "Streamlit 沒有背景常駐機制，所以出場需要你手動按按鈕檢查；"
        "若要 24 小時全自動看盤出場，請改用 webhook_server.py 常駐監控（見下方 Webhook 分頁）。"
    )

    # 獲取所有持倉（不再篩選 current exchange，改為全部顯示）
    all_tracked_positions = st.session_state["positions"]

    if not all_tracked_positions:
        st.info("目前沒有任何追蹤中的持倉（MEXC / Gate.io）")
    else:
        for pos in all_tracked_positions:
            pos_exchange = pos["exchange"]
            pos_symbol = pos["symbol"]
            
            # 根據持倉本身的交易所，動態決定使用的 API 函式
            price_func = get_current_price_mexc if pos_exchange == "MEXC" else get_current_price_gate
            close_func = place_order_mexc if pos_exchange == "MEXC" else place_order_gate

            # 使用容器包裹，並特別標註交易所標籤
            with st.container(border=True):
                st.markdown(
                    f"### 🏦 **[{pos_exchange}]** {pos_symbol}\n"
                    f"數量：{pos['quantity']} ｜ 建立時間：{pos['opened_at']}"
                )
                
                # 獲取該持倉幣對在該交易所的最新價格
                try:
                    current_price = price_func(pos_symbol)
                except (requests.exceptions.RequestException, ValueError):
                    current_price = None

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("進場價", f"{pos['entry_price']:.6f}")
                c2.metric("止盈價", f"{pos['tp_price']:.6f}" if pos["tp_price"] else "未設定")
                c3.metric("止損價", f"{pos['sl_price']:.6f}" if pos["sl_price"] else "未設定")
                
                if current_price is not None:
                    pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                    c4.metric("目前價 / 損益", f"{current_price:.6f}（{pnl_pct:+.2f}%）")
                else:
                    c4.metric("目前價", "查詢失敗")

                # 判斷是否觸及止盈止損
                triggered = None
                if current_price is not None:
                    if pos["tp_price"] and current_price >= pos["tp_price"]:
                        triggered = "止盈"
                    elif pos["sl_price"] and current_price <= pos["sl_price"]:
                        triggered = "止損"

                btn1, btn2 = st.columns(2)
                
                # 定義平倉閉包邏輯（避免依賴全域的 exchange 變數變更）
                def exec_close(p=pos, r="手動"):
                    # 執行該持倉對應交易所的平倉單
                    res = close_func(p["symbol"], "SELL", "MARKET", p["quantity"])
                    # 從工作階段中移除
                    st.session_state["positions"] = [item for item in st.session_state["positions"] if item["id"] != p["id"]]
                    return res

                with btn1:
                    if triggered:
                        st.warning(f"⚠️ 已觸及 {triggered} 條件！")
                        if st.button(f"執行{triggered}出場", key=f"auto_close_{pos['id']}"):
                            try:
                                result = exec_close(pos, triggered)
                                st.success(f"[{pos_exchange}] {triggered}出場完成")
                                st.json(result)
                                st.rerun()
                            except (requests.exceptions.RequestException, ValueError) as e:
                                st.error(f"出場失敗：{e}")
                with btn2:
                    if st.button("🔴 手動平倉", key=f"manual_close_{pos['id']}"):
                        try:
                            result = exec_close(pos, "手動")
                            st.success(f"[{pos_exchange}] 已手動平倉")
                            st.json(result)
                            st.rerun()
                        except (requests.exceptions.RequestException, ValueError) as e:
                            st.error(f"平倉失敗：{e}")