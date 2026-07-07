"""
position_poller.py — 持倉輪詢服務（背景常駐版）

同時監控：
- Gate.io 合約 (Futures)：exchange.gate_futures.GateFuturesExchange
- Gate.io 現貨 (Spot) 錢包餘額：exchange.gate_spot.GateSpotExchange
- MEXC 合約 (Futures)：exchange.mexc_futures.MEXCFuturesExchange

三者都繼承同一套 BaseExchange 介面，get_positions() 回傳格式已對齊，
所以可以共用同一套「變化偵測」邏輯（開倉/平倉/餘額變化都會記錄+通知）。

執行方式：
    python position_poller.py

想加 MEXC 現貨？MEXC 現貨走 ccxt（exchange/mexc.py），本檔案沒有內建，
因為現貨沒有「持倉」概念、通常直接看帳戶餘額就好；如果你要，跟我說一聲即可加上。
"""

import time
import logging

from config import (
    API_KEY, API_SECRET, TESTNET,
    MEXC_API_KEY, MEXC_API_SECRET,
    GATE_FUTURES_SYMBOLS, POLL_INTERVAL,
)
from exchange.base import ExchangeException
from exchange.gate_futures import GateFuturesExchange
from exchange.gate_spot import GateSpotExchange
from exchange.mexc_futures import MEXCFuturesExchange
from notifier import send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("position_poller")

EXCHANGES = {}

if API_KEY and API_SECRET:
    EXCHANGES["Gate-Futures"] = GateFuturesExchange(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)
    EXCHANGES["Gate-Spot"] = GateSpotExchange(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)
else:
    log.warning("未設定 GATE_API_KEY / GATE_API_SECRET，略過 Gate.io 監控")

if MEXC_API_KEY and MEXC_API_SECRET:
    EXCHANGES["MEXC-Futures"] = MEXCFuturesExchange(api_key=MEXC_API_KEY, api_secret=MEXC_API_SECRET)
else:
    log.warning("未設定 MEXC_API_KEY / MEXC_API_SECRET，略過 MEXC 合約監控")

# {exchange_name: {symbol: last_size}}
last_sizes: dict[str, dict[str, float]] = {name: {} for name in EXCHANGES}


def format_position(exchange_name: str, p: dict) -> str:
    if p["side"] == "spot":
        return f"[{exchange_name}] {p['symbol']} | 現貨餘額 | 數量={p['size']:.8f}"
    return (f"[{exchange_name}] {p['symbol']} | "
            f"{'多單' if p['side'] == 'long' else '空單'} | "
            f"數量={p['size']} | 進場價={p['entry_price']} "
            f"| 槓桿={p['leverage']} | 未實現盈虧={p['unrealised_pnl']}")


def check_positions(exchange_name: str, exchange) -> None:
    try:
        positions = exchange.get_positions()
    except ExchangeException as e:
        log.error(f"[{exchange_name}] 查詢持倉失敗: {e}")
        return

    current = {p["symbol"]: p for p in positions}
    prev_sizes = last_sizes[exchange_name]

    # 檢查現有/新增倉位或餘額變化
    for symbol, p in current.items():
        size = p["size"]
        prev_size = prev_sizes.get(symbol, 0)
        if size != prev_size:
            msg = format_position(exchange_name, p)
            log.info(f"[持倉變化] {msg}")
            if prev_size == 0:
                send_telegram(f"🟢 新增 {msg}")
            else:
                send_telegram(f"🔄 變化 {msg}")
            prev_sizes[symbol] = size

    # 檢查已消失的部位（合約平倉 / 現貨餘額歸零）
    for symbol in list(prev_sizes.keys()):
        if symbol not in current and prev_sizes[symbol] != 0:
            log.info(f"[持倉變化] [{exchange_name}] {symbol} 已歸零/平倉")
            send_telegram(f"🔴 歸零/平倉 [{exchange_name}] {symbol}")
            prev_sizes[symbol] = 0


def main() -> None:
    if not EXCHANGES:
        log.error("沒有任何交易所設定金鑰，請先編輯 .env。程式結束。")
        return

    for name, exchange in EXCHANGES.items():
        ok = exchange.ping()
        log.info(f"{name} 連線狀態: {'正常' if ok else '異常'}")

    log.info(f"開始輪詢，Gate 合約清單: {', '.join(GATE_FUTURES_SYMBOLS)}　|　其餘監控帳戶內所有非零持倉/餘額")
    log.info(f"輪詢間隔 {POLL_INTERVAL} 秒")

    while True:
        for name, exchange in EXCHANGES.items():
            check_positions(name, exchange)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("已手動停止輪詢服務")
    finally:
        for exchange in EXCHANGES.values():
            exchange.close()
