import ccxt
import streamlit as st
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

from exchange.gate_futures import GateFuturesExchange
from exchange.gate_spot import GateSpotExchange
from exchange.mexc_futures import MEXCFuturesExchange
from exchange.base import ExchangeException

MEXC_BASE_URL = "https://api.mexc.com"
GATE_BASE_URL = "https://api.gateio.ws/api/v4"

st.set_page_config(page_title="多交易所交易工具", layout="wide")
st.title("MEXC / Gate.io 交易工具")

# ------------------------------------------------------------------
# 側邊欄：交易所 & API 金鑰設定
# ------------------------------------------------------------------
st.sidebar.header("⚙️ 交易所設定")
exchange = st.sidebar.selectbox("選擇交易所", ["MEXC", "Gate.io"])

st.sidebar.header("🔑 API 金鑰")


def get_secret(key: str) -> str:
    """從 Streamlit Secrets 讀取金鑰，沒設定就回傳空字串（不會噴錯）"""
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

**本機測試**：在專案資料夾建立 `.streamlit/secrets.toml`（記得加進 `.gitignore`，絕對不要上傳到 GitHub）：
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
# MEXC 現貨：簽名與 API 請求
# ------------------------------------------------------------------
def mexc_sign_params(params: dict, secret: str) -> str:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


def mexc_signed_request(method: str, path: str, params: dict = None, key: str = None, secret: str = None):
    """
    通用版：預設用側邊欄的 api_key/api_secret，
    但也可以傳入獨立的 key/secret（供「持倉監控」分頁同時查多組金鑰使用）。
    """
    use_key = key or api_key
    use_secret = secret or api_secret
    if not use_key or not use_secret:
        raise ValueError("請先輸入 API Key 與 Secret Key")

    params = params.copy() if params else {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    params["signature"] = mexc_sign_params(params, use_secret)

    headers = {"X-MEXC-APIKEY": use_key}
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


def get_mexc_spot_balance(key: str, secret: str):
    """供「持倉監控」分頁使用：用獨立金鑰查 MEXC 現貨餘額"""
    data = mexc_signed_request("GET", "/api/v3/account", key=key, secret=secret)
    return [b for b in data.get("balances", []) if float(b["free"]) > 0 or float(b["locked"]) > 0]


# ------------------------------------------------------------------
# Gate.io 現貨：簽名與 API 請求（APIv4，HMAC-SHA512）
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


def get_current_price_gate(symbol: str) -> float:
    resp = requests.get(f"{GATE_BASE_URL}/spot/tickers", params={"currency_pair": symbol}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError("查無此幣對報價")
    return float(data[0]["last"])


def get_account_info_gate():
    return gate_request("GET", "/spot/accounts")


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
# 止盈 / 止損 持倉追蹤（僅本次瀏覽器工作階段，模擬用）
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
# 資金費率掃描（簡化穩定版：任何一個交易所失敗都不影響另一個）
# ------------------------------------------------------------------
@st.cache_data(ttl=60)
def get_funding_rates() -> pd.DataFrame:
    rows = []

    try:
        gate_res = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=8).json()
        if isinstance(gate_res, list):
            for item in gate_res:
                symbol = item.get("contract", "")
                if not symbol.endswith("_USDT"):
                    continue
                fr = float(item.get("funding_rate", 0) or 0)
                rows.append({"交易所": "Gate.io", "合約": symbol, "資金費率": fr,
                             "狀態": "🟢 負費率" if fr < 0 else "🔴 正費率"})
    except Exception:
        pass

    try:
        mexc_res = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=8).json()
        if isinstance(mexc_res, dict) and mexc_res.get("success"):
            for item in mexc_res.get("data", []) or []:
                fr = float(item.get("fundingRate", 0) or 0)
                rows.append({"交易所": "MEXC", "合約": item.get("symbol", ""), "資金費率": fr,
                             "狀態": "🟢 負費率" if fr < 0 else "🔴 正費率"})
    except Exception:
        pass

    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# 持倉監控：統一格式，串接 exchange/ 底下的 GateFuturesExchange /
# GateSpotExchange / MEXCFuturesExchange，同時查現貨+合約
# ------------------------------------------------------------------
def _position_rows(exchange_name: str, market: str, positions: list) -> list:
    rows = []
    for p in positions:
        rows.append({
            "交易所": exchange_name,
            "市場": market,
            "幣種/合約": p["symbol"],
            "方向": {"long": "多單 🟢", "short": "空單 🔴"}.get(p["side"], "—"),
            "數量": p["size"],
            "進場價": p["entry_price"] if p["entry_price"] is not None else "—",
            "槓桿": p["leverage"],
            "未實現盈虧": p["unrealised_pnl"] if p["unrealised_pnl"] is not None else "—",
        })
    return rows


def query_all_positions(gate_key, gate_secret, mexc_key, mexc_secret) -> pd.DataFrame:
    rows = []

    if gate_key and gate_secret:
        try:
            gs = GateSpotExchange(api_key=gate_key, api_secret=gate_secret)
            rows += _position_rows("Gate.io", "現貨", gs.get_positions())
        except ExchangeException as e:
            st.error(f"Gate.io 現貨查詢失敗：{e}")

        try:
            gf = GateFuturesExchange(api_key=gate_key, api_secret=gate_secret)
            rows += _position_rows("Gate.io", "合約", gf.get_positions())
        except ExchangeException as e:
            st.error(f"Gate.io 合約查詢失敗：{e}")
    else:
        st.caption("ℹ️ 尚未輸入 Gate.io 金鑰，略過 Gate.io 查詢")

    if mexc_key and mexc_secret:
        try:
            balances = get_mexc_spot_balance(mexc_key, mexc_secret)
            for b in balances:
                rows.append({
                    "交易所": "MEXC", "市場": "現貨", "幣種/合約": b["asset"],
                    "方向": "—", "數量": float(b["free"]) + float(b["locked"]),
                    "進場價": "—", "槓桿": "—", "未實現盈虧": "—",
                })
        except Exception as e:
            st.error(f"MEXC 現貨查詢失敗：{e}")

        try:
            mf = MEXCFuturesExchange(api_key=mexc_key, api_secret=mexc_secret)
            rows += _position_rows("MEXC", "合約", mf.get_positions())
        except ExchangeException as e:
            st.error(f"MEXC 合約查詢失敗：{e}")
    else:
        st.caption("ℹ️ 尚未輸入 MEXC 金鑰，略過 MEXC 查詢")

    return pd.DataFrame(rows)


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

tab_tv, tab_chart, tab_trade, tab_auto, tab_tpsl, tab_positions, tab_funding, tab_webhook, tab_account = st.tabs(
    ["📺 TradingView 圖表", "📈 K 線圖", "🛒 手動下單", "🤖 簡易自動交易",
     "🎯 止盈止損監控", "📊 持倉監控（全交易所）", "💰 資金費率", "🔗 TradingView Webhook", "💰 帳戶資訊"]
)

# ------------------------------------------------------------------
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
    st.subheader(f"簡易自動交易策略（{exchange} · SMA 均線交叉 + 止盈止損）")
    st.caption(
        "Streamlit 每次互動才會重新執行程式，並不適合當作 24 小時常駐的交易機器人。\n"
        "此頁籤示範「策略邏輯」：沒有持倉時偵測 SMA 黃金/死亡交叉進場；已有持倉時優先檢查止盈/止損出場。\n"
        "若要 24 小時全自動運行，建議搭配「TradingView Webhook」分頁的做法。"
    )

    auto_symbol = symbol_picker("幣對", "auto", all_symbols, default_symbol)
    auto_interval = st.selectbox("時間", ["1m", "5m", "15m", "1h"], key="auto_interval")
    fast_len = st.number_input("快線週期", min_value=2, max_value=200, value=9)
    slow_len = st.number_input("慢線週期", min_value=2, max_value=200, value=21)
    order_qty = st.number_input("每次下單數量", min_value=0.0, step=0.0001, format="%.6f", key="auto_qty")
    col_tp2, col_sl2 = st.columns(2)
    with col_tp2:
        auto_tp_pct = st.number_input("止盈 %", min_value=0.0, value=5.0, step=0.1, key="auto_tp")
    with col_sl2:
        auto_sl_pct = st.number_input("止損 %", min_value=0.0, value=3.0, step=0.1, key="auto_sl")

    if st.button("檢查訊號並執行一次"):
        try:
            existing_position = next(
                (p for p in st.session_state["positions"] if p["symbol"] == auto_symbol and p["exchange"] == exchange),
                None,
            )

            if existing_position:
                current_price = get_current_price(auto_symbol)
                st.write(f"目前持倉中，最新價格：{current_price:.6f}")
                if existing_position["tp_price"] and current_price >= existing_position["tp_price"]:
                    result = close_position(existing_position, "止盈")
                    st.success("已觸及止盈，市價出場完成")
                    st.json(result)
                elif existing_position["sl_price"] and current_price <= existing_position["sl_price"]:
                    result = close_position(existing_position, "止損")
                    st.warning("已觸及止損，市價出場完成")
                    st.json(result)
                else:
                    st.info("尚未觸及止盈/止損，暫不理會新的進場訊號，等下次再檢查")
            else:
                df = get_klines(auto_symbol, auto_interval, limit=max(100, slow_len + 5))
                if df is None or len(df) < slow_len + 2:
                    st.error("資料不足，無法計算均線")
                else:
                    df["fast_sma"] = df["Close"].rolling(fast_len).mean()
                    df["slow_sma"] = df["Close"].rolling(slow_len).mean()

                    prev_fast, prev_slow = df["fast_sma"].iloc[-2], df["slow_sma"].iloc[-2]
                    curr_fast, curr_slow = df["fast_sma"].iloc[-1], df["slow_sma"].iloc[-1]

                    signal = None
                    if prev_fast <= prev_slow and curr_fast > curr_slow:
                        signal = "BUY"
                    elif prev_fast >= prev_slow and curr_fast < curr_slow:
                        signal = "SELL"

                    st.write(f"最新收盤價：{df['Close'].iloc[-1]:.6f}")
                    st.write(f"快線 SMA({fast_len})：{curr_fast:.6f}　慢線 SMA({slow_len})：{curr_slow:.6f}")

                    if signal != "BUY":
                        st.info("目前沒有做多進場訊號（此策略僅示範做多），不執行下單")
                    elif order_qty <= 0:
                        st.error("請設定大於 0 的下單數量")
                    else:
                        result = place_order(auto_symbol, "BUY", "MARKET", order_qty)
                        if dry_run:
                            st.info("🧪 模擬模式，實際會送出的參數如下：")
                            st.json(result["would_send"])
                        else:
                            st.success("訂單已送出")
                            st.json(result)

                        entry_price = get_current_price(auto_symbol)
                        pos = open_position(auto_symbol, order_qty, entry_price, auto_tp_pct, auto_sl_pct)
                        st.success(
                            f"已建立止盈/止損追蹤：進場價 {entry_price:.6f}"
                            + (f"，止盈 {pos['tp_price']:.6f}" if pos["tp_price"] else "")
                            + (f"，止損 {pos['sl_price']:.6f}" if pos["sl_price"] else "")
                        )
        except (requests.exceptions.RequestException, ValueError) as e:
            st.error(f"執行失敗：{e}")

# ------------------------------------------------------------------
# Tab 4：止盈止損監控（本次瀏覽器工作階段的模擬追蹤）
# ------------------------------------------------------------------
with tab_tpsl:
    st.subheader("止盈止損監控")
    st.caption(
        "這裡列出的持倉只存在於這次瀏覽器工作階段（重新整理網頁、App 重啟都會清空）。\n"
        "Streamlit 沒有背景常駐機制，所以出場需要你手動按按鈕檢查；"
        "若要 24 小時全自動看盤出場，請改用 webhook_server.py 常駐監控（見下方 Webhook 分頁）。"
    )

    positions = [p for p in st.session_state["positions"] if p["exchange"] == exchange]

    if not positions:
        st.info(f"目前 {exchange} 沒有追蹤中的持倉")
    else:
        for pos in positions:
            with st.container(border=True):
                st.markdown(f"**{pos['symbol']}**　數量：{pos['quantity']}　建立時間：{pos['opened_at']}")
                try:
                    current_price = get_current_price(pos["symbol"])
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

                triggered = None
                if current_price is not None:
                    if pos["tp_price"] and current_price >= pos["tp_price"]:
                        triggered = "止盈"
                    elif pos["sl_price"] and current_price <= pos["sl_price"]:
                        triggered = "止損"

                btn1, btn2 = st.columns(2)
                with btn1:
                    if triggered:
                        st.warning(f"已觸及{triggered}條件！")
                        if st.button(f"執行{triggered}出場", key=f"auto_close_{pos['id']}"):
                            try:
                                result = close_position(pos, triggered)
                                st.success(f"{triggered}出場完成")
                                st.json(result)
                                st.rerun()
                            except (requests.exceptions.RequestException, ValueError) as e:
                                st.error(f"出場失敗：{e}")
                with btn2:
                    if st.button("手動平倉", key=f"manual_close_{pos['id']}"):
                        try:
                            result = close_position(pos, "手動")
                            st.success("已手動平倉")
                            st.json(result)
                            st.rerun()
                        except (requests.exceptions.RequestException, ValueError) as e:
                            st.error(f"平倉失敗：{e}")

# ------------------------------------------------------------------
# Tab 5：持倉監控（全交易所：Gate.io 現貨/合約 + MEXC 現貨/合約）
# ------------------------------------------------------------------
with tab_positions:
    st.subheader("📊 即時持倉監控（現貨 + 合約，全交易所）")
    st.caption(
        "跟上面幾個分頁不同，這裡直接向交易所查詢「真實帳戶」的現貨餘額與合約持倉，"
        "跟左側目前選擇的交易所無關，兩邊金鑰都可以獨立輸入。"
    )

    col_g, col_m = st.columns(2)
    with col_g:
        st.markdown("**Gate.io**")
        pos_gate_key = st.text_input(
            "Gate.io API Key", value=get_secret("GATE_API_KEY"), type="password", key="pos_gate_key"
        )
        pos_gate_secret = st.text_input(
            "Gate.io Secret Key", value=get_secret("GATE_API_SECRET"), type="password", key="pos_gate_secret"
        )
    with col_m:
        st.markdown("**MEXC**")
        pos_mexc_key = st.text_input(
            "MEXC API Key", value=get_secret("MEXC_API_KEY"), type="password", key="pos_mexc_key"
        )
        pos_mexc_secret = st.text_input(
            "MEXC Secret Key", value=get_secret("MEXC_API_SECRET"), type="password", key="pos_mexc_secret"
        )

    auto_refresh = st.checkbox("每 10 秒自動刷新（需安裝 streamlit-autorefresh）", value=False, key="pos_auto_refresh")
    if auto_refresh:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=10_000, key="pos_autorefresh_timer")
        except ImportError:
            st.warning("尚未安裝 streamlit-autorefresh（`pip install streamlit-autorefresh`），目前先用手動刷新按鈕")
            auto_refresh = False

    if st.button("🔄 立即查詢所有持倉", key="btn_query_all_positions") or auto_refresh:
        with st.spinner("查詢中..."):
            df_positions = query_all_positions(pos_gate_key, pos_gate_secret, pos_mexc_key, pos_mexc_secret)
        if df_positions.empty:
            st.info("沒有查到任何持倉或非零餘額，或尚未輸入任何金鑰。")
        else:
            st.success(f"共查到 {len(df_positions)} 筆")
            st.dataframe(df_positions, use_container_width=True)

    st.caption(
        "💡 這裡只查詢，不會下單。若要背景 24 小時輪詢並用 Telegram 通知持倉變化，"
        "請改用專案裡的 `position_poller.py`（獨立背景程式，見 README）。"
    )

# ------------------------------------------------------------------
# Tab 6：資金費率
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Tab 6：資金費率 (請複製並取代您的最後一段程式碼)
# ------------------------------------------------------------------
df_funding = get_funding_rates()
    
    if not df_funding.empty:
        # 篩選負費率
        df_negative = df_funding[df_funding['資金費率'] < 0]
        
        if not df_negative.empty:
            st.dataframe(df_negative.style.map(
                lambda x: 'color: green', 
                subset=['資金費率']
            ), use_container_width=True)
        else:
            st.info("目前沒有發現負費率的合約。")
    else:
        # 這個 else 必須和上面第一層的 if 對齊
        st.info("目前無法讀取資金費率資料。")
# ------------------------------------------------------------------
# Tab 7：TradingView Webhook 說明
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
# Tab 8：帳戶資訊
# ------------------------------------------------------------------
def get_gate_futures_balance():
    # 初始化 Gate.io 合約接口
    exchange = ccxt.gate({
        'apiKey': st.secrets["GATE_API_KEY"],
        'secret': st.secrets["GATE_API_SECRET"],
        'options': {'defaultType': 'swap'}
    })
    # 查詢餘額
    balance = exchange.fetch_balance({'type': 'swap'})
    return balance.get('total', {}).get('USDT', 0)

def get_futures_balance():
    # 初始化 MEXC 合約接口
    exchange = ccxt.mexc({
        'apiKey': st.secrets["MEXC_API_KEY"],
        'secret': st.secrets["MEXC_API_SECRET"],
        'options': {'defaultType': 'swap'}
    })
    # 查詢餘額
    balance = exchange.fetch_balance()
    # MEXC 合約餘額結構通常在 'USDT' 欄位
    return balance.get('total', {}).get('USDT', 0)
# 在頁面上顯示
if st.button("查詢合約餘額"):
    try:
        balance = get_futures_balance()
        st.success(f"目前合約帳戶餘額: {balance} USDT")
    except Exception as e:
        st.error(f"無法讀取餘額: {e}")
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
# 1. 定義查詢餘額的函數
def get_balance(exchange_name):
    try:
        if exchange_name == 'mexc':
            ex = ccxt.mexc({
                'apiKey': st.secrets["MEXC_API_KEY"],
                'secret': st.secrets["MEXC_API_SECRET"],
                'options': {'defaultType': 'swap'}
            })
        else: # 這是 Gate.io
            ex = ccxt.gate({
                'apiKey': st.secrets["GATE_API_KEY"],
                'secret': st.secrets["GATE_API_SECRET"],
                'options': {'defaultType': 'swap'}
            })
        balance = ex.fetch_balance()
        return balance['total'].get('USDT', 0)
    except Exception as e:
        return f"錯誤: {e}"

# 2. 這是按鈕介面，請確認它們在你的 app.py 中
if st.button("查詢 MEXC 合約餘額"):
    st.write(f"MEXC 餘額: {get_balance('mexc')} USDT")

if st.button("查詢 Gate.io 合約餘額"):
    st.write(f"Gate.io 餘額: {get_balance('gate')} USDT")