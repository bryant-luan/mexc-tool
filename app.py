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
st.title("🎛️ 智能量化、實時持倉與快捷下單終端")

# ------------------------------------------------------------------
# ⚙️ 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 CryptoQuant API 設定")
cq_api_key = st.sidebar.text_input("CryptoQuant Token (選填)", type="password", value="demo_mode", key="cq_token")

st.sidebar.header("🎯 MEXC 止盈止損基準")
tp_pct = st.sidebar.number_input("自動止盈 %", value=5.0, step=0.5)
sl_pct = st.sidebar.number_input("自動止損 %", value=3.0, step=0.5)

# 初始化 CryptoQuant 模擬資料
if "whale_trades" not in st.session_state:
    st.session_state.whale_trades = [
        {"time": "2026-07-04 12:15:30", "whale_id": "Whale_0x71a", "symbol": "BTCUSDT", "side": "LONG (做多)", "entry": 63450.0, "size": "150,000 USDT"},
        {"time": "2026-07-04 13:02:11", "whale_id": "Smart_Top1", "symbol": "GWEIUSDT", "side": "LONG (做多)", "entry": 0.1355, "size": "45,000 USDT"}
    ]

# ------------------------------------------------------------------
# 🔒 MEXC 官方簽章加密演算法
# ------------------------------------------------------------------
def mexc_headers_and_sign(path, a_key, a_secret, method="GET", body_str=""):
    """符合 MEXC 官方私有端點（含 POST 下單）的標準加密簽章"""
    timestamp = str(int(time.time() * 1000))
    # 合約 API 簽章格式：ApiKey + Timestamp + BodyString (如果是 POST)
    sign_str = f"{a_key}{timestamp}{body_str}"
    
    signature = hmac.new(
        a_secret.encode('utf-8'), 
        sign_str.encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()
    
    return {
        "ApiKey": a_key,
        "Request-Time": timestamp,
        "Signature": signature,
        "Content-Type": "application/json"
    }

# 查詢持倉邏輯
def fetch_mexc_positions(a_key, a_secret):
    if not a_key or not a_secret:
        return {"success": False, "msg": "未輸入 API 金鑰"}
    try:
        path = "/api/v1/private/position/open_positions"
        headers = mexc_headers_and_sign(path, a_key, a_secret)
        resp = requests.get(f"{MEXC_FUT_URL}{path}", headers=headers, timeout=5)
        res_json = resp.json()
        if res_json.get("success"):
            return {"success": True, "data": res_json.get("data", [])}
        return {"success": False, "msg": f"交易所拒絕: {res_json.get('message')}"}
    except Exception as e:
        return {"success": False, "msg": f"網路連線失敗: {str(e)}"}

# ------------------------------------------------------------------
# ⚡ MEXC 官方合約快捷下單執行函數
# ------------------------------------------------------------------
def place_mexc_futures_order(a_key, a_secret, symbol, side, order_type, vol, price=0):
    """
    發送下單請求到 MEXC 官方私有下單端點
    side: 1=開多(Open Long), 2=平空, 3=開空(Open Short), 4=平多
    type: 1=限價單(Limit), 5=市價單(Market)
    """
    import json
    path = "/api/v1/private/order/submit"
    
    # 建立與 MEXC 參數精確對接的字典 payload
    payload = {
        "symbol": symbol,
        "price": float(price) if order_type == 1 else 0,
        "vol": int(vol),
        "leverage": 10,       # 預設 10 倍槓桿
        "side": int(side),
        "type": int(order_type),
        "openType": 1,        # 1 代表逐倉(Isolated)
    }
    
    body_str = json.dumps(payload, separators=(',', ':'))
    headers = mexc_headers_and_sign(path, a_key, a_secret, method="POST", body_str=body_str)
    
    try:
        url = f"{MEXC_FUT_URL}{path}"
        resp = requests.post(url, headers=headers, data=body_str, timeout=5)
        return resp.json()
    except Exception as e:
        return {"success": False, "message": f"連線異常: {str(e)}"}

# ------------------------------------------------------------------
# 🗂️ 四個分頁定義（新增下單面板）
# ------------------------------------------------------------------
tab_mexc, tab_order, tab_freqtrade, tab_whale = st.tabs([
    "🚀 MEXC 實時持倉", "⚡ MEXC 電腦版快捷下單", "🤖 Freqtrade 策略控制台", "🕵️ CryptoQuant 巨鯨雷達"
])

# ==========================================
# 【分頁一：MEXC 實時持倉】
# ==========================================
with tab_mexc:
    # ...（保持原有持倉卡片邏輯不變）...
    if not api_key or not api_secret:
        st.warning("👋 請在左側輸入您的 MEXC API 金鑰以載入真實合約持倉。")
    else:
        st.success("🟢 API 金鑰就緒，系統已切換至安全動態追蹤模式。")
        placeholder = st.empty()
        result = fetch_mexc_positions(api_key, api_secret)
        with placeholder.container():
            if not result["success"]: st.error(result["msg"])
            else:
                active_positions = [(p, float(p.get("holdVol", 0))) for p in result["data"] if float(p.get("holdVol", 0)) > 0]
                if not active_positions: st.info("⏳ 目前您在 MEXC 帳戶中沒有任何開倉中的合約部位。")
                else:
                    for pos, size in active_positions:
                        with st.container(border=True):
                            st.markdown(f"#### 🪙 {pos.get('symbol')} ｜ 持倉: {int(size)} 張 ｜ 盈虧: `{pos.get('unRealizedPnl')} USDT`")

# ==========================================
# 【全新分頁二：⚡ MEXC 電腦版快捷下單】
# ==========================================
with tab_order:
    st.markdown("### ⚡ MEXC 電腦網頁端快速下單控制台")
    st.caption("直接從此面板發送合約委託訂單至 MEXC 交易所。請確保您的 API Key 具有「合約交易」權限。")
    
    if not api_key or not api_secret:
        st.error("🔒 請先在左側邊欄輸入 API 金鑰，才能解鎖電腦版下單功能。")
    else:
        # 下單輸入表單網格
        with st.container(border=True):
            o_col1, o_col2, o_col3 = st.columns(3)
            
            # 1. 選擇幣種與交易對
            trade_symbol = o_col1.selectbox("選擇交易標的", ["GWEI_USDT", "BTC_USDT", "ETH_USDT", "SOL_USDT"])
            
            # 2. 選擇訂單類型（市價/限價）
            order_style = o_col2.radio("委託類型", ["🚀 市價單 (Market)", "🎯 限價單 (Limit)"], horizontal=True)
            order_type_code = 5 if "市價" in order_style else 1
            
            # 3. 輸入下單張數
            trade_vol = o_col3.number_input("下單張數 (Vol / 張)", value=1, min_value=1, step=1)
            
            # 如果是限價單，動態跳出價格輸入框
            trade_price = 0.0
            if order_type_code == 1:
                trade_price = st.number_input("委託限價價格 (USDT)", value=0.1350, format="%.4f")
            
            st.divider()
            
            # 買入與賣出按鈕
            btn_col1, btn_col2 = st.columns(2)
            
            # 🔥 按鈕 A：開多（買入）
            if btn_col1.button("🟢 一鍵【開啟多單 (BUY)】", use_container_width=True):
                with st.spinner("正在向 MEXC 送出多單..."):
                    res = place_mexc_futures_order(api_key, api_secret, trade_symbol, side=1, order_type=order_type_code, vol=trade_vol, price=trade_price)
                    if res.get("success"):
                        st.success(f"🎉 下單成功！訂單 ID: {res.get('data')}")
                    else:
                        st.error(f"❌ 下單失敗！交易所回傳：{res.get('message', '未知錯誤')}")
            
            # 🔥 按鈕 B：開空（賣出）
            if btn_col2.button("🔴 一鍵【開啟空單 (SELL)】", use_container_width=True):
                with st.spinner("正在向 MEXC 送出空單..."):
                    res = place_mexc_futures_order(api_key, api_secret, trade_symbol, side=3, order_type=order_type_code, vol=trade_vol, price=trade_price)
                    if res.get("success"):
                        st.success(f"🎉 下單成功！訂單 ID: {res.get('data')}")
                    else:
                        st.error(f"❌ 下單失敗！交易所回傳：{res.get('message', '未知錯誤')}")

        # 快捷快捷平倉區塊
        st.markdown("#### ⚡ 快捷一鍵全平倉")
        if st.button("⚠️ 緊急撤銷所有掛單與平倉", type="primary"):
            st.warning("正在執行緊急指令...")
            # 這裡可以擴充呼叫 cancel_all 端點

# ==========================================
# 【分頁三與四：Freqtrade 與 CryptoQuant】
# ==========================================
with tab_freqtrade:
    st.markdown("### 🤖 Freqtrade 量化機器人遠端監控")
    # ...（保持上個版本不變）...
with tab_whale:
    st.markdown("### 🕵️ CryptoQuant 鏈上聰明錢監控牆")
    # ...（保持上個版本不變）...

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制 (8秒)
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()