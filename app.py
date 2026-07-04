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
st.title("🎛️ 動態幣種感知 ＆ 實時多幣種動態自動追蹤終端")

# ------------------------------------------------------------------
# ⚙️ 側邊欄與動態幣種清單定義
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 CryptoQuant 智慧跟單設定")
cq_api_key = st.sidebar.text_input("CryptoQuant Token", type="password", value="demo_mode", key="cq_token")
auto_trade_enabled = st.sidebar.toggle("🤖 啟用「多幣種自動下單」", value=False)
whale_threshold = st.sidebar.number_input("大戶觸發值 (Whale Ratio > 此值即下單)", value=0.55, step=0.01)

st.sidebar.header("📈 獨立移動追蹤設定 (Trailing Stop)")
trailing_enabled = st.sidebar.toggle("🔥 啟用多幣種動態追蹤", value=True)
activation_pct = st.sidebar.number_input("各幣種最高點回檔 % 平倉", value=2.0, step=0.1)

# 💡 【核心升級】：動態定義系統支援的幣種清單
# 未來只要在這裡增加新幣種，主面板跟設定會自動全部「實時聯動」顯示
SUPPORTED_COINS = ["GWEI_USDT", "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT"]

# 初始化狀態記憶庫
if "last_triggered_time" not in st.session_state:
    st.session_state.last_triggered_time = ""
if "auto_trade_logs" not in st.session_state:
    st.session_state.auto_trade_logs = []
if "active_trailing_positions" not in st.session_state:
    st.session_state.active_trailing_positions = {}
# 儲存使用者對各幣種實時配置的自訂下單張數
if "coin_vol_settings" not in st.session_state:
    st.session_state.coin_vol_settings = {coin: 10 if "GWEI" in coin else 1 for coin in SUPPORTED_COINS}

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
        "price": 0,  
        "vol": int(vol),
        "leverage": 10,
        "side": int(side),  # 1=開多, 4=平多
        "type": int(order_type), 
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
# 🕵️ CryptoQuant 多幣種實時數據與市場價格模擬
# ------------------------------------------------------------------
def fetch_multi_coin_market_data():
    import random
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_ratio = round(random.uniform(0.48, 0.65), 2)
    
    # 隨機挑選一個目前正在被巨鯨盯上的幸運幣種
    target_coin = random.choice(SUPPORTED_COINS)
    
    # 實時生成清單中所有幣種的最新市場價格
    prices = {
        "BTC_USDT": round(random.uniform(62000, 65000), 1),
        "ETH_USDT": round(random.uniform(3300, 3600), 1),
        "GWEI_USDT": round(random.uniform(0.1300, 0.1500), 4),
        "SOL_USDT": round(random.uniform(140, 160), 2),
        "XRP_USDT": round(random.uniform(0.55, 0.65), 4)
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
tab_whale, tab_config, tab_mexc = st.tabs([
    "🕵️ CryptoQuant 多幣種自動雷達", "⚙️ 實時各幣種下單張數配置", "🚀 MEXC 實時持倉"
])

# ==========================================
# 【核心引擎】背景自動下單與多幣種獨立追蹤控制
# ==========================================
market_tick = fetch_multi_coin_market_data()
current_ratio = market_tick["whale_ratio"]
triggered_coin = market_tick["target_symbol"]
tick_time = market_tick["date"]
all_prices = market_tick["prices"]

# 1. 🔍 多幣種自動下單監聽器
if auto_trade_enabled and current_ratio > whale_threshold and st.session_state.last_triggered_time != tick_time:
    if triggered_coin not in st.session_state.active_trailing_positions:
        coin_price = all_prices[triggered_coin]
        # 實時從動態狀態庫中抓取該幣種使用者設定的張數
        coin_vol = st.session_state.coin_vol_settings.get(triggered_coin, 1)
        
        # 發送真實 MEXC 市價多單 (side=1)
        order_res = place_mexc_futures_order(api_key, api_secret, symbol=triggered_coin, side=1, order_type=5, vol=coin_vol)
        
        # 建立獨立移動防線
        st.session_state.active_trailing_positions[triggered_coin] = {
            "entry_price": coin_price,
            "highest_price": coin_price,
            "stop_loss_price": coin_price * (1 - activation_pct / 100),
            "vol": coin_vol
        }
        
        log_time = datetime.now().strftime("%H:%M:%S")
        st.session_state.auto_trade_logs.insert(0, f"🚀 [{log_time}] 偵測巨鯨異動 ({current_ratio})！【自動開多 {triggered_coin}】實時設定張數: {coin_vol} | 進場價: {coin_price}")
        st.session_state.last_triggered_time = tick_time

# 2. 📈 多幣種獨立移動止損追蹤
if trailing_enabled and st.session_state.active_trailing_positions:
    for coin in list(st.session_state.active_trailing_positions.keys()):
        pos = st.session_state.active_trailing_positions[coin]
        live_price = all_prices[coin]
        
        if live_price > pos["highest_price"]:
            pos["highest_price"] = live_price
            pos["stop_loss_price"] = live_price * (1 - activation_pct / 100)
            st.session_state.auto_trade_logs.insert(0, f"📈 【止損上移】{coin} 創高至 {live_price}！新防線: {pos['stop_loss_price']:.4f}")
            
        elif live_price <= pos["stop_loss_price"]:
            place_mexc_futures_order(api_key, api_secret, symbol=coin, side=4, order_type=5, vol=pos["vol"])
            pnl = ((pos["stop_loss_price"] - pos["entry_price"]) / pos["entry_price"]) * 100
            st.session_state.auto_trade_logs.insert(0, f"🚨 【移動止損觸發】{coin} 跌破防線市價平倉。預估收益: {pnl:.2f}%")
            del st.session_state.active_trailing_positions[coin]

# ==========================================
# 【分頁一：🕵️ CryptoQuant 多幣種自動雷達主面板】
# ==========================================
with tab_whale:
    st.markdown("### 🕵️ 實時多幣種巨鯨雷達面板")
    
    # 頂部狀態列
    c1, c2, c3 = st.columns(3)
    c1.metric("當前巨鯨廣播頻率", f"{current_ratio}", f"焦點動態幣種: {triggered_coin}")
    c2.metric("自動下單功能", "🟢 背景監聽中" if auto_trade_enabled else "⚪ 已關閉")
    c3.metric("全自動移動跟蹤", "🔥 運作中" if trailing_enabled else "❌ 已關閉")
    
    st.divider()
    
    # 實時顯示各種幣種目前的市場價格與下單規格表
    st.markdown("#### 🪙 實時監控市場幣種行情 ＆ 下單規格對照")
    market_display = []
    for coin in SUPPORTED_COINS:
        is_tracking = "🎯 追蹤中" if coin in st.session_state.active_trailing_positions else "⏳ 觀望中"
        market_display.append({
            "幣種交易對": coin,
            "實時市場價格": f"{all_prices[coin]:.4f}",
            "當前配置下單張數 (隨設定同步)": f"{st.session_state.coin_vol_settings[coin]} 張",
            "雷達跟蹤狀態": is_tracking
        })
    st.dataframe(pd.DataFrame(market_display), use_container_width=True)
    
    st.divider()
    
    # 當前動態持倉表格
    st.markdown("#### 📊 當前獨立跟蹤中的「自動持倉矩陣」")
    if st.session_state.active_trailing_positions:
        display_data = []
        for coin, info in st.session_state.active_trailing_positions.items():
            display_data.append({
                "交易對": coin,
                "開倉原價": f"{info['entry_price']:.4f}",
                "當前市價": f"{all_prices[coin]:.4f}",
                "波段最高價": f"{info['highest_price']:.4f}",
                "動態止損防線": f"{info['stop_loss_price']:.4f}",
                "追蹤中張數": info['vol']
            })
        st.table(pd.DataFrame(display_data))
    else:
        st.info("⏳ 目前沒有任何自動單正在運行。")

    st.markdown("#### 📜 雷達自動化執行日誌")
    with st.container(height=250):
        for log in st.session_state.auto_trade_logs:
            if "開多" in log: st.success(log)
            elif "上移" in log: st.info(log)
            elif "觸發" in log: st.error(log)
            else: st.code(log)

# ==========================================
# 【全新分頁二：⚙️ 實時各種幣種下單張數配置】
# ==========================================
with tab_config:
    st.markdown("### ⚙️ 實時多幣種下單參數控制牆")
    st.caption("你可以在這裡直接調整各個幣種被巨鯨雷達觸發時的「下單張數」，修改後將即時應用於背景自動化程式中。")
    
    # 動態利用 Streamlit 網格，根據支援的幣種數量實時排版顯示輸入框
    cols = st.columns(len(SUPPORTED_COINS))
    for idx, coin in enumerate(SUPPORTED_COINS):
        with cols[idx]:
            st.markdown(f"**🪙 {coin.split('_')[0]}**")
            # 實時將使用者輸入的值同步存入 session_state 的字典中
            st.session_state.coin_vol_settings[coin] = st.number_input(
                f"每次下單張數", 
                min_value=1, 
                value=st.session_state.coin_vol_settings[coin], 
                key=f"input_vol_{coin}"
            )
    
    st.toast("💡 所有幣種的下單張數均已實時與自動化引擎同步！")

# ==========================================
# 【分頁三：MEXC 實時持倉】
# ==========================================
with tab_mexc:
    st.markdown("### 🚀 MEXC 實時帳戶持倉狀況")

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制 (8秒)
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()