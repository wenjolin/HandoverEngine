# 接棒引擎｜Handover Engine

接棒引擎會分析既有專案的 ZIP，產出可執行的交接學習計畫、每日教材、測驗、交接缺口與可下載的交接包，協助接任者快速掌握專案。

## 功能

- 上傳專案 ZIP，安全解壓並排除虛擬環境、相依套件與機密檔案。
- 產生多日交接課綱、每日教材、來源檔案連結與每日筆記 PDF。
- 每日查核必須 **100 分** 才算通過；期中查核與上手驗收會記錄通過／未通過狀態。
- 題目選項會穩定分散正解位置；通過後再次開啟測驗只顯示題目、正確答案與解析。
- 偵測文件覆蓋不足、結構缺漏與矛盾；可手動新增交接缺口。
- 交接缺口提供未解決／確認中／已解決三欄看板，拖曳卡片即可保存狀態。
- 可下載完整交接 ZIP、教材 PDF、每日筆記 PDF 與缺口問題清單 PDF。
- 內建根據專案內容回答問題的學習小助手。

## 架構

```text
瀏覽器（內建靜態前端）
        │
        ▼
FastAPI：Jobs / Plans API
        │
        ├─ SQLite：Job 與執行狀態
        ├─ artifacts：教材、測驗、進度、缺口、PDF、ZIP
        └─ LangGraph Pipeline
             ingest → index → extract → coverage → gaps
                    → outline → daily materials → quizzes
                    → validate / repair → PDF / package
```

前端由 FastAPI 在同一個服務內提供，不需要另外啟動 Node.js 或前端開發伺服器。

## 專案結構

```text
project-root/
├── README.md
├── backend/
│   ├── app/
│   │   ├── api/              # Jobs、學習計畫、測驗、缺口、小助手 API
│   │   ├── pipeline/         # LangGraph 分析與教材產生流程
│   │   ├── services/         # 解壓、索引、PDF、測驗、儲存與安全處理
│   │   ├── static/           # 網頁前端（HTML / CSS / JS）
│   │   ├── models/           # Pydantic schema 與列舉
│   │   └── db/               # SQLite Job repository
│   ├── tests/
│   ├── .env.example
│   └── pyproject.toml
└── backend/data/             # 執行時資料；不納入 Git
```

## 環境需求

- Python 3.11 或以上版本
- macOS、Windows 或 Linux
- 線上模式需要 OpenAI 相容 API 金鑰；fake 模式不需要金鑰
- PDF 匯出需要可用中文字型；macOS 通常可使用系統字型

## 安裝

macOS／zsh：

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,embed,assistant]"
cp .env.example .env
```

Windows PowerShell：

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,embed,assistant]"
Copy-Item .env.example .env
```

若只需要最小依賴，可安裝 `.[dev]`；本機 embedding 與學習小助手的延伸能力將無法使用或會降級。

## 設定 `.env`

從 `backend/.env.example` 複製設定檔，**不要提交真實金鑰**。

線上模式範例：

```dotenv
OPENAI_API_KEY=你的金鑰
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-mini

EMBEDDING_BACKEND=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=你的_embedding_金鑰
EMBEDDING_BASE_URL=https://api.openai.com/v1

USE_FAKE_LLM=false
```

`OPENAI_BASE_URL` 與 embedding 的 base URL 可指向 OpenAI 相容服務；embedding 金鑰未設定時會回退使用 `OPENAI_*`。

離線／驗證模式：

```dotenv
USE_FAKE_LLM=true
EMBEDDING_BACKEND=fake
```

## 啟動

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 網頁：<http://127.0.0.1:8000/>
- 健康檢查：<http://127.0.0.1:8000/health>

公開介面不提供 Swagger 文件連結。若 8000 埠已被占用，可改用 `--port 8001`。

以上預設讀取 `.env` 中的線上 chat 與 embedding API 設定。僅在離線驗證時才於指令前加上：

```bash
USE_FAKE_LLM=true EMBEDDING_BACKEND=fake
```

## 使用流程

1. 在交接首頁上傳專案 ZIP，選擇預計交接天數。
2. 等待分析完成後，從「每日任務」依序閱讀教材並完成每日查核。
3. 每日查核須全對才標示「已通過」；通過後測驗改為唯讀答案複習。
4. 進度達門檻後可進行交接期中查核；所有每日查核通過後可進行上手驗收。
5. 在「交接缺口」拖曳卡片管理未解決／確認中／已解決事項。
6. 使用選取模式，將跨欄選取的缺口依狀態分段匯出 PDF。
7. 下載交接 ZIP 或整份 PDF 保存與交接。

## Pipeline 與產出

```text
ingest → index → extract → coverage check
                         └→ coverage repair（必要時）
      → handover gaps → outline → day writer → quiz smith
      → validate / repair → diagrams → PDF → package
```

完成的 Job 會在 `backend/data/jobs/<job-id>/artifacts/` 建立：

- `learning_plan.json`：多日學習計畫
- `days/<n>.json`：每日教材
- `quiz_bank.json`：每日、期中與上手驗收題庫
- `progress.json`：閱讀、通過與測驗嘗試狀態
- `handover_gaps.json`：交接缺口與三欄狀態
- `handover-pack.pdf`、`handover-pack.zip`：完整交接包

## API 摘要

| 用途 | 方法與路徑 |
| --- | --- |
| 建立分析 Job | `POST /api/jobs` |
| 取得 Job 狀態 | `GET /api/jobs/{job_id}` |
| 下載交接 ZIP／PDF | `GET /api/jobs/{job_id}/download`、`/download/pdf` |
| 讀取學習計畫與每日教材 | `GET /api/plans/{plan_id}`、`/days/{day}` |
| 讀取／提交測驗 | `GET /api/plans/{plan_id}/quizzes/...`、`POST /quizzes/submit` |
| 管理缺口 | `GET/POST /api/plans/{plan_id}/gaps`、`PATCH /gaps/{gap_id}` |
| 匯出缺口 PDF | `GET /api/plans/{plan_id}/gaps/export/pdf` |
| 詢問學習小助手 | `POST /api/plans/{plan_id}/assistant` |

## 測試

在 `backend/` 下執行離線完整回歸：

```bash
USE_FAKE_LLM=true EMBEDDING_BACKEND=fake .venv/bin/python -m pytest -q
```

本機 BGE embedding 測試預設略過，避免測試期間下載模型。若已準備模型且要測試它：

```bash
RUN_LOCAL_EMBED_TESTS=1 .venv/bin/python -m pytest tests/test_local_embed.py -q
```

## 安全與資料處理

- 僅接受 ZIP 上傳，並限制解壓縮檔案數、檔案大小與總大小。
- 會排除 `.git`、`node_modules`、`dist`、`build`、`.venv`、`venv`、`env`、快取與機密檔案。
- `.env`、虛擬環境、執行期資料與上傳檔均由 `.gitignore` 排除。
- 若 API 金鑰曾出現在公開訊息、文件或 Git 歷史，請立即撤銷並更換。

## 疑難排解

| 現象 | 處理方式 |
| --- | --- |
| `segmentation fault` 或 Python 啟動異常 | 刪除 `backend/.venv`，以 Python 3.11 重新建立虛擬環境並安裝依賴。 |
| `Failed to fetch` | 確認 uvicorn 正在執行、網址與埠號正確。 |
| embedding 請求超過 token 上限 | 使用最新版程式；embedding 已採分批處理。 |
| PDF 中文亂碼或重疊 | 確認系統中文字型可用；可設定 `HANDOVER_PDF_FONT` 指向可用 TTF/TTC 字型。 |
| 本機 BGE 測試失敗 | 先下載模型並設定 `RUN_LOCAL_EMBED_TESTS=1`，否則維持預設略過。 |
