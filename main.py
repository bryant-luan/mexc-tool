from tools.mexc_executor import MEXCExecutor
from agents.mexc_agent_tool import MEXCTool

# 1. 初始化執行器
mexc_core = MEXCExecutor(api_key="你的KEY", api_secret="你的SECRET")

# 2. 將執行器掛載到 AI 工具介面上
mexc_tool = MEXCTool(mexc_core)

# 3. 把 mexc_tool 給你的 Agent 使用
# 接下來當 AI 判斷需要平倉時，它會呼叫: 
# mexc_tool.use("BATCH_PROFIT_TAKE")