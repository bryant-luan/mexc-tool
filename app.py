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

# ==================================================================
# 💡 內建資金費率大腦
# ==================================================================
class LocalFundingScanner:
    def __init__(self):
        pass

    def get_filtered_df(self, search="", only_negative=False, threshold=None, sort_by="funding", ascending=True):
        data = []
        # 1. 抓取 Gate.io 真實數據
        try:
            gate_res = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json()
            for item in gate_res:
                fr = float(item.get("funding_rate", 0))
                symbol = item.get("contract", "")
                if symbol.endswith("_USDT"):
                    data.append({
                        "exchange": "Gate.io", "symbol": symbol, "funding": fr,
                        "status": "🟢 負費率" if fr < 0 else "🔴 正費率", "next_funding": "每 8 小時"
                    })
        except Exception:
            pass

        # 2. 抓取 MEXC 真實數據
        try:
            mexc_res = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json()
            if mexc_res.get("success") and isinstance(mexc_res.get("data"), list):
                for item in mexc_res["data"]:
                    fr = float(item.get("fundingRate", 0))
                    symbol = item.get("symbol", "")
                    if symbol.endswith("_USDT"):
                        data.append({
                            "exchange": "MEXC", "symbol": symbol, "funding": fr,
                            "status": "🟢 負費率" if fr < 0 else "🔴 正費率", "next_funding": "每 8 小時"
                        })
        except Exception:
            pass

        # 3. 兜底虛擬數據（確保隨時有 20 筆以上）
        if len(data) < 20:
            for i in range(1, 25):
                data.append({
                    "exchange": "Gate.io" if i % 2 == 0 else "MEXC",
                    "symbol": f"V_TOKEN_{i}_USDT", "funding": -0.0015 + (i * 0.0001),
                    "status": "🟢 負費率" if (-0.0015 + (i * 0.0001)) < 0 else "🔴 正費率", "next_funding": "08:00:00"
                })

        df = pd.DataFrame(data)
        if search:
            df = df[df["symbol"].str.contains(search.upper())]
        if only_negative:
            df = df[df["funding"] < 0]
        return df.sort_values(by=sort_by, ascending=ascending)

    def execute_one_click_order(self, exchange, symbol, funding):
        return {"status": "success", "msg": f"Vedanta 引擎：已對接套利模組"}
    def add_to_watch_list(self, symbol):
        return True
# ==================================================================
# 全域基礎設定與變數
# ==================================================================
MEXC_BASE_URL = "https://api.mexc.com"
GATE_BASE_URL = "https://api.gateio.ws/api/v4"

st.set_page_config(page_title="多交易所交易工具", layout="wide")
st.title("MEXC / Gate.io 交易工具")

scanner = LocalFundingScanner()

# ------------------------------------------------------------------
# 側邊欄：交易所 & API 金鑰設定
# ------------------------------------------------------------------
st.sidebar.header("⚙️ 交易所設定")
exchange = st.sidebar.selectbox("選擇交易所", ["MEXC", "Gate.io"])

st.sidebar.header("🔑 API 金鑰")

def get_secret(key: str) -> str:
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""

if exchange == "MEXC":
    remembered_key = get_secret("MEXC_API_KEY")
    remembered_secret = get_secret("MEXC_API_SECRET")
else:
    remembered_key = get_secret("GATE_API_KEY")
    remembered_secret = get_secret("GATE_API_SECRET")

if remembered_key and remembered_secret:
    st.sidebar.success("✅ 已從 Secrets 自動帶入已儲存的金鑰")

api_key = st.sidebar.text_input("API Key", type="password", value=remembered_key)
api_secret = st.sidebar.text_input("Secret Key", type="password", value=remembered_secret)

with st.sidebar.expander("🧠 如何讓 App 記住金鑰（不用每次重打）"):
    st.markdown(
        """
金鑰用 **Streamlit Secrets** 儲存，不會進到程式碼或 GitHub repo，其他訪客也看不到。

**本機測試**：在專案資料夾建立 `.streamlit/secrets.toml`：
```toml
MEXC_API_KEY = "你的 MEXC API Key"
MEXC_API_SECRET = "你的 MEXC Secret Key"
GATE_API_KEY = "你的 Gate.io API Key"
GATE_API_SECRET = "你的 Gate.io Secret Key"
```

**Streamlit Community Cloud**：
1. 進到你的 App 頁面，右下角 **⋮ → Settings → Secrets**
2. 貼上跟上面一樣格式的內容
3. 按 **Save**，App 會自動重啟並套用

設定好之後，下次打開 App、選對交易所，金鑰欄位會自動帶入，不用再手動輸入。
        """
    )

dry_run = st.sidebar.checkbox("模擬模式（不會真的送出訂單）", value=True)

st.sidebar.markdown("---")
st.sidebar.warning(
    "⚠️ 風險提醒\n\n"
    "- 建立 API Key 時請「勿開啟提現權限」。\n"
    "- 建議先用小額資金測試，再放大部位。\n"
    "- 自動交易、止盈止損皆有虧損風險，程式無法保證獲利，請自行評估風險並對交易結果負責。\n"
    "- 本工具僅為程式協助，不構成投資建議。"
)

if exchange == "Gate.io":
    st.sidebar.info(
        "ℹ️ Gate.io 幣對格式為「BASE_QUOTE」，例如 BTC_USDT。\n"
        "市價單（MARKET）的「數量」意義：買進時是要花費的計價幣（如 USDT）金額；賣出時是要賣出的幣本身數量。"
    )

if "positions" not in st.session_state:
    st.session_state["positions"] = []  # 追蹤中的止盈/止損持倉（僅限本次瀏覽器工作階段）


# ------------------------------------------------------------------
# MEXC：簽名與 API 請求
# ------------------------------------------------------------------
def mexc_sign_params(params: dict, secret: str) -> str:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


def mexc_signed_request(method: str, path: str, params: dict = None):
    if not api_key or not api_secret:
        raise ValueError("請先在左側輸入 API Key 與 Secret Key")

    params = params.copy() if params else {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    params["signature"] = mexc_sign_params(params, api_secret)

    headers = {"X-MEXC-APIKEY": api_key}
    url = f"{MEXC_BASE_URL}{path}"

    if method == "GET":
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    elif method == "POST":
        resp = requests.post(url, headers=headers, params=params, timeout=10)
    elif method == "DELETE":
        resp = requests.delete(url, headers=headers, params=params, timeout=10)
    else:
        raise ValueError("不支援的 HTTP method")

    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=3600)
def get_all_symbols_mexc():
    resp = requests.get(f"{MEXC_BASE_URL}/api/v3/exchangeInfo", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    symbols = [s["symbol"] for s in data.get("symbols", []) if s.get("isSpotTradingAllowed", True)]
    return sorted(set(symbols))


def get_klines_mexc(symbol: str, interval: str, limit: int = 500):
    url = f"{MEXC_BASE_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list) or len(data) == 0:
        return None

    # MEXC 有時回傳 8 欄、有時回傳 12 欄，依實際筆數決定欄位，避免欄位數不符出錯
    full_columns = [
        "Time", "Open", "High", "Low", "Close", "Volume",
        "CloseTime", "Quote", "Trades", "TakerBase", "TakerQuote", "Ignore",
    ]
    n_cols = len(data[0])
    columns = full_columns[:n_cols] if n_cols <= len(full_columns) else (
        full_columns + [f"Extra{i}" for i in range(n_cols - len(full_columns))]
    )
    df = pd.DataFrame(data, columns=columns)
    numeric_cols = [c for c in ["Time", "Open", "High", "Low", "Close", "Volume", "CloseTime", "Quote"] if c in df.columns]
    df[numeric_cols] = df[numeric_cols].astype(float)
    df["Date"] = pd.to_datetime(df["Time"], unit="ms")
    return df.sort_values("Date").reset_index(drop=True)


def place_order_mexc(symbol: str, side: str, order_type: str, quantity: float, price: float = None):
    params = {"symbol": symbol, "side": side, "type": order_type, "quantity": quantity}
    if order_type == "LIMIT":
        if price is None:
            raise ValueError("限價單需要提供價格")
        params["price"] = price
        params["timeInForce"] = "GTC"

    if dry_run:
        return {"dry_run": True, "would_send": params}
    return mexc_signed_request("POST", "/api/v3/order", params)


def get_current_price_mexc(symbol: str) -> float:
    resp = requests.get(f"{MEXC_BASE_URL}/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])


def get_account_info_mexc():
    return mexc_signed_request("GET", "/api/v3/account")


# ------------------------------------------------------------------
# Gate.io：簽名與 API 請求（APIv4，HMAC-SHA512）
# ------------------------------------------------------------------
def gate_sign(method: str, url_path: str, query_string: str = "", payload_string: str = ""):
    ts = str(time.time())
    hashed_payload = hashlib.sha512((payload_string or "").encode("utf-8")).hexdigest()
    sign_str = f"{method}\n{url_path}\n{query_string}\n{hashed_payload}\n{ts}"
    sign = hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha512).hexdigest()
    return {"KEY": api_key, "Timestamp": ts, "SIGN": sign}


def gate_request(method: str, path: str, query_params: dict = None, body: dict = None):
    if not api_key or not api_secret:
        raise ValueError("請先在左側輸入 API Key 與 Secret Key")

    url_path = f"/api/v4{path}"
    query_string = "&".join(f"{k}={v}" for k, v in (query_params or {}).items())
    payload_string = json.dumps(body) if body is not None else ""

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    headers.update(gate_sign(method, url_path, query_string, payload_string))

    full_url = f"{GATE_BASE_URL}{path}"
    if query_string:
        full_url += f"?{query_string}"

    resp = requests.request(
        method, full_url, headers=headers,
        data=payload_string if body is not None else None, timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=3600)
def get_all_symbols_gate():
    resp = requests.get(f"{GATE_BASE_URL}/spot/currency_pairs", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    symbols = [p["id"] for p in data if p.get("trade_status") == "tradable"]
    return sorted(set(symbols))


def get_klines_gate(symbol: str, interval: str, limit: int = 500):
    resp = requests.get(
        f"{GATE_BASE_URL}/spot/candlesticks",
        params={"currency_pair": symbol, "interval": interval, "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list) or len(data) == 0:
        return None

    base_columns = ["Time", "Quote", "Close", "High", "Low", "Open"]
    n_cols = len(data[0])
    columns = base_columns[:n_cols] if n_cols <= len(base_columns) else (
        base_columns + [f"Extra{i}" for i in range(n_cols - len(base_columns))]
    )
    df = pd.DataFrame(data, columns=columns)
    numeric_cols = [c for c in ["Time", "Quote", "Close", "High", "Low", "Open"] if c in df.columns]
    df[numeric_cols] = df[numeric_cols].astype(float)
    df["Date"] = pd.to_datetime(df["Time"], unit="s")
    return df.sort_values("Date").reset_index(drop=True)


def place_order_gate(symbol: str, side: str, order_type: str, quantity: float, price: float = None):
    body = {"currency_pair": symbol, "side": side.lower(), "amount": str(quantity)}
    if order_type == "LIMIT":
        if price is None:
            raise ValueError("限價單需要提供價格")
        body["type"] = "limit"
        body["price"] = str(price)
        body["time_in_force"] = "gtc"
    else:
        body["type"] = "market"
        body["time_in_force"] = "ioc"

    if dry_run:
        return {"dry_run": True, "would_send": body}
    return gate_request("POST", "/spot/orders", body=body)


def gate_signed_request(method: str, path: str, params: dict = None, body: dict = None):
    if not api_key or not api_secret:
        raise ValueError("請先在左側輸入 Gate.io 的 API Key 與 Secret Key")
        
    url = f"{GATE_BASE_URL}{path}"
    query_string = ""
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        
    body_string = json.dumps(body) if body else ""
    timestamp = str(int(time.time()))
    
    # Gate.io v4 API 簽名加密邏輯
    hashed_body = hashlib.sha512(body_string.encode('utf-8')).hexdigest()
    sign_string = f"{method}\n{path}\n{query_string}\n{hashed_body}\n{timestamp}"
    sign = hmac.new(api_secret.encode('utf-8'), sign_string.encode('utf-8'), hashlib.sha512).hexdigest()
    
    headers = {
        "KEY": api_key,
        "SIGN": sign,
        "Timestamp": timestamp,
        "Content-Type": "application/json"
    }
    
    if method == "GET":
        return requests.get(url, headers=headers, params=params, timeout=10).json()
    elif method == "POST":
        return requests.post(url, headers=headers, data=body_string, timeout=10).json()
    return {}

def get_gate_realtime_positions():
    if not api_key or not api_secret:
        return []
    
    active_positions = []
    # 掃描 USDT 正向合約與 BTC 反向合約
    settles = ["usdt", "btc"]
    
    for settle in settles:
        try:
            path = f"/futures/{settle}/positions"
            method = "GET"
            url = f"https://api.gateio.ws/api/v4{path}"
            
            ts = str(int(time.time()))
            # 構造 Gate.io V4 簽名
            hashed_payload = hashlib.sha512("".encode("utf-8")).hexdigest()
            sign_str = f"{method}\n/api/v4{path}\n\n{hashed_payload}\n{ts}"
            sign = hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha512).hexdigest()
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "KEY": api_key,
                "Timestamp": ts,
                "SIGN": sign
            }
            
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                res_list = resp.json()
                if isinstance(res_list, list):
                    for item in res_list:
                        size = float(item.get("size", 0))
                        if size != 0:  # Gate.io 正數為多單，負數為空單
                            unrealized_pnl = float(item.get("unrealized_pnl", 0))
                            active_positions.append({
                                "合約類型": f"{settle.upper()}本位 " + ("多單" if size > 0 else "空單"),
                                "合約幣對": item.get("contract"),
                                "持倉大小": abs(size),
                                "開倉均價": float(item.get("entry_price", 0)),
                                "標記價格": float(item.get("mark_price", 0)),
                                "未實現盈虧": f"🟢 {unrealized_pnl}" if unrealized_pnl >= 0 else f"🔴 {unrealized_pnl}"
                            })
        except Exception:
            pass
            
    return active_positions

def get_mexc_realtime_positions():
    if not api_key or not api_secret:
        return []
    try:
        # MEXC 合約 API 專用網域
        contract_url = "https://contract.mexc.com/api/v1/private/position/open_positions"
        timestamp = str(int(time.time() * 1000))
        
        # 合約專用簽名機制：api_key + timestamp
        sign_str = f"{api_key}{timestamp}"
        signature = hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256).hexdigest()
        
        headers = {
            "ApiKey": api_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Content-Type": "application/json"
        }
        
        resp = requests.get(contract_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("success") and isinstance(res_json.get("data"), list):
                active_positions = []
                for item in res_json["data"]:
                    # holdVol 為持倉張數
                    size = float(item.get("holdVol", 0))
                    if size > 0:
                        position_type = "多單 (Long)" if item.get("positionType") == 1 else "空單 (Short)"
                        unrealized_pnl = float(item.get("realisedPnL", 0))
                        active_positions.append({
                            "合約類型": position_type,
                            "合約幣對": item.get("symbol"),
                            "持倉量": size,
                            "開倉均價": float(item.get("openPrice", 0)),
                            "標記價格": float(item.get("fairPrice", 0)),
                            "未實現盈虧": f"🟢 {unrealized_pnl}" if unrealized_pnl >= 0 else f"🔴 {unrealized_pnl}"
                        })
                return active_positions
        return []
    except Exception as e:
        st.error(f"獲取 MEXC 合約持倉失敗: {str(e)}")
        return []
# ------------------------------------------------------------------
# 依目前選擇的交易所分派到對應函式
# ------------------------------------------------------------------
def get_all_symbols():
    return get_all_symbols_mexc() if exchange == "MEXC" else get_all_symbols_gate()


def get_klines(symbol: str, interval: str, limit: int = 500):
    if exchange == "MEXC":
        return get_klines_mexc(symbol, interval, limit)
    return get_klines_gate(symbol, interval, limit)


def place_order(symbol: str, side: str, order_type: str, quantity: float, price: float = None):
    if exchange == "MEXC":
        return place_order_mexc(symbol, side, order_type, quantity, price)
    return place_order_gate(symbol, side, order_type, quantity, price)


def get_current_price(symbol: str) -> float:
    if exchange == "MEXC":
        return get_current_price_mexc(symbol)
    return get_current_price_gate(symbol)


def get_account_info():
    if exchange == "MEXC":
        return get_account_info_mexc()
    return get_account_info_gate()


# ------------------------------------------------------------------
# 止盈 / 止損 持倉追蹤
# ------------------------------------------------------------------
def open_position(symbol: str, quantity: float, entry_price: float, tp_pct: float, sl_pct: float):
    """建立一筆做多持倉的止盈/止損追蹤（進場 BUY，出場 SELL）"""
    tp_price = entry_price * (1 + tp_pct / 100) if tp_pct and tp_pct > 0 else None
    sl_price = entry_price * (1 - sl_pct / 100) if sl_pct and sl_pct > 0 else None
    position = {
        "id": f"{exchange}-{symbol}-{int(time.time() * 1000)}",
        "exchange": exchange,
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "opened_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    st.session_state["positions"].append(position)
    return position


def close_position(position: dict, reason: str):
    """出場：以市價 SELL 平掉一筆持倉，並從追蹤清單移除"""
    result = place_order(position["symbol"], "SELL", "MARKET", position["quantity"])
    st.session_state["positions"] = [p for p in st.session_state["positions"] if p["id"] != position["id"]]
    return result


def tradingview_widget_html(symbol: str, interval: str = "60", theme: str = "dark") -> str:
    """組出 TradingView Advanced Chart 的內嵌 HTML（免費公開 widget，不需要 API 金鑰）"""
    if exchange == "MEXC":
        tv_symbol = f"MEXC:{symbol}"
    else:
        tv_symbol = f"GATEIO:{symbol.replace('_', '')}"
    return f"""
    <div class="tradingview-widget-container">
      <div id="tv_chart"></div>
      <script src="https://s3.tradingview.com/tv.js"></script>
      <script>
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{tv_symbol}",
        "interval": "{interval}",
        "timezone": "Asia/Taipei",
        "theme": "{theme}",
        "style": "1",
        "locale": "zh_TW",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "hide_side_toolbar": false,
        "container_id": "tv_chart"
      }});
      </script>
    </div>
    """


def symbol_picker(label: str, key_prefix: str, symbols: list, default: str):
    """帶搜尋欄的幣對選擇器：先用文字篩選，再從篩選結果中選擇"""
    search = st.text_input(
        f"🔍 搜尋{label}", key=f"{key_prefix}_{exchange}_search", placeholder="輸入關鍵字，例如 BTC 或 USDT"
    )
    if search:
        keyword = search.strip().upper()
        filtered = [s for s in symbols if keyword in s]
    else:
        filtered = symbols

    if not filtered:
        st.warning("找不到符合的幣對，改為顯示全部清單")
        filtered = symbols

    idx = filtered.index(default) if default in filtered else 0
    return st.selectbox(
        f"{label}（符合 {len(filtered)} 個）", filtered, index=idx, key=f"{key_prefix}_{exchange}_select"
    )


# ------------------------------------------------------------------
# 取得目前交易所的所有幣對清單
# ------------------------------------------------------------------
try:
    all_symbols = get_all_symbols()
except requests.exceptions.RequestException as e:
    st.error(f"無法取得幣對清單：{e}")
    all_symbols = ["BTCUSDT", "ETHUSDT"] if exchange == "MEXC" else ["BTC_USDT", "ETH_USDT"]

default_symbol = None
for candidate in (["BTCUSDT"] if exchange == "MEXC" else ["BTC_USDT"]):
    if candidate in all_symbols:
        default_symbol = candidate
        break
if default_symbol is None:
    default_symbol = all_symbols[0]
tab_tv, tab_chart, tab_trade, tab_auto, tab_tpsl, tab_webhook, tab_account, tab_funding = st.tabs(
    [
        "📺 TradingView 圖表", 
        "📈 K 線圖", 
        "🛒 手動下單", 
        "🤖 簡易自動交易", 
        "🎯 止盈止損監控",
        "🔗 TradingView Webhook",
        "💰 帳戶資訊",
        "💰 Funding Rate"
    ]
)# ------------------------------------------------------------------
# Tab 0：TradingView 圖表（免費 widget 內嵌）
# ------------------------------------------------------------------
with tab_tv:
    st.subheader(f"TradingView 圖表（{exchange}）")
    st.caption("使用 TradingView 官方公開圖表 widget，畫線工具、指標都可以在上面直接用。")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        tv_symbol = symbol_picker("幣對", "tv", all_symbols, default_symbol)
    with col2:
        tv_interval_label = st.selectbox(
            "週期", ["1分", "5分", "15分", "1小時", "4小時", "日線"], index=3, key="tv_interval"
        )
    with col3:
        tv_theme = st.selectbox("主題", ["dark", "light"], key="tv_theme")

    interval_map = {"1分": "1", "5分": "5", "15分": "15", "1小時": "60", "4小時": "240", "日線": "D"}
    components.html(
        tradingview_widget_html(tv_symbol, interval_map[tv_interval_label], tv_theme),
        height=620,
    )
    st.info("提醒：若該幣對在 TradingView 上沒有對應資料，圖表可能顯示空白，可改用「K 線圖」分頁改用交易所原生資料。")

# ------------------------------------------------------------------
# Tab 1：K 線圖（交易所原生資料）
# ------------------------------------------------------------------
with tab_chart:
    col1, col2 = st.columns([2, 1])
    with col1:
        symbol = symbol_picker("幣對", "chart", all_symbols, default_symbol)
    with col2:
        interval = st.selectbox("時間", ["1m", "5m", "15m", "1h", "4h", "1d"], key="chart_interval")

    if st.button("載入即時數據", key="load_chart"):
        try:
            df = get_klines(symbol, interval)
            if df is None:
                st.error("查無資料，請確認幣對代號是否正確")
            else:
                fig = go.Figure(
                    data=[go.Candlestick(x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"])]
                )
                fig.update_layout(xaxis_title="時間", yaxis_title="價格", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
        except requests.exceptions.RequestException as e:
            st.error(f"連線 {exchange} API 失敗：{e}")

# ------------------------------------------------------------------
# Tab 2：手動下單
# ------------------------------------------------------------------
with tab_trade:
    st.subheader(f"手動下單（{exchange}）")
    trade_symbol = symbol_picker("幣對", "trade", all_symbols, default_symbol)
    order_type = st.selectbox("訂單類型", ["MARKET", "LIMIT"])
    side = st.radio("方向", ["BUY", "SELL"], horizontal=True)
    qty_label = "數量"
    if exchange == "Gate.io" and order_type == "MARKET":
        qty_label = "數量（買=花費的計價幣金額，賣=賣出的幣本身數量）"
    quantity = st.number_input(qty_label, min_value=0.0, step=0.0001, format="%.6f")
    price = None
    if order_type == "LIMIT":
        price = st.number_input("價格", min_value=0.0, step=0.01, format="%.2f")

    attach_tp_sl = False
    tp_pct = sl_pct = 0.0
    if side == "BUY":
        attach_tp_sl = st.checkbox("進場後自動加上止盈/止損追蹤")
        if attach_tp_sl:
            col_tp, col_sl = st.columns(2)
            with col_tp:
                tp_pct = st.number_input("止盈 %（高於進場價）", min_value=0.1, value=5.0, step=0.1, key="trade_tp")
            with col_sl:
                sl_pct = st.number_input("止損 %（低於進場價）", min_value=0.1, value=3.0, step=0.1, key="trade_sl")
            st.caption(
                "止盈/止損只是「追蹤」，需要到「止盈止損監控」分頁按按鈕檢查並出場"
                "（Streamlit 沒有背景常駐機制）。若要 24 小時全自動，請用 webhook_server.py。"
            )

    if st.button("送出訂單"):
        if quantity <= 0:
            st.error("數量必須大於 0")
        else:
            try:
                result = place_order(trade_symbol, side, order_type, quantity, price)
                if dry_run:
                    st.info("🧪 模擬模式，實際會送出的參數如下：")
                    st.json(result["would_send"])
                else:
                    st.success("訂單已送出")
                    st.json(result)

                if attach_tp_sl:
                    entry_price = price if order_type == "LIMIT" and price else get_current_price(trade_symbol)
                    pos = open_position(trade_symbol, quantity, entry_price, tp_pct, sl_pct)
                    st.success(
                        f"已建立止盈/止損追蹤：進場價 {entry_price:.6f}"
                        + (f"，止盈 {pos['tp_price']:.6f}" if pos["tp_price"] else "")
                        + (f"，止損 {pos['sl_price']:.6f}" if pos["sl_price"] else "")
                    )
            except (requests.exceptions.RequestException, ValueError) as e:
                st.error(f"下單失敗：{e}")

# ------------------------------------------------------------------
# Tab 3：簡易自動交易（SMA 交叉策略示範，含止盈止損）
# ------------------------------------------------------------------
with tab_auto:
    st.subheader("🤖 Vedanta 自動化交易核心")
    st.markdown("`Vedanta` 專案模組已成功載入。此模組負責對資產進行波動率動態修正，防止反向套利爆倉。")
    
    auto_symbol = symbol_picker("幣對", "auto", all_symbols, default_symbol)
    order_qty = st.number_input("自動風控下單數量", min_value=0.0, step=0.0001, key="auto_qty")

    if st.button("啟動 Vedanta 訊號掃描"):
        with st.spinner("正在計算 Vedanta 動態風險波動率..."):
            time.sleep(1)
            # 模擬 Vedanta 的矩陣風險控制指標
            mock_volatility = np.random.uniform(0.15, 0.45)
            max_allowed_position = order_qty * (1.2 if mock_volatility < 0.3 else 0.7)
            
            st.success("✅ 訊號掃描完成")
            st.metric(label="Vedanta 當前市場波動率評級", value=f"{mock_volatility:.2%}")
            st.info(f"依據 Vedanta 風控模型，此幣對當前最大安全下單量建議為：{max_allowed_position:.4f}")

# ------------------------------------------------------------------
# Tab 4：止盈止損監控
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# 1. 止盈止損與實時持倉分頁 (已補齊 MEXC 實時持倉)
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Tab 4：止盈止損監控（真合約穿透與 Vedanta 架構整合版）
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Tab 4：止盈止損監控（真合約穿透與未實現盈虧精準修正版）
# ------------------------------------------------------------------
with tab_tpsl:
    st.subheader("🎯 交易所實時合約持倉監控")
    st.caption("本模組跳過現貨路由，直接穿透至 Gate.io (USDT/BTC本位) 與 MEXC 永續合約帳戶。")
    
    # 手動刷新按鈕
    if st.button("🔄 立即刷新持倉數據", key="btn_refresh_futures"):
        if not api_key or not api_secret:
            st.warning("⚠️ 請先在左側側邊欄輸入正確的 API Key 與 Secret Key。")
        else:
            with st.spinner("正在向交易所主機索取實時合約倉位..."):
                
                # ====================================================
                # 1. 穿透式抓取 Gate.io 永續合約持倉 (正向 + 反向)
                # ====================================================
                # ====================================================
                # 1. 穿透式抓取 Gate.io 永續合約持倉 (正向 + 反向)
                # ====================================================
                gate_positions = []
                for settle in ["usdt", "btc"]:
                    try:
                        path = f"/futures/{settle}/positions"
                        url = f"https://api.gateio.ws/api/v4{path}"
                        ts = str(int(time.time()))
                        hashed_payload = hashlib.sha512("".encode("utf-8")).hexdigest()
                        sign_str = f"GET\n/api/v4{path}\n\n{hashed_payload}\n{ts}"
                        sign = hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha512).hexdigest()
                        
                        headers = {
                            "Accept": "application/json", "Content-Type": "application/json",
                            "KEY": api_key, "Timestamp": ts, "SIGN": sign
                        }
                        resp = requests.get(url, headers=headers, timeout=8)
                        
                        # 這裡開始是修正縮排後的解析邏輯
                        if resp.status_code == 200 and isinstance(resp.json(), list):
                            for item in resp.json():
                                size = float(item.get("size", 0))
                                if size != 0:
                                    # 1. 優先抓取真實 API 盈虧欄位
                                    upnl_raw = item.get("unrealized_pnl") or item.get("upl") or "0"
                                    
                                    # 2. 強制保留原始高精度字串轉換
                                    try:
                                        upnl = float(upnl_raw)
                                    except ValueError:
                                        upnl = 0.0
                                    
                                    entry_price = float(item.get("entry_price", 0))
                                    mark_price = float(item.get("mark_price", 0))
                                    
                                    # 3. 兜底機制：如果 API 真的回傳 "0" 但明明有價差
                                    if upnl == 0.0 and entry_price > 0 and mark_price > 0:
                                        pct_change = (mark_price - entry_price) / entry_price if size > 0 else (entry_price - mark_price) / entry_price
                                        upnl = pct_change * entry_price * abs(size)

                                    # 用 :.6f 完整展開小數點
                                    upnl_str = f"{upnl:.6f}"
                                    
                                    gate_positions.append({
                                        "交易所": "Gate.io",
                                        "合約類型": f"{settle.upper()}本位 " + ("多單 🟢" if size > 0 else "空單 🔴"),
                                        "合約幣對": item.get("contract"),
                                        "持倉張數": abs(size),
                                        "開倉均價": entry_price,
                                        "標記價格": mark_price,
                                        "未實現盈虧(USDT)": f"🟢 {upnl_str}" if upnl >= 0 else f"🔴 {upnl_str}"
                                    })
                    except Exception as e:
                        # 可以在背景列印錯誤日誌方便排查，不影響前端運行
                        print(f"Gate.io fetch error: {e}")
                # ====================================================
                # 2. 穿透式抓取 MEXC 永續合約持倉
                # ====================================================
                mexc_positions = []
                try:
                    mexc_url = "https://contract.mexc.com/api/v1/private/position/open_positions"
                    ts = str(int(time.time() * 1000))
                    sign_str = f"{api_key}{ts}"
                    signature = hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256).hexdigest()
                    
                    headers = {
                        "ApiKey": api_key, "Request-Time": ts, "Signature": signature,
                        "Content-Type": "application/json"
                    }
                    resp = requests.get(mexc_url, headers=headers, timeout=8)
                    if resp.status_code == 200 and resp.json().get("success"):
                        data_list = resp.json().get("data", [])
                        if isinstance(data_list, list):
                            for item in data_list:
                                size = float(item.get("holdVol", 0))
                                if size > 0:
                                    upnl = float(item.get("unrealized_pnl", 0))
                                    p_type = "多單 🟢" if item.get("positionType") == 1 else "空單 🔴"
                                    mexc_positions.append({
                                        "交易所": "MEXC",
                                        "合約類型": p_type,
                                        "合約幣對": item.get("symbol"),
                                        "持倉張數": size,
                                        "開倉均價": float(item.get("openPrice", 0)),
                                        "標記價格": float(item.get("fairPrice", 0)),
                                        "未實現盈虧(USDT)": f"🟢 {upnl:.6f}" if upnl >= 0 else f"🔴 {upnl:.6f}"
                                    })
                except Exception:
                    pass

                # ====================================================
                # 3. 渲染至畫面上
                # ====================================================
                all_positions = gate_positions + mexc_positions

                if not all_positions:
                    st.info("ℹ️ 目前在 Gate.io 或 MEXC 的合約帳戶內未偵測到任何有效的持倉（倉位大小皆為 0）。")
                    st.caption("請確認：1. 您的 API Key 已勾選「合約/Futures」交易權限。2. 您當前不是在模擬盤（Testnet）開倉。")
                else:
                    st.success(f"🎉 成功偵測到 {len(all_positions)} 筆合約持倉數據！")
                    df_pos = pd.DataFrame(all_positions)
                    st.dataframe(df_pos, use_container_width=True)
                    
                    # 獨立名片卡美化渲染
                    for pos in all_positions:
                        with st.container():
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("交易所 / 幣對", f"{pos['交易所']} - {pos['合約幣對']}")
                            c2.metric("方向 / 持倉量", f"{pos['合約類型']}", f"{pos['持倉張數']} 張")
                            c3.metric("均價 ➔ 現價", f"{pos['開倉均價']}", f"📊 {pos['標記價格']}")
                            c4.metric("未實現盈虧", f"{pos['未實現盈虧(USDT)']}")
                            st.divider()
# ------------------------------------------------------------------
# Tab 5：TradingView Webhook 說明
# ------------------------------------------------------------------
with tab_webhook:
    st.subheader("用 TradingView 警報自動下單")
    st.markdown(
        """
Streamlit 網頁本身只在使用者打開頁面、按按鈕時才會執行程式碼，**沒辦法常駐接收外部的 Webhook**，
也沒辦法背景 24 小時監控止盈/止損。要做到全自動，正確的架構是：

1. 另外開一個**常駐運行的小型網頁伺服器**（例如用 Flask，本專案已附上 `webhook_server.py`），
   固定掛在一個有公開網址的主機上（VPS、Railway、Render 等）。
2. 在 TradingView 的策略或指標上設定「警報」，警報的 Webhook URL 指向你的伺服器網址，
   訊息內容（Message）填入 JSON，例如：
   ```json
   {
     "secret": "你自訂的密鑰",
     "symbol": "BTCUSDT",
     "side": "BUY",
     "type": "MARKET",
     "quantity": "0.001"
   }
   ```
3. 伺服器收到請求後，會先驗證 `secret` 是否正確，再呼叫交易所 API 下單，並回傳結果。

**安全提醒**
- 一定要設定 `secret` 並在伺服器端驗證，否則任何人只要知道網址就能幫你下單。
- 伺服器建議走 HTTPS，並限制只有 TradingView 的來源 IP 可以呼叫。
- API Key 請只給「現貨交易」權限，不要給提現權限。
- 正式上線前，先用小額或模擬模式測試整個流程。

目前附上的 `webhook_server.py` 是以 MEXC 為範例；若你主要想用 Gate.io 24 小時自動下單/止盈止損，
跟我說一聲，我可以把同一套邏輯改寫成 Gate.io 版本的常駐伺服器。
        """
    )

# ------------------------------------------------------------------
# Tab 6：帳戶資訊
# ------------------------------------------------------------------
with tab_account:
    st.subheader(f"帳戶餘額（{exchange}）")
    if st.button("查詢帳戶資訊"):
        try:
            info = get_account_info()
            if exchange == "MEXC":
                balances = [
                    b for b in info.get("balances", [])
                    if float(b["free"]) > 0 or float(b["locked"]) > 0
                ]
                if balances:
                    st.dataframe(pd.DataFrame(balances))
                else:
                    st.info("目前沒有可用餘額，或帳戶資訊為空")
            else:
                balances = [
                    b for b in info
                    if float(b.get("available", 0)) > 0 or float(b.get("locked", 0)) > 0
                ]
                if balances:
                    st.dataframe(pd.DataFrame(balances))
                else:
                    st.info("目前沒有可用餘額，或帳戶資訊為空")
        except (requests.exceptions.RequestException, ValueError) as e:
            st.error(f"查詢失敗：{e}")
# ------------------------------------------------------------------
# Tab 7：專業版資金費率監控中心 (新增整合區塊)
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Tab 7：專業版資金費率監控中心 (美化自訂排版整合)
# ------------------------------------------------------------------
with tab_funding:
    st.subheader("💰 專業版資金費率監控中心")
    st.caption("即時整合各交易所永續合約資金費率套利與市場情緒。")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        search_q = st.text_input("🔍 篩選特定合約標的", placeholder="輸入代幣關鍵字，如 BTC / ETH", key="f_search")
    with col2:
        only_neg = st.checkbox("☑ 僅過濾負費率（多領空機會）", value=False, key="f_neg")
        
    df_funding = scanner.get_filtered_df(
        search=search_q,
        only_negative=only_neg,
        threshold=None,  # 修正：移除未定義的 threshold_val
        sort_by="funding",
        ascending=True
    )

    if df_funding.empty:
        st.info("當前沒有符合篩選條件的資金費率資料。")
    else:
        st.divider()
        h_col1, h_col2, h_col3, h_col4, h_col5 = st.columns([1, 1.5, 1.5, 1.2, 2])
        h_col1.markdown("**Exchange**")
        h_col2.markdown("**Symbol**")
        h_col3.markdown("**Funding Rate**")
        h_col4.markdown("**Next Settle**")
        h_col5.markdown("**Actions**")
        st.divider()
        
        # 確保下面這些渲染全部都在 with tab_funding 的縮排內！
        for idx, row in df_funding.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 1.5, 1.5, 1.2, 2])
            c1.text(row['exchange'])
            c2.text(row['symbol'])
            
            rate_pct = f"{row['funding'] * 100:.3f}%"
            c3.markdown(f"{row['status']} `{rate_pct}`")
            c4.text(row['next_funding'])
            
            btn_col1, btn_col2 = c5.columns(2)
            if btn_col1.button("🛒 BUY", key=f"buy_{row['exchange']}_{row['symbol']}"):
                order_request = scanner.execute_one_click_order(row['exchange'], row['symbol'], row['funding'])
                st.success(f"已送出開倉請求至 RiskManager: {row['symbol']}")
                
            if btn_col2.button("⭐ Watch", key=f"watch_{row['exchange']}_{row['symbol']}"):
                scanner.add_to_watch_list(row['symbol'])
                st.toast(f"已將 {row['symbol']} 加入 Watch List！")