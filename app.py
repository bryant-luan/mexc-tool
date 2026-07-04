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
st.title("🎛️ 動態移動追蹤 ＆ 批次智慧平倉量化終端")

# ------------------------------------------------------------------
# ⚙️ 側邊欄設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password", key="mexc_key")
api_secret = st.sidebar.text_input("Secret Key", type="password", key="mexc_secret")

st.sidebar.header("🎯 CryptoQuant 智慧跟單設定")
cq_api_key = st.sidebar.text_input("CryptoQuant Token", type="password", value="demo_mode", key="cq_token")
auto_trade_enabled = st.sidebar.toggle("🤖 啟用「多幣種自動下單」", value=False)
whale_threshold = st.sidebar.number_input("大戶觸發值 (Whale Ratio > 此值即下單)", value=0.55, step=0.01)

st.sidebar.header("📈 實時持倉移動追蹤設定 (Trailing Stop)")
trailing_enabled = st.sidebar.toggle("🔥 啟用真實持倉動態移動追蹤", value=True)
activation_pct = st.sidebar.number_input("最高點回檔 % 平倉 (鎖定利潤)", value=2.0, step=0.1)

# 動態定義系統支援的幣種清單
SUPPORTED_COINS = ["GWEI_USDT", "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT"]

# 初始化狀態記憶庫
if "last_triggered_time" not in st.session_state:
    st.session_state.last_triggered_time = ""
if "auto_trade_logs" not in st.session_state:
    st.session_state.auto_trade_logs = []
if "coin_vol_settings" not in st.session_state:
    st.session_state.coin_vol_settings = {coin: 10 if "GWEI" in coin else 1 for coin in SUPPORTED_COINS}
if "real_portfolio_trailing" not in st.session_state:
    st.session_state.real_portfolio_trailing = {}

# ------------------------------------------------------------------
# 🔒 MEXC 安全加密簽章與 API 請求
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
        "side": int(side),  
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
        return {"success": False, "msg": res_json.get("message")}
    except Exception as e:
        return {"success": False, "msg": str(e)}

# ------------------------------------------------------------------
# 🕵️ CryptoQuant 多幣種市場模擬
# ------------------------------------------------------------------
def fetch_multi_coin_market_data():
    import random
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_ratio = round(random.uniform(0.48, 0.65), 2)
    target_coin = random.choice(SUPPORTED_COINS)
    prices = {
        "BTC_USDT": round(random.uniform(62000, 65000), 1),
        "ETH_USDT": round(random.uniform(3300, 3600), 1),
        "GWEI_USDT": round(random.uniform(0.1300, 0.1500), 4),
        "SOL_USDT": round(random.uniform(140, 160), 2),
        "XRP_USDT": round(random.uniform(0.55, 0.65), 4)
    }
    return {"date": now_str, "whale_ratio": mock_ratio, "target_symbol": target_coin, "prices": prices}

# ------------------------------------------------------------------
# 🗂️ 分頁與核心邏輯
# ------------------------------------------------------------------
tab_whale, tab_config, tab_mexc = st.tabs([
    "🕵️ CryptoQuant 多幣種自動雷達", "⚙️ 實時各幣種下單張數配置", "🚀 MEXC 實時移動追蹤持倉"
])

market_tick = fetch_multi_coin_market_data()
all_prices = market_tick["prices"]

with tab_whale: st.markdown("### 🕵️ 實時多幣種巨鯨雷達面板")
with tab_config: st.markdown("### ⚙️ 實時多幣種下單參數控制牆")

# ==========================================
# 🚀 分頁三：MEXC 實時移動追蹤持倉（新增批次平倉功能）
# ==========================================
with tab_mexc:
    st.markdown("### 🚀 MEXC 實時真實持倉 ＆ 移動追蹤防線")
    st.caption("此面板已整合「動態移動跟蹤」與「一鍵戰術批次盈利平倉」功能。")
    
    if not api_key or not api_secret:
        st.warning("👋 請先在左側邊欄輸入您的 MEXC API 金鑰，以啟動真實持倉動態追蹤機制。")
    else:
        # 1. 獲取交易所真實持倉
        pos_result = fetch_mexc_positions(api_key, api_secret)
        
        if not pos_result["success"]:
            st.error(f"❌ 無法讀取持倉：{pos_result['msg']}")
        else:
            raw_positions = pos_result.get("data", [])
            active_list = []
            current_active_symbols = set()
            
            for p in raw_positions:
                vol = float(p.get("holdVol") or p.get("positionSize") or 0)
                if vol > 0:
                    raw_sym = p.get("symbol", "")
                    formatted_sym = raw_sym if "_" in raw_sym else f"{raw_sym.replace('USDT', '')}_USDT"
                    active_list.append((p, vol, formatted_sym))
                    current_active_symbols.add(formatted_sym)
            
            # 清理快取
            for cached_coin in list(st.session_state.real_portfolio_trailing.keys()):
                if cached_coin not in current_active_symbols:
                    del st.session_state.real_portfolio_trailing[cached_coin]

            if not active_list:
                st.info("⏳ 讀取成功！目前您在 MEXC 帳戶中沒有任何正在開倉的合約部位。")
            else:
                # ----------------------------------------------------------
                # 🔥 【🔥全新戰術功能】：一鍵批次盈利平倉控制面板
                # ----------------------------------------------------------
                st.markdown("#### ⚡ 戰術快捷控制台")
                
                # 計算目前有幾筆單是賺錢的
                profit_positions_count = sum(1 for p, _, _ in active_list if float(p.get("unRealizedPnl") or 0) > 0)
                
                # 炫酷的一鍵平倉按鈕配置
                btn_label = f"💰 一鍵鎖定利潤：批次平倉所有盈利單 (當前有 {profit_positions_count} 筆正收益)"
                
                # 只要有賺錢的單，按鈕就亮起，否則停用避免誤觸
                if profit_positions_count > 0:
                    if st.button(btn_label, type="primary", use_container_width=True):
                        with st.spinner("🚀 正在極速清空所有浮盈倉位..."):
                            success_count = 0
                            for p, vol, symbol in active_list:
                                pnl = float(p.get("unRealizedPnl") or 0)
                                # 🔍 只對浮盈大於 0 的部位下手
                                if pnl > 0:
                                    # 發送平多單指令 (side=4)
                                    res = place_mexc_futures_order(api_key, api_secret, symbol=symbol, side=4, order_type=5, vol=vol)
                                    if res.get("success") or res.get("code") == 0:
                                        success_count += 1
                                        st.success(f"✅ 成功平倉 {symbol} ｜ 撈回浮盈: ${pnl:+.2f}")
                                    else:
                                        st.error(f"❌ {symbol} 平倉失敗: {res.get('message')}")
                            
                            st.toast(f"🎉 批次任務結束！成功收割 {success_count} 筆盈利部位！")
                            time.sleep(1.5)
                            st.rerun()  # 馬上重整刷新持倉畫面
                else:
                    st.button("⚪ 當前無任何盈利部位（按鈕已鎖定）", disabled=True, use_container_width=True)
                
                st.divider()

                # 2. 渲染真實持倉追蹤矩陣卡片
                st.markdown(f"#### 📊 真實持倉追蹤矩陣 ({len(active_list)} 筆)")
                
                for pos, vol, symbol in active_list:
                    entry_price = float(pos.get("holdAvgPrice") or 0)
                    liq_price = float(pos.get("liquidatePrice") or 0)
                    unrealized_pnl = float(pos.get("unRealizedPnl") or 0)
                    leverage = pos.get("leverage", 10)
                    
                    live_market_price = all_prices.get(symbol, entry_price)
                    
                    if symbol not in st.session_state.real_portfolio_trailing:
                        st.session_state.real_portfolio_trailing[symbol] = {
                            "highest_price": max(entry_price, live_market_price),
                            "stop_loss_line": entry_price * (1 - activation_pct / 100)
                        }
                    
                    track_status = st.session_state.real_portfolio_trailing[symbol]
                    
                    if live_market_price > track_status["highest_price"]:
                        track_status["highest_price"] = live_market_price
                        track_status["stop_loss_line"] = live_market_price * (1 - activation_pct / 100)
                    
                    triggered_sl = False
                    if live_market_price <= track_status["stop_loss_line"]:
                        triggered_sl = True
                        place_mexc_futures_order(api_key, api_secret, symbol=symbol, side=4, order_type=5, vol=vol)
                        st.toast(f"🚨 {symbol} 價格破動態防線！自動平倉！")
                    
                    # 卡片 UI 渲染
                    with st.container(border=True):
                        col_a, col_b, col_c, col_d = st.columns(4)
                        
                        col_a.markdown(f"### 🪙 {symbol}")
                        col_a.markdown("標籤: **🟢 LONG (做多)**")
                        col_a.markdown(f"槓桿: `{leverage}X` ｜ 數量: **{int(vol)} 張**")
                        
                        col_b.metric("開倉均價", f"${entry_price:.4f}")
                        col_b.metric("最新市場價", f"${live_market_price:.4f}")
                        
                        col_c.metric("📈 波段最高價", f"${track_status['highest_price']:.4f}")
                        sl_display_label = "🔥 動態移動止損線" if not triggered_sl else "🚨 防線跌破！平倉中"
                        col_c.metric(sl_display_label, f"${track_status['stop_loss_line']:.4f}")
                        
                        pnl_color = "green" if unrealized_pnl >= 0 else "red"
                        col_d.markdown("##### 未實現盈虧")
                        html_pnl = f"<h2 style='color:{pnl_color}; margin:0;'>${unrealized_pnl:+.2f}</h2>"
                        col_d.markdown(html_pnl, unsafe_allow_html=True)
                        col_d.caption(f"強平價格: ${liq_price:.4f}")

# ------------------------------------------------------------------
# 💡 全域自動定時重整機制 (8秒)
# ------------------------------------------------------------------
time.sleep(8)
st.rerun()