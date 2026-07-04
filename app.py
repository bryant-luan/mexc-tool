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
            else:
            positions = result["data"]
            
            # 🔥 升級：全相容篩選機制（通殺 MEXC 各種幣別與欄位名）
            active_positions = []
            for p in positions:
                # 同時嘗試抓取所有 MEXC 可能出現的持倉數量欄位
                size = float(p.get("positionSize") or p.get("size") or p.get("vol") or p.get("openSize") or 0)
                if size > 0:
                    active_positions.append((p, size))
            
            if not active_positions:
                st.info("⏳ 目前您在 MEXC 帳戶中沒有任何開倉中的合約部位。")
                # 偵錯用：如果還是空，把交易所原始回傳的 JSON 結構吐出來看
                with st.expander("🛠️ 偵錯專用：查看交易所原始回傳資料"):
                    st.json(positions)
            else:
                st.markdown(f"### 📊 當前真實持倉清單 ({len(active_positions)} 筆)")
                
                for pos, size in active_positions:
                    symbol = pos.get("symbol")
                    entry_price = float(pos.get("holdAvgPrice") or pos.get("entryPrice") or pos.get("avgPrice") or 0)
                    
                    # 多空判斷：相容數字型態與字串型態
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
                        st.markdown(f"#### 🪙 {symbol} ｜ **{pos_type}**")
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("持倉數量", f"{size}")
                        c2.metric("開倉均價", f"{entry_price:.4f}" if entry_price else "未知")
                        c3.metric("自動止盈點", f"{calculated_tp:.4f}" if entry_price else "未知")
                        c4.metric("自動止損點", f"{calculated_sl:.4f}" if entry_price else "未知")