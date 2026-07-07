"""
gate_poll.py — Gate.io USDT 合約持倉輪詢工具

功能：
1. 支援多合約同時輪詢（在 .env 的 GATE_CONTRACTS 設定，逗號分隔）
2. 偵測持倉變化（開倉／平倉／加減倉）時印出並可推播 Telegram 通知
3. 具備錯誤處理與重試，不會因單次 API 失敗而整支程式當掉
4. 詳細日誌輸出，方便除錯

執行方式：
    python gate_poll.py
"""

import time
import logging
from datetime import datetime

from config import CONTRACTS, POLL_INTERVAL
from gate_client import GateClient
from notifier import send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gate_poll")

client = GateClient()

# 記錄上一次的持倉大小，用來比對是否有變化：{contract: size}
last_sizes: dict[str, float] = {}


def format_position(p: dict) -> str:
    contract = p.get("contract", "?")
    size = p.get("size", 0)
    entry_price = p.get("entry_price", "-")
    unrealised_pnl = p.get("unrealised_pnl", "-")
    leverage = p.get("leverage", "-")
    side = "多單" if float(size) > 0 else "空單" if float(size) < 0 else "無倉位"
    return (f"{contract} | {side} | 數量={size} | 進場價={entry_price} "
            f"| 槓桿={leverage} | 未實現盈虧={unrealised_pnl}")


def check_position(contract: str) -> None:
    try:
        pos = client.get_position(contract)
    except Exception as e:
        log.error(f"查詢 {contract} 持倉失敗: {e}")
        return

    size = float(pos.get("size", 0))
    prev_size = last_sizes.get(contract, 0)

    if size != prev_size:
        msg = f"[持倉變化] {format_position(pos)}"
        log.info(msg)
        if prev_size == 0 and size != 0:
            send_telegram(f"🟢 開倉 {msg}")
        elif prev_size != 0 and size == 0:
            send_telegram(f"🔴 平倉 {contract}")
        else:
            send_telegram(f"🔄 倉位變化 {msg}")
        last_sizes[contract] = size
    else:
        log.debug(f"{contract} 持倉無變化（數量={size}）")


def main() -> None:
    log.info(f"開始輪詢合約：{', '.join(CONTRACTS)}，間隔 {POLL_INTERVAL} 秒")
    while True:
        for contract in CONTRACTS:
            check_position(contract)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("已手動停止輪詢程式")
