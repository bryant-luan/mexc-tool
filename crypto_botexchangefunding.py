import os
import time
import sqlite3
import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional

class FundingScanner:
    """
    專業版資金費率監控中心 (Funding Rate Monitor)
    整合 MEXC 與 Gate.io 永續合約 API，支援過濾、排序、資料庫歷史紀錄與通知。
    """
    def __init__(self, db_path: str = "crypto_bot.db", tg_token: str = None, tg_chat_id: str = None):
        self.db_path = db_path
        self.tg_token = tg_token or os.getenv("TELEGRAM_TOKEN")
        self.tg_chat_id = tg_chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 資料庫，建立歷史紀錄表與自選股(Watch List)表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 歷史費率表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS funding_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    exchange TEXT,
                    symbol TEXT,
                    funding_rate REAL,
                    next_settle_time TEXT
                )
            """)
            # 自選股表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watch_list (
                    symbol TEXT PRIMARY KEY,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 警報冷卻紀錄表 (避免重複通知)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_cooldown (
                    key TEXT PRIMARY KEY,
                    last_alert_time REAL
                )
            """)
            conn.commit()

    def _fetch_mexc(self) -> List[Dict[str, Any]]:
        """從 MEXC 取得所有永續合約 Funding Rate"""
        result = []
        try:
            url = "https://contract.mexc.com/api/v1/contract/funding_rate"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and "data" in data:
                    # MEXC 格式: {symbol, fundingRate, nextSettleTime}
                    for item in data["data"]:
                        # 格式化 Symbol 名稱，例如 BTC_USDT
                        symbol = item["symbol"].replace("_", "") # 先變標準
                        if "USDT" in symbol:
                            formatted_symbol = symbol.replace("USDT", "_USDT")
                        else:
                            formatted_symbol = symbol

                        # 轉換時間戳為本地時間字串 (MEXC 通常是 timestamp 毫秒)
                        settle_time_raw = item.get("nextSettleTime", 0)
                        settle_time = datetime.fromtimestamp(settle_time_raw / 1000).strftime("%H:%M") if settle_time_raw else "--:--"

                        result.append({
                            "exchange": "MEXC",
                            "symbol": formatted_symbol,
                            "funding": float(item["fundingRate"]),
                            "next_funding": settle_time,
                            "status": "🔴" if float(item["fundingRate"]) < 0 else "🟢"
                        })
        except Exception as e:
            print(f"[Error] Fetching MEXC funding failed: {e}")
        return result

    def _fetch_gate(self) -> List[Dict[str, Any]]:
        """從 Gate.io 取得所有 USDT 永續合約 Funding Rate"""
        result = []
        try:
            url = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                contracts = response.json()
                for item in contracts:
                    # Gate.io 格式: {name: "BTC_USDT", funding_rate, ...}
                    funding_rate = float(item.get("funding_rate", 0))
                    
                    # 預估下次結算時間 (Gate 通常每 8 小時，固定或倒數，此處簡化為取間隔)
                    # 實務上可根據 server time 計算，這裡預設填入格式
                    result.append({
                        "exchange": "Gate",
                        "symbol": item["name"],
                        "funding": funding_rate,
                        "next_funding": "02:00", # 可優化為動取
                        "status": "🔴" if funding_rate < 0 else "🟢"
                    })
        except Exception as e:
            print(f"[Error] Fetching Gate.io funding failed: {e}")
        return result

    def get_all(self, save_to_db: bool = True) -> pd.DataFrame:
        """獲取所有交易所的最新 Funding Rate 並轉為 DataFrame"""
        mexc_data = self._fetch_mexc()
        gate_data = self._fetch_gate()
        all_data = mexc_data + gate_data
        
        df = pd.DataFrame(all_data)
        if df.empty:
            return pd.DataFrame(columns=["exchange", "symbol", "funding", "next_funding", "status"])
        
        if save_to_db:
            self._save_to_history(all_data)
            
        return df

    def _save_to_history(self, data: List[Dict[str, Any]]):
        """將每次掃描的數據寫入 SQLite 以供未來繪製 24H 趨勢圖"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            records = [
                (now, item["exchange"], item["symbol"], item["funding"], item["next_funding"])
                for item in data
            ]
            cursor.executemany("""
                INSERT INTO funding_history (timestamp, exchange, symbol, funding_rate, next_settle_time)
                VALUES (?, ?, ?, ?, ?)
            """, records)
            conn.commit()

    def get_filtered_df(self, search: str = "", only_negative: bool = False, threshold: Optional[float] = None, sort_by: str = "funding", ascending: bool = True) -> pd.DataFrame:
        """
        Dashboard 專用：提供搜尋、只看負值、自訂閾值過濾與排序功能
        """
        df = self.get_all(save_to_db=False) # 介面查詢不重複寫入 DB
        if df.empty:
            return df
            
        # 1. 搜尋過濾
        if search:
            df = df[df["symbol"].str.contains(search, case=False)]
            
        # 2. 只看負 Funding
        if only_negative:
            df = df[df["funding"] < 0]
            
        # 3. 自訂閾值過濾 (例如小於 -0.02%)
        if threshold is not None:
            df = df[df["funding"] <= threshold]
            
        # 4. 排序
        if sort_by in df.columns:
            df = df.sort_values(by=sort_by, ascending=ascending)
            
        return df.reset_index(drop=True)

    # =====================================================================
    # 🔔 通知系統 (Telegram)
    # =====================================================================
    def check_and_notify(self, threshold: float = -0.0003, cooldown_seconds: int = 3600):
        """
        後台守護進程(Scheduler)專用：檢查並發送 Telegram 警報，具備冷卻機制
        """
        df = self.get_all(save_to_db=True) # 定時任務觸發時寫入歷史紀錄
        target_df = df[df["funding"] <= threshold]
        
        current_time = time.time()
        
        for _, row in target_df.iterrows():
            alert_key = f"{row['exchange']}_{row['symbol']}_{threshold}"
            
            # 檢查冷卻時間
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT last_alert_time FROM alert_cooldown WHERE key = ?", (alert_key,))
                last_time = cursor.fetchone()
                
                if last_time and (current_time - last_time[0] < cooldown_seconds):
                    continue # 還在冷卻中，跳過
                    
                # 更新或插入冷卻時間
                cursor.execute("""
                    INSERT OR REPLACE INTO alert_cooldown (key, last_alert_time)
                    VALUES (?, ?)
                """, (alert_key, current_time))
                conn.commit()
            
            # 發送通知
            self._send_telegram_alert(row)

    def _send_telegram_alert(self, row: pd.Series):
        """執行 Telegram 訊息發送"""
        if not self.tg_token or not self.tg_chat_id:
            return
            
        message = (
            f"🚨 *Negative Funding Alert*\n\n"
            f"🔹 *Exchange:* {row['exchange']}\n"
            f"🔹 *Pair:* `{row['symbol']}`\n"
            f"🔹 *Funding:* `{row['funding'] * 100:.3f}%`\n"
            f"🔹 *Next Funding:* {row['next_funding']}\n"
            f"🕒 *Time:* {datetime.now().strftime('%H:%M:%S')}"
        )
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        try:
            requests.post(url, data={"chat_id": self.tg_chat_id, "text": message, "parse_mode": "Markdown"}, timeout=5)
        except Exception as e:
            print(f"[Error] Telegram send failed: {e}")

    # =====================================================================
    # 🌟 自選股功能 (Watch List)
    # =====================================================================
    def add_to_watch_list(self, symbol: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO watch_list (symbol) VALUES (?)", (symbol,))
            conn.commit()

    def get_watch_list(self) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM watch_list")
            return [row[0] for row in cursor.fetchall()]

    # =====================================================================
    # 🤖 AI Hook & 一鍵開倉介面 (保留給後續系統串接)
    # =====================================================================
    def get_ai_score(self, symbol: str, funding_rate: float) -> Dict[str, Any]:
        """
        AI 評分 Hook：後續可接入大模型或量化策略
        """
        # 這裡提供預設的基礎邏輯，極端費率給予高分
        confidence = 50
        action = "Hold"
        
        if funding_rate < -0.0010: # 小於 -0.1%
            action = "Long (Extreme Negative Funding)"
            confidence = 85
        elif funding_rate < -0.0003:
            action = "Long (Sentiment Panicked)"
            confidence = 65
            
        return {"action": action, "confidence": confidence}

    def execute_one_click_order(self, exchange: str, symbol: str, rate: float) -> Dict[str, Any]:
        """
        一鍵開倉 Hook：供 Dashboard 按鈕觸發，串接 RiskManager 執行實際落單
        """
        # 這裡回傳結構，供 app.py 判斷下一步
        return {
            "status": "pending_risk_check",
            "exchange": exchange,
            "symbol": symbol,
            "funding_rate": rate,
            "timestamp": time.time()
        }