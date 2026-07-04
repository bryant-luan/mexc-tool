Vedanta/
│
├── vedanta/                     # 專案核心演算法與 AI 決策層
│   ├── agents/                  # LLM 決策 Agent
│   └── predictors/              # 價格預測模組
│
├── extensions/                  # 💡 新增：外部擴充與 UI 介面
│   └── mexc_terminal/           
│       ├── __init__.py
│       ├── core.py              # 💡 存放 MEXC 安全簽章、下單與真實持倉 API
│       └── app.py               # 💡 你的 Streamlit 智慧互動面板
│
└── requirements.txt             # 記得加上 streamlit, requests, pandas