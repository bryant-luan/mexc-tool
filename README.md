# mexc-tool — 多交易所現貨/合約下單 + 持倉監控

## 這次更新做了什麼

你原本部署在 Streamlit 上的 `app.py` 會直接崩潰（`IndentationError`），原因是檔案裡累積了大量重複貼上的區塊（重複的 Tab 定義註解、重複的 `gate_signed_request()`、壞掉縮排的 `LocalFundingScanner`）。這次整理：

**移除**
- `LocalFundingScanner`：縮排壞掉導致崩潰，邏輯也粗糙，改用更穩定的寫法重做
- `Vedanta` / `PanWatch` 分頁：純裝飾用的假數據（`np.random` 產生的「風控評級」），沒有真實功能，先拿掉。如果之後想做真的，跟我說
- 重複定義的 `gate_signed_request()`、重複的 Tab 定義註解區塊

**新增**
- `exchange/gate_futures.py`、`exchange/gate_spot.py`、`exchange/mexc_futures.py`：三個交易所類別都繼承同一套 `BaseExchange` 介面（全部交易所都補上合約）
- `app.py` 新分頁「📊 持倉監控（全交易所）」：一次查 Gate.io 現貨/合約 + MEXC 現貨/合約
- `position_poller.py`：背景常駐程式，同時輪詢 Gate 現貨/合約 + MEXC 合約，變化時 Telegram 通知

## 檔案結構

```
mexc-tool/
├── app.py                     # Streamlit 網頁（手動下單、K線、持倉監控...）
├── position_poller.py         # 背景輪詢程式（24小時跑，搭配 Telegram 通知）
├── notifier.py                 # Telegram 通知模組
├── config.py                    # 環境變數設定
├── exchange/
│   ├── base.py                 # BaseExchange 抽象介面（原有，未修改）
│   ├── mexc.py                  # MEXC 現貨（原有，用 ccxt）
│   ├── gate_base.py             # Gate.io 簽名共用邏輯
│   ├── gate_futures.py          # Gate.io 合約
│   ├── gate_spot.py             # Gate.io 現貨
│   └── mexc_futures.py          # MEXC 合約 ★這次新增，補齊「全部交易所都有合約」
├── .env.example
├── .gitignore
└── requirements.txt
```

## 安裝

```bash
pip install -r requirements.txt
cp .env.example .env
```

編輯 `.env`，Gate.io 和 MEXC 的金鑰都可以只填一邊，程式會自動略過沒填的交易所：

```
GATE_API_KEY=你的Key
GATE_API_SECRET=你的Secret
MEXC_API_KEY=你的Key
MEXC_API_SECRET=你的Secret
```

**建立 API Key 時務必只開「唯讀」或「交易」權限，不要開提現權限。**

## 執行

**網頁版（手動操作、看盤、下單）**
```bash
streamlit run app.py
```

**背景版（24 小時自動輪詢 + Telegram 通知）**
```bash
python position_poller.py
```

兩個可以同時跑，互不影響——`app.py` 給你手動查看/下單，`position_poller.py` 負責背景默默盯著、有變化才通知你。

## MEXC 合約要注意的地方

MEXC 合約下單 API（`/private/order/submit`）比 Gate.io 複雜一些，`exchange/mexc_futures.py` 裡的 `place_market_order` / `place_limit_order` 先實作了「開倉」的基本版本（`side` 用 1=開多、3=開空），**平倉、調整槓桿等功能還沒做**。查詢持倉（`get_positions`）已經可以正常用。正式下單前務必先用小額測試。

## 上傳 GitHub 前確認

- [ ] `.env`、`.streamlit/secrets.toml` 都沒有被加入 git（`.gitignore` 已排除）
- [ ] 程式碼裡沒有寫死任何 API Key / Secret
- [ ] 若曾經誤將金鑰上傳過，立即到交易所後台刪除該組 API Key 並重新產生

## 待確認/可延伸的方向

- [ ] MEXC 合約下單目前只支援開倉，平倉/調整槓桿需要再擴充
- [ ] MEXC 現貨在「持倉監控」分頁只顯示餘額（現貨沒有槓桿/方向的概念）
- [ ] `position_poller.py` 目前沒有監控 MEXC 現貨餘額變化（現貨通常波動較小，先略過；需要的話可以加）
- [ ] `app.py` 的「持倉監控」分頁如果要自動刷新，需要額外安裝 `streamlit-autorefresh`（已寫進 requirements.txt）
