# main.py 的最後整合建議
from mexc_service import MEXCTradingService
from mexc_executor import MEXCExecutor

# 初始化你的服務
# 建議將 API KEY 放入 .env 檔案中，不要直接寫死在程式碼裡
mexc_service = MEXCTradingService(api_key="你的KEY", api_secret="你的SECRET")
executor = MEXCExecutor(mexc_service)

def run_automation():
    # 這裡就是你的整合點
    # 讓 AI 或程式自動檢查持倉並觸發 executor 的邏輯
    positions = mexc_service.get_portfolio_status()
    executor.check_and_execute(positions)

if __name__ == "__main__":
    run_automation()
