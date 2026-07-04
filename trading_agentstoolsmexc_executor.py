# 檔案位置：trading_agents/tools/mexc_executor.py
import time
import hmac
import hashlib
import requests

class MEXCExecutor:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def execute_action(self, action_name, params=None):
        """AI 或 UI 統一呼叫入口"""
        if action_name == "BATCH_PROFIT_TAKE":
            return self._batch_profit_take(params)
        return {"success": False, "message": "無效指令"}

    def _batch_profit_take(self, params):
        # 這裡放入你之前寫好的「抓取持倉 > 判斷盈虧 > 發送市價平倉」邏輯
        # 確保此函數能被 Agent 自動觸發
        return {"success": True, "message": "批次平倉執行成功"}