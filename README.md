# mexc-tool — Gate.io 合約持倉輪詢工具

一個輕量的 Python 工具，定時輪詢 Gate.io USDT 永續合約持倉，偵測變化並可選擇性透過 Telegram 通知。

## 功能特色

- ✅ 正確處理 Gate.io v4 API 所需的 HMAC-SHA512 簽名驗證
- ✅ 支援多合約同時輪詢
- ✅ 偵測開倉 / 平倉 / 加減倉並記錄日誌
- ✅ 選填 Telegram 即時推播
- ✅ API Key 透過 `.env` 管理，不會寫死在程式碼或上傳到 GitHub

## 檔案結構

```
mexc-tool/
├── gate_client.py    # Gate.io API 客戶端（簽名、查倉、下單）
├── gate_poll.py       # 主輪詢程式
├── notifier.py        # Telegram 通知模組
├── config.py          # 設定讀取
├── .env.example       # 環境變數範例
├── .gitignore
├── requirements.txt
└── README.md
```

## 安裝

```bash
git clone https://github.com/bryant-luan/mexc-tool.git
cd mexc-tool
pip install -r requirements.txt
cp .env.example .env
```

接著編輯 `.env`，填入你的 Gate.io API Key / Secret（可於 Gate.io 後台「API 管理」建立，**建議只開啟「唯讀」或「合約交易」權限，不要開啟提幣權限**）。

## 執行

```bash
python gate_poll.py
```

執行後會持續印出目前持倉狀態，並在持倉變化時顯示：

```
2026-07-05 14:32:10 [INFO] [持倉變化] BTC_USDT | 多單 | 數量=10 | 進場價=65000 | 槓桿=10 | 未實現盈虧=120.5
```

## 上傳到 GitHub 前請務必確認

- [ ] `.env` 檔**沒有**被加入 git（`.gitignore` 已預先排除）
- [ ] 程式碼裡沒有寫死任何 API Key / Secret
- [ ] 若曾經誤將金鑰上傳過，請立即到 Gate.io 後台**刪除該組 API Key** 並重新產生

上傳指令：

```bash
git init
git add .
git commit -m "Initial commit: Gate.io position poller"
git branch -M main
git remote add origin https://github.com/bryant-luan/mexc-tool.git
git push -u origin main
```

## 風險提示

本工具僅供技術參考，涉及真實資金操作（尤其是 `place_order` 下單功能）請務必先在小額或測試環境驗證，作者不對任何交易損失負責。
