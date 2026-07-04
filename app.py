import time
import hmac
import hashlib
import requests
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go

BASE_URL = "https://api.mexc.com"

st.set_page_config(page_title="MEXC SMC 交易工具", layout="wide")
st.title("MEXC SMC 交易工具")

# ------------------------------------------------------------------
# 側邊欄：API 金鑰設定
# ------------------------------------------------------------------
st.sidebar.header("🔑 MEXC API 設定")
api_key = st.sidebar.text_input("API Key", type="password")
api_secret = st.sidebar.text_input("Secret Key", type="password")
dry_run = st.sidebar.checkbox("模擬模式（不會真的送出訂單）", value=True)

st.sidebar.markdown("---")
st.sidebar.warning(
    "⚠️ 風險提醒\n\n"
    "- 建立 API Key 時請「勿開啟提現權限」。\n"
    "- 建議先用小額資金測試，再放大部位。\n"
    "- 自動交易有虧損風險，程式無法保證獲利，請自行評估風險並對交易結果負責。\n"
    "- 本工具僅為程式協助，不構成投資建議。"
)


# ------------------------------------------------------------------
# 共用函式：簽名與私有 API 請求
# ------------------------------------------------------------------
def sign_params(params: dict, secret: str) -> str:
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return signature


def signed_request(method: str, path: str, params: dict = None):
    if not api_key or not api_secret:
        raise ValueError("請先在左側輸入 API Key 與 Secret Key")

    params = params.copy() if params else {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    params["signature"] = sign_params(params, api_secret)

    headers = {"X-MEXC-APIKEY": api_key}
    url = f"{BASE_URL}{path}"

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
def get_all_symbols():
    """取得所有可交易的幣對"""
    resp = requests.get(f"{BASE_URL}/api/v3/exchangeInfo", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    symbols = [
        s["symbol"]
        for s in data.get("symbols", [])
        if s.get("isSpotTradingAllowed", True)
    ]
    return sorted(set(symbols))


def get_klines(symbol: str, interval: str, limit: int = 500):
    url = f"{BASE_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list) or len(data) == 0:
        return None

    # MEXC 有時回傳 8 欄、有時回傳 12 欄，先用完整欄位名稱，
    # 再依實際筆數截取，避免欄位數量不一致造成錯誤。
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
    return df


def place_order(symbol: str, side: str, order_type: str, quantity: float, price: float = None):
    """送出現貨訂單。side: BUY / SELL，order_type: MARKET / LIMIT"""
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
    }
    if order_type == "LIMIT":
        if price is None:
            raise ValueError("限價單需要提供價格")
        params["price"] = price
        params["timeInForce"] = "GTC"

    if dry_run:
        return {"dry_run": True, "would_send": params}

    return signed_request("POST", "/api/v3/order", params)


def get_account_info():
    return signed_request("GET", "/api/v3/account")


def tradingview_widget_html(symbol: str, interval: str = "60", theme: str = "dark", height: int = 600) -> str:
    """組出 TradingView Advanced Chart 的內嵌 HTML（免費公開 widget，不需要 API 金鑰）"""
    tv_symbol = f"MEXC:{symbol}"
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
        f"🔍 搜尋{label}", key=f"{key_prefix}_search", placeholder="輸入關鍵字，例如 BTC 或 USDT"
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
        f"{label}（符合 {len(filtered)} 個）", filtered, index=idx, key=f"{key_prefix}_select"
    )


# ------------------------------------------------------------------
# 取得所有幣對清單
# ------------------------------------------------------------------
try:
    all_symbols = get_all_symbols()
except requests.exceptions.RequestException as e:
    st.error(f"無法取得幣對清單：{e}")
    all_symbols = ["BTCUSDT", "ETHUSDT"]

default_symbol = "BTCUSDT" if "BTCUSDT" in all_symbols else all_symbols[0]

tab_tv, tab_chart, tab_trade, tab_auto, tab_webhook, tab_account = st.tabs(
    ["📺 TradingView 圖表", "📈 K 線圖 (MEXC)", "🛒 手動下單", "🤖 簡易自動交易", "🔗 TradingView Webhook", "💰 帳戶資訊"]
)

# ------------------------------------------------------------------
# Tab 0：TradingView 圖表（免費 widget 內嵌）
# ------------------------------------------------------------------
with tab_tv:
    st.subheader("TradingView 圖表")
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
    st.info("提醒：TradingView 上的符號是 MEXC:幣對，若該幣對在 TradingView 上沒有對應資料，圖表可能顯示空白，可改用「K 線圖 (MEXC)」分頁改用 MEXC 原生資料。")

# ------------------------------------------------------------------
# Tab 1：K 線圖 (MEXC 原生資料)
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
                    data=[
                        go.Candlestick(
                            x=df["Date"], open=df["Open"], high=df["High"],
                            low=df["Low"], close=df["Close"],
                        )
                    ]
                )
                fig.update_layout(
                    xaxis_title="時間", yaxis_title="價格",
                    xaxis_rangeslider_visible=False,
                )
                st.plotly_chart(fig, use_container_width=True)
                st.session_state["last_df"] = df
                st.session_state["last_symbol"] = symbol
        except requests.exceptions.RequestException as e:
            st.error(f"連線 MEXC API 失敗：{e}")

# ------------------------------------------------------------------
# Tab 2：手動下單
# ------------------------------------------------------------------
with tab_trade:
    st.subheader("手動下單")
    trade_symbol = symbol_picker("幣對", "trade", all_symbols, default_symbol)
    order_type = st.selectbox("訂單類型", ["MARKET", "LIMIT"])
    side = st.radio("方向", ["BUY", "SELL"], horizontal=True)
    quantity = st.number_input("數量", min_value=0.0, step=0.0001, format="%.6f")
    price = None
    if order_type == "LIMIT":
        price = st.number_input("價格", min_value=0.0, step=0.01, format="%.2f")

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
            except (requests.exceptions.RequestException, ValueError) as e:
                st.error(f"下單失敗：{e}")

# ------------------------------------------------------------------
# Tab 3：簡易自動交易（SMA 交叉策略示範）
# ------------------------------------------------------------------
with tab_auto:
    st.subheader("簡易自動交易策略（SMA 均線交叉）")
    st.caption(
        "Streamlit 每次互動才會重新執行程式，並不適合當作 24 小時常駐的交易機器人。\n"
        "此頁籤示範「策略邏輯」，你可以按下方按鈕手動檢查一次訊號並（視模擬模式）下單；\n"
        "若要 24 小時自動運行，建議搭配右邊「TradingView Webhook」分頁的做法。"
    )

    auto_symbol = symbol_picker("幣對", "auto", all_symbols, default_symbol)
    auto_interval = st.selectbox("時間", ["1m", "5m", "15m", "1h"], key="auto_interval")
    fast_len = st.number_input("快線週期", min_value=2, max_value=200, value=9)
    slow_len = st.number_input("慢線週期", min_value=2, max_value=200, value=21)
    order_qty = st.number_input("每次下單數量", min_value=0.0, step=0.0001, format="%.6f", key="auto_qty")

    if st.button("檢查訊號並執行一次"):
        try:
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

                if signal is None:
                    st.info("目前沒有交叉訊號，不執行下單")
                else:
                    st.warning(f"偵測到訊號：{signal}")
                    if order_qty <= 0:
                        st.error("請設定大於 0 的下單數量")
                    else:
                        result = place_order(auto_symbol, signal, "MARKET", order_qty)
                        if dry_run:
                            st.info("🧪 模擬模式，實際會送出的參數如下：")
                            st.json(result["would_send"])
                        else:
                            st.success("訂單已送出")
                            st.json(result)
        except (requests.exceptions.RequestException, ValueError) as e:
            st.error(f"執行失敗：{e}")

# ------------------------------------------------------------------
# Tab 4：TradingView Webhook 說明
# ------------------------------------------------------------------
with tab_webhook:
    st.subheader("用 TradingView 警報自動下單")
    st.markdown(
        """
Streamlit 網頁本身只在使用者打開頁面、按按鈕時才會執行程式碼，**沒辦法常駐接收外部的 Webhook**。
要讓 TradingView 的警報（Alert）自動觸發 MEXC 下單，正確的架構是：

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
3. 伺服器收到請求後，會先驗證 `secret` 是否正確，再呼叫 MEXC API 下單，並回傳結果。

**安全提醒**
- 一定要設定 `secret` 並在伺服器端驗證，否則任何人只要知道網址就能幫你下單。
- 伺服器建議走 HTTPS，並限制只有 TradingView 的來源 IP 可以呼叫（TradingView 官方有公告固定 IP 清單，可自行查詢最新版本）。
- API Key 請只給「現貨交易」權限，不要給提現權限。
- 正式上線前，先用小額或模擬模式測試整個流程。

下方是可以直接部署的 `webhook_server.py`，與這支 `app.py` 放在同一個資料夾即可（它會共用同一組簽名邏輯）。
        """
    )

# ------------------------------------------------------------------
# Tab 5：帳戶資訊
# ------------------------------------------------------------------
with tab_account:
    st.subheader("帳戶餘額")
    if st.button("查詢帳戶資訊"):
        try:
            info = get_account_info()
            balances = [
                b for b in info.get("balances", [])
                if float(b["free"]) > 0 or float(b["locked"]) > 0
            ]
            if balances:
                st.dataframe(pd.DataFrame(balances))
            else:
                st.info("目前沒有可用餘額，或帳戶資訊為空")
        except (requests.exceptions.RequestException, ValueError) as e:
            st.error(f"查詢失敗：{e}")
