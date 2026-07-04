# 檔案位置：trading_agents/agents/mexc_agent_tool.py
# 假設專案內定義了 BaseTool，若無，此結構可直接給 Agent 調用

class MEXCTool:
    def __init__(self, executor):
        self.executor = executor
        self.name = "MEXC_Manager"
        self.description = "當持倉獲利時或市場風險過高時，負責執行批次平倉的專業工具"

    def use(self, action, params=None):
        """AI Agent 透過此函數控制你的交易所帳戶"""
        return self.executor.execute_action(action, params)