import time
import hmac
import hashlib
import requests
import streamlit as st

# 交易所 Base URL
MEXC_FUT_URL = "https://contract.mexc.com"

st.set_page_config(page_title="MEXC 實時合約工具", layout="wide")
st.title("🚀 MEXC 實時持倉監控面板 (無衝突安全版)")

# ------------------------------------------------------------------
# ⚙️ 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 止盈止損基準")
tp_pct = st.sidebar.number_input("自動止盈 %", value=5.0, step=0.5)
sl_pct = st.sidebar.number_input("自動止損 %", value=3.0, step=0.5)

# ------------------------------------------------------------------
# 🔒 官方標準安全簽章與持倉查詢 (處理時鐘與參數同步)
# ------------------------------------------------------------------
def fetch_mexc_positions(a_key, a_secret):
    if not a_key or not a_secret:
        return {"success": False, "msg": "未輸入 API 金鑰"}
    
    try:
        # 1. 取得毫秒時間戳
        timestamp = str(int(time.time() * 1000))
        path = "/api/v1/private/position/open_positions"
        
        # 2. 🔥 修正後的 MEXC 官方合約 GET 標準：ApiKey 必須在前，Timestamp 在後
        sign_str = f"{a_key}{timestamp}"
        
        # 3. 使用 Hmac SHA256 加密
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
# 📈 主畫面邏輯：利用 Streamlit 原生循環，免去背景線程衝突
# ------------------------------------------------------------------
if not api_key or not api_secret:
    st.warning("👋 請在左側輸入您的 MEXC API 金鑰以載入真實合約持倉。")
else:
    st.success("🟢 API 金鑰就緒，系統已切換至安全動態追蹤模式。")
    
    # 建立一個動態刷新的區塊
    placeholder = st.empty()
    
    # 點擊按鈕手動觸發立即刷新
    if st.button("🔄 立即重新整理數據"):
        st.rerun()

    # 直接在主線程中安全撈取，100% 不會漏掉變數
    result = fetch_mexc_positions(api_key, api_secret)
    
    with placeholder.container():
        if not result["success"]:
            st.error(result["msg"])
        else:
            positions = result["data"]
            # 篩選真正有持倉的部位 (positionSize > 0)
            active_positions = [p for p in positions if float(p.get("positionSize", 0)) > 0]
            
            if not active_positions:
                st.info("⏳ 目前您在 MEXC 帳戶中沒有任何開倉中的合約部位。")
            else:
                st.markdown(f"### 📊 當前真實持倉清單 ({len(active_positions)} 筆)")
                
                for pos in active_positions:
                    symbol = pos.get("symbol")
                    size = float(pos.get("positionSize", 0))
                    entry_price = float(pos.get("holdAvgPrice", 0))
                    pos_type = "LONG (做多)" if pos.get("positionType") == 1 else "SHORT (做空)"
                    
                    # 計算預期的止盈止損價格
                    if pos.get("positionType") == 1:
                        calculated_tp = entry_price * (1 + tp_pct / 100)
                        calculated_sl = entry_price * (1 - sl_pct / 100)
                    else:
                        calculated_tp = entry_price * (1 - tp_pct / 100)
                        calculated_sl = entry_price * (1 + sl_pct / 100)
                    
                    with st.container(border=True):
                        st.markdown(f"#### 🪙 {symbol} ｜ **{pos_type}**")
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("持倉數量", f"{size}")
                        c2.metric("開倉均價", f"{entry_price:.4f}")
                        c3.metric("自動止盈點", f"{calculated_tp:.4f}")
                        c4.metric("自動止損點", f"{calculated_sl:.4f}")
                        
    # 💡 聰明的定時自動刷新：每 8 秒自動重整網頁更新市價與持倉，完全不耗費後台線程
    time.sleep(8)
    st.rerun()