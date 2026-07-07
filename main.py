import sys
import os

# 強制將當前路徑加入搜尋，這能解決所有 ModuleNotFoundError
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 現在再執行引用
from mexc_service import MEXCTradingService

print("成功找到 mexc_service！")
# 下面接你原本的程式邏輯...