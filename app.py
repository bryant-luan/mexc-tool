import time
import hmac
import hashlib
import requests
import streamlit as st
import pandas as pd
from datetime import datetime

# 交易所 Base URL
MEXC_FUT_URL = "https://contract.mexc.com"

st.set_page_config(page_title="MEXC 智慧量化終端", layout="wide")
st.title("🎛️ 多幣種巨鯨雷達 ＆ 獨立動態自動追蹤終端")

# ------------------------------------------------------------------
# ⚙️ 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 CryptoQuant 智慧多幣種跟單")
cq_api_key = st.sidebar.text_input("CryptoQuant Token", type="password", value="demo_mode", key="cq_token")
auto_trade_enabled = st.sidebar.toggle("🤖 啟用「多幣種自動下單」", value=False)
whale_threshold = st.sidebar.number_input("大戶觸發值 (Whale Ratio > 此值即下單)", value=0.55, step=0.01)

st.sidebar.header("📈 獨立移動追蹤設定 (Trailing Stop)")
trailing_enabled = st.sidebar.toggle("🔥 啟用多幣種動態追蹤", value=True)
activation_pct = st.sidebar.number_input("各幣種最高點回檔 % 平倉", value=2.0, step=0.1)

# 下單自訂參數配置表（讓你可以針對不同幣種設定不同的下單張數）
st.sidebar.subheader("💰 各幣種下單張數配置")
vol_config = {
    "GWEI_USDT": st.sidebar.number_input("GWEI 每次下單張數", value=100, min_value=1),
    "BTC_USDT": st.sidebar.number_input("BTC 每次下單張數", value=1, min_value=1),
    "ETH_USDT": st.sidebar.number_input("ETH 每次下單張數", value=2, min_value=1)
}

# 初始化狀態記憶庫
if "last_triggered_time" not in st.session_state:
    st.session_state.last_triggered_time = ""
if "auto_trade_logs" not in st.session_state:
    st.session_state.auto_trade_logs = []
# ⚡ 核心：多幣種獨立追蹤字典 { "幣種名稱": {持倉資料} }
if "active_trailing_positions" not in st.session_state:
    st.session_state.active_trailing_positions = {}

# ------------------------------------------------------------------
# 🔒 MEXC 安全加密簽章與下單執行
# ------------------------------------------------------------------
def mexc_headers_and_sign(path, a_key, a_secret, body_str=""):
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{a_key}{timestamp}{body_str}"
    signature = hmac.new(a_secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest()
    return {"ApiKey": a_key, "Request-Time": timestamp, "Signature": signature, "Content-Type": "application/json"}

def place_mexc_futures_order(a_key, a_secret, symbol, side, order_type, vol):
    import json
    path = "/api/v1/private/order/submit"
    payload = {
        "symbol": symbol,
        "price": 0,  # 5=市價單，價格帶0
        "vol": int(vol),
        "leverage": 10,
        "side": int(side),  # 1=開多, 4=平多
        "type": int(order_type), # 5=市價
        "openType": 1,
    }
    body_str = json.dumps(payload, separators=(',', ':'))
    headers = mexc_headers_and_sign(path, a_key, a_secret, body_str=body_str)
    try:
        resp = requests.post(f"{MEXC_FUT_URL}{path}", headers=headers, data=body_str, timeout=5)
        return resp.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

# ------------------------------------------------------------------
# 🕵️ CryptoQuant 多幣種實時鏈上與價格模擬
# ------------------------------------------------------------------
def fetch_multi_coin_data():
    """模擬 CryptoQuant 同時廣播多個幣種的大戶異動與實時最新市價"""
    import random
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_ratio = round(random.uniform(0.48, 0.65), 2)
    
    # 隨機挑選一個目前正在被巨鯨炒作的幸運幣種
    target_coin = random.choice(["GWEI_USDT", "BTC_USDT", "ETH_USDT"])
    
    # 生成各幣種實時市價波動
    prices = {
        "BTC_USDT": round(random.uniform(62000, 65000), 1),
        "ETH_USDT": round(random.uniform(3300, 3600), 1),
        "GWEI_USDT": round(random.uniform(0.1300, 0.1500), 4)
    }
    
    return {
        "date": now_str,
        "whale_ratio": mock_ratio,
        "target_symbol": target_coin,
        "prices": prices
    }

# ------------------------------------------------------------------
# 🗂️ 分頁定義
# ------------------------------------------------------------------
tab_whale, tab_mexc = st.tabs(["🕵️ CryptoQuant 多幣種自動雷達", "🚀 MEXC 實時持倉"])

# ==========================================
# 【核心引擎】背景自動下單與多幣種獨立追蹤控制
# ==========================================
market_tick = fetch_multi_coin_data()
current_ratio = market_tick["whale_ratio"]
triggered_coin = market_tick["target_symbol"]
tick_time = market_tick["date"]
all_prices = market_tick["prices"]

# 1. 🔍 多幣種自動下單監聽器
if auto_trade_enabled and current_ratio > whale_threshold and st.session_state.last_triggered_time != tick_time:
    # 檢查該幣種是否已經有在追蹤的單，避免重複開倉
    if triggered_coin not in st.session_state.active_trailing_positions:
        coin_price = all_prices[triggered_coin]
        coin_vol = vol_config.get(triggered_coin, 1)
        
        # 發送真實 MEXC 市價多單 (side=1)
        order_res = place_mexc_futures_order(api_key, api_secret, symbol=triggered_coin, side=1, order_type=5, vol=coin_vol)
        
        # 在本地追蹤矩陣中為該幣種建立「獨立移動防線」
        st.session_state.active_trailing_positions[triggered_coin] = {
            "entry_price": coin_price,
            "highest_price": coin_price,
            "stop_loss_price": coin_price * (1 - activation_pct / 100),
            "vol": coin_vol
        }
        
        log_time = datetime.now().strftime("%H:%M:%S")
        st.session_state.auto_trade_logs.insert(0, f"🚀 [{log_time}] 偵測巨鯨異動 ({current_ratio})！【自動開多 {triggered_coin}】數量: {coin_vol} | 進場價: {coin_price} | 初始止損: {st.session_state.active_trailing_positions[triggered_coin]['stop_loss_price']:.4f}")
        st.session_state.last_triggered_time = tick_time

# 2. 📈 多幣種「各別獨立」移動止損追蹤器
if trailing_enabled and st.session_state.active_trailing_positions:
    # 使用 list(keys) 迭代，允許在循環中刪除已觸發平倉的幣種
    for coin in list(st.session_state.active_trailing_positions.keys()):
        pos = st.session_state.active_trailing_positions[coin]
        live_price = all_prices[coin]
        
        # 該幣種價格創下它自己的歷史新高 -> 獨立推高自己的止損點
        if live_price > pos["highest_price"]:
            pos["highest_price"] = live_price
            pos["stop_loss_price"] = live_price * (1 - activation_pct / 100)
            st.session_state.auto_trade_logs.insert(0, f"📈 【止損上移】{coin} 創高至 {live_price}！新防線已鎖定在: {pos['stop_loss_price']:.4f}")
            
        # 該幣種價格跌破它自己的動態生命線 -> 獨立執行平倉
        elif live_price <= pos["stop_loss_price"]:
            # 發送平倉單 (side=4 平多)
            place_mexc_futures_order(api_key, api_secret, symbol=coin, side=4, order_type=5, vol=pos["vol"])
            
            pnl = ((pos["stop_loss_price"] - pos["entry_price"]) / pos["entry_price"]) * 100
            st.session_state.auto_trade_logs.insert(0, f"🚨 【移動止損觸發】{coin} 跌破防線！市價平倉出場。預估利潤: {pnl:.2f}%")
            
            # 將該幣種移出追蹤矩陣，不影響其他正在奔跑的幣種
            del st.session_state.active_trailing_positions[coin]

# ==========================================
# 【介面渲染：🕵️ CryptoQuant 多幣種自動雷達】
# ==========================================
with tab_whale:
    st.markdown("### 🕵️ 鏈上多幣種自動下單 ＆ 獨立動態跟蹤面板")
    st.caption("系統會在背景動態掃描所有幣種的巨鯨信號。各幣種擁有獨立的最高價紀錄與移動止損線，互不干涉。")
    
    # 頂部即時狀況
    c1, c2, c3 = st.columns(3)
    c1.metric("當前巨鯨廣播頻率", f"{current_ratio}", f"焦點幣種: {triggered_coin}")
    c2.metric("自動下單功能", "🟢 背景自動監聽中" if auto_trade_enabled else "⚪ 已關閉自動化")
    c3.metric("全自動移動跟蹤", "🔥 運作中" if trailing_enabled else "❌ 已關閉")
    
    st.divider()
    
    # 3. 實時多幣種跟蹤矩陣卡片
    st.markdown("#### 📊 當前獨立跟蹤中的「自動持倉矩陣」")
    if st.session_state.active_trailing_positions:
        # 將多幣種資料格式化轉成表格顯示
        display_data = []
        for coin, info in st.session_state.active_trailing_positions.items():
            display_data.append({
                "交易對": coin,
                "開倉原價": f"{info['entry_price']:.4f}",
                "當前市價": f"{all_prices[coin]:.4f}",
                "波段最高價": f"{info['highest_price']:.4f}",
                "動態止損防線 (跌破平倉)": f"{info['stop_loss_price']:.4f}",
                "下單數量": info['vol']
            })
        st.table(pd.DataFrame(display_data))
    else:
        st.info("⏳ 目前沒有任何自動單正在運行。當鏈上大戶指標破表時，系統會自動在上方建倉並啟動獨立跟蹤。")

    # 4. 實時日誌
    st.markdown("#### 📜 雷達自動化執行日誌 (多幣種動態流)")
    with st.container(height=300):
        for log in st.session_state.auto_trade_logs:
            if "開多" in log: st.success(log)
            elif "上移" in log: st.info(log)
            elif "觸發" in log: st.error(log)
            else: st.code(log)

# ==========================================
# 【分頁二：MEXC 實時持倉】
# ==========================================
with tab_mexc:
    st.markdown("### 🚀 MEXC 實時帳戶持倉狀況")
    st.caption("此處顯示您 MEXC 帳戶中的真實合約倉位。")

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制 (8秒)
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()