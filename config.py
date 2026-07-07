"""
config.py
所有機密設定改由環境變數 / .env 檔讀取，避免 API Key 直接寫死在程式碼裡
（原截圖中的寫法一旦上傳 GitHub，金鑰就會外洩，這裡一併修正）。

使用方式：
1. 複製 .env.example 為 .env
2. 填入你的 Gate.io API Key / Secret
3. 程式會自動讀取
"""

import os
from dotenv import load_dotenv

load_dotenv()  # 讀取同目錄下的 .env 檔

API_KEY = os.getenv("GATE_API_KEY", "")
API_SECRET = os.getenv("GATE_API_SECRET", "")
TESTNET = os.getenv("GATE_TESTNET", "false").lower() == "true"

MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

# 要輪詢的「合約」清單（Futures），逗號分隔，統一用 "BTC/USDT" 格式
GATE_FUTURES_SYMBOLS = [s.strip() for s in os.getenv("GATE_FUTURES_SYMBOLS", "BTC/USDT").split(",") if s.strip()]

# 要輪詢的「現貨」清單（Spot，用來監控錢包餘額變化），逗號分隔
# 若不確定要填什麼，可以先不設定，程式會自動監控帳戶內所有非零餘額的幣種
GATE_SPOT_SYMBOLS = [s.strip() for s in os.getenv("GATE_SPOT_SYMBOLS", "").split(",") if s.strip()]

# 輪詢間隔（秒）
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# Telegram 通知（選填，留空則不啟用通知）
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not (API_KEY and API_SECRET) and not (MEXC_API_KEY and MEXC_API_SECRET):
    print("⚠️  尚未設定任何交易所金鑰，請先建立 .env 檔（可參考 .env.example）")
