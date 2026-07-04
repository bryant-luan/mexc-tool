# 確保 main.py 內容簡潔且正確引用
from mexc_service import MEXCTradingService
from mexc_executor import MEXCExecutor

# 初始化你的工具
service = MEXCTradingService(api_key="...", api_secret="...")
executor = MEXCExecutor(service)

# 開始你的自動化邏輯
if __name__ == "__main__":
    print("系統已啟動，準備進行監控與交易...")
