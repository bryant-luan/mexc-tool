"""
notifier.py
簡單的 Telegram 通知模組，用於持倉變化時主動推播。
未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 時會自動略過，不影響主程式運作。
"""

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return  # 未設定通知，靜默略過

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except requests.RequestException as e:
        print(f"[通知失敗] {e}")
