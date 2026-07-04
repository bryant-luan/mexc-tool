import time
import hmac
import hashlib
import requests
import streamlit as st

# 交易所 Base URL
MEXC_FUT_URL = "https://contract.mexc.com"

# 🤖 Freqtrade 預設連線設定 (你可以根據實際運行的 VPS 修改這三個數值)
FREQTRADE_API_URL = "http://127.0.0.1:8080/api/v1"
FREQ_USER = "admin"
FREQ_PASS = "your_password"

st.set_page_config(page_title="MEXC & Freqtrade 綜合交易工具", layout="wide")
st.title("🎛️ 智能量化與持倉監控面板")

# ------------------------------------------------------------------
# ⚙️ 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 MEXC 止盈止損基準")
tp_pct = st.sidebar.number_input("自動止盈 %", value=5.0, step=0.5)
sl_pct = st.sidebar.number_input("自動止損 %", value=3.0, step=0.5)

# ------------------------------------------------------------------
# 🔒 MEXC 官方標準安全簽章與持倉查詢
# ------------------------------------------------------------------
def fetch_mexc_positions(a_key, a_secret):
    if not a_key or not a_secret:
        return {"success": False, "msg": "未輸入 API 金鑰"}
    
    try:
        timestamp = str(int(time.time() * 1000))
        path = "/api/v1/private/position/open_positions"
        
        sign_str = f"{a_key}{timestamp}"
        signature = hmac.new(
            a_secret.encode('utf-8'), 
            sign_str.encode('utf-8'), 
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "ApiKey": a_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Content-Type": "application/json"
        }
        
        resp = requests.get(f"{MEXC_FUT_URL}{path}", headers=headers, timeout=5)
        res_json = resp.json()
        
        if res_json.get("success"):
            return {"success": True, "data": res_json.get("data", [])}
        else:
            return {"success": False, "msg": f"交易所拒絕: {res_json.get('message')} (代碼: {res_json.get('code')})"}
            
    except Exception as e:
        return {"success": False, "msg": f"網路連線失敗: {str(e)}"}

# ------------------------------------------------------------------
# 🗂️ 這裡就是核心：定義網頁的兩個分頁
# ------------------------------------------------------------------
tab_mexc, tab_freqtrade = st.tabs(["🚀 MEXC 實時持倉", "🤖 Freqtrade 策略控制台"])

# ==========================================
# 【分頁一：MEXC 實時持倉】
# ==========================================
with tab_mexc:
    if not api_key or not api_secret:
        st.warning("👋 請在左側輸入您的 MEXC API 金鑰以載入真實合約持倉。")
    else:
        st.success("🟢 API 金鑰就緒，系統已切換至安全動態追蹤模式。")
        
        placeholder = st.empty()
        
        if st.button("🔄 立即重新整理數據"):
            st.rerun()

        result = fetch_mexc_positions(api_key, api_secret)
        
        with placeholder.container():
            if not result["success"]:
                st.error(result["msg"])
            else:
                positions = result["data"]
                
                active_positions = []
                for p in positions:
                    size = float(p.get("holdVol") or p.get("positionSize") or p.get("size") or p.get("vol") or 0)
                    if size > 0:
                        active_positions.append((p, size))
                
                if not active_positions:
                    st.info("⏳ 目前您在 MEXC 帳戶中沒有任何開倉中的合約部位。")
                    with st.expander("🛠️ 偵錯專用：查看交易所原始回傳資料"):
                        st.json(positions)
                else:
                    st.markdown(f"### 📊 當前真實持倉清單 ({len(active_positions)} 筆)")
                    
                    for pos, size in active_positions:
                        symbol = pos.get("symbol", "").replace("_", "")
                        entry_price = float(pos.get("holdAvgPrice") or pos.get("entryPrice") or 0)
                        liq_price = float(pos.get("liquidatePrice") or 0)
                        unrealized_pnl = float(pos.get("unRealizedPnl") or 0)
                        leverage = pos.get("leverage", 10)
                        
                        pos_type_raw = pos.get("positionType") or pos.get("side")
                        if pos_type_raw in [1, "1", "LONG", "Long", "long"]:
                            pos_type = "LONG (做多)"
                            calculated_tp = entry_price * (1 + tp_pct / 100)
                            calculated_sl = entry_price * (1 - sl_pct / 100)
                        else:
                            pos_type = "SHORT (做空)"
                            calculated_tp = entry_price * (1 - tp_pct / 100)
                            calculated_sl = entry_price * (1 + sl_pct / 100)
                        
                        with st.container(border=True):
                            st.markdown(f"#### 🪙 {symbol} ｜ **{pos_type}** ｜ {leverage}X 槓桿")
                            
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("持倉張數 (Vol)", f"{int(size)}")
                            c2.metric("開倉均價", f"{entry_price:.4f}")
                            c3.metric("目標止盈點", f"{calculated_tp:.4f}")
                            c4.metric("強平價格", f"{liq_price:.4f}")
                            
                            if unrealized_pnl >= 0:
                                st.markdown(f"**💡 當前未實現盈虧：** `+{unrealized_pnl} USDT`")
                            else:
                                st.markdown(f"**💡 當前未實現盈虧：** `{unrealized_pnl} USDT`")

# ==========================================
# 【分頁二：Freqtrade 遠端控制台 (新增的分頁)】
# ==========================================
with tab_freqtrade:
    st.markdown("### 🤖 Freqtrade 量化機器人遠端監控")
    st.caption("本分頁將透過 REST API 連線至您背景運行的 Freqtrade 交易系統。")
    
    # 提供一個可以手動輸入 Freqtrade API 位置的擴充輸入框
    freq_url = st.text_input("🔗 Freqtrade API 位置", value=FREQTRADE_API_URL)
    
    try:
        # 1. 嘗試跟當地的 Freqtrade 拿狀態
        status_resp = requests.get(f"{freq_url}/status", auth=(FREQ_USER, FREQ_PASS), timeout=2)
        profit_resp = requests.get(f"{freq_url}/profit", auth=(FREQ_USER, FREQ_PASS), timeout=2)
        
        if status_resp.status_code == 200:
            bot_status = status_resp.json()
            bot_profit = profit_resp.json()
            
            st.success(f"🟢 Freqtrade 機器人正在運行中！當前狀態：{bot_status.get('state', 'RUNNING')}")
            
            # 顯示 Freqtrade 的機器人數據
            col1, col2, col3 = st.columns(3)
            col1.metric("今日勝率", f"{bot_profit.get('winning_trades', 0)} / {bot_profit.get('total_trades', 0)}")
            col2.metric("今日收益百分比", f"{bot_profit.get('profit_day_pct', 0):+.2f}%")
            col3.metric("當前浮動利潤 (USDT)", f"{bot_profit.get('fiat_value', 0)} USDT")
            
            # 控制開關
            st.markdown("#### ⚡ 機器人手動控制指令")
            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("🛑 暫停自動交易"):
                requests.post(f"{freq_url}/stop", auth=(FREQ_USER, FREQ_PASS))
                st.toast("已發送暫停指令")
            if btn_col2.button("▶️ 開啟自動交易"):
                requests.post(f"{freq_url}/start", auth=(FREQ_USER, FREQ_PASS))
                st.toast("已發送開啟指令")
        else:
            st.warning("⚠️ 成功連上該網址，但 Freqtrade 拒絕存取，請檢查 config.json 中的 API 密碼是否正確。")
            
    except Exception:
        # 如果背景還沒跑 Freqtrade，提示用戶如何開啟
        st.info("💡 目前尚未偵測到正在運行的 Freqtrade 機器人。")
        with st.container(border=True):
            st.markdown("""
            **如何啟用 Freqtrade API 連線？**
            1. 請確保您已在伺服器上安裝並運行了 Freqtrade。
            2. 請檢查 Freqtrade 的 `config.json` 設定檔中，`api_server` 區塊是否已啟用：
            ```json
            "api_server": {
                "enabled": true,
                "listen_ip_address": "127.0.0.1",
                "listen_port": 8080,
                "username": "admin",
                "password": "your_password"
            }
            ```
            3. 當您的機器人在後台跑起來後，這個分頁就會自動亮起綠燈並抓取機器人的收益曲線！
            """)

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()