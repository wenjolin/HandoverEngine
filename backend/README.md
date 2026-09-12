# 交接學習平台 — Backend

上傳專案 ZIP → LangGraph 產出課綱／測驗 → 網站依天學習（每日教材、每日查核、筆記 PDF、nano-graphrag 學習小助手）。

## 架構

```
backend/
  app/
    main.py                 # FastAPI 入口
    config.py               # Settings（.env）
    api/                    # HTTP：jobs（分析）、plans（學習）
    db/                     # SQLite jobs
    models/                 # enums、schemas
    pipeline/               # LangGraph 編排
      graph.py / runner.py / state.py / llm.py / prompts.py
      nodes/                # 流水線節點（ingest…package、validate）
      repair/               # 修復代理人：contract / permissions / agent
      extract_support/      # extract 輔助：merge、coverage、file_groups、importance
    services/
      indexing/             # chunking、chroma、embeddings
      learning/             # store、quiz、pdf、assistant、nano patch
      rate_limit.py / secrets_filter.py / unzip_safe.py
    static/                 # 前端
  tests/
  data/                     # 執行時（gitignore）
```

**兩條主線**

| 線 | 入口 | 職責 |
|----|------|------|
| Job | `POST /api/jobs` | ZIP → pipeline → artifacts／ZIP／PDF |
| Plan | `/api/plans/{id}/…` | 課綱／每日／測驗／缺口／小助手／筆記 PDF |

### Pipeline（主幹，擋 Job 完成）

```
ingest → index → extract → check_coverage
         ↓（覆蓋不足，最多 1 次）
      extract_gap → 再 check_coverage
         ↓
handover_gaps → outline → day_writer → quiz_smith → validate
                                    ↓（未過）
                                 repair → validate
                                    ↓（通過）
                          render → export_pdf → package
```

| 節點 | 說明 |
|------|------|
| ingest | 安全解壓 ZIP → `raw/` |
| index | Chunk + embedding → Chroma |
| extract | 多 pass 抽知識卡；小模組批次合併 pass1 |
| check_coverage / extract_gap | 覆蓋率檢查與補洞 |
| handover_gaps | 文件／卡片矛盾缺口（LLM） |
| outline | 學習計畫（LLM，`PLAN_SYSTEM`） |
| day_writer | **按天並行 LLM**（最多 3 workers，`DAY_WRITER_SYSTEM`）；失敗／過薄則規則 fallback |
| quiz_smith | 每日查核／交接期中查核／上手驗收（LLM，`QUIZ_SMITH_SYSTEM`）；題數不足再 pad |
| validate / repair | 契約驗收；未過則 Planner→Worker→Critic |
| render → export_pdf → package | 架構圖、PDF、ZIP |

System prompt 集中在 `app/pipeline/prompts.py`（請直接改該檔，勿另開平行常數名）。

### Job 完成後（背景，不擋學習）

`runner.py` 在 `mark_done` 後背景預建小助手索引（失敗不擋；首問仍可補建）。

### 學習 SSOT

`work_dir/artifacts/`：`learning_plan.json`、`days/{n}.json`、`quiz_bank.json`、`progress.json`、`handover_gaps.json`、`cards.json` 等。

## 環境

- Python **3.11+**，請用 `backend/.venv`（勿污染本機全域）
- Chat：OpenAI 相容 API（OpenRouter，`qwen/qwen3-235b-a22b-2507`）
- Embedding：`fake`／`local`（BGE）／`openai`（可走 OpenRouter，與 chat 金鑰分開）
- PDF：`fpdf2` + 系統中文字型（優先微軟正黑／雅黑；可用 `HANDOVER_PDF_FONT`。勿用標楷體 kaiu）
- 小助手：可選 `[assistant]`（nano-graphrag）；Python 3.14 見下方備註

## 安裝

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,embed,assistant]"
copy .env.example .env
```

Python **3.14**（graspologic／gensim 可能裝不起）：

```powershell
pip install -e ".[dev,embed]"
pip install nano-graphrag --no-deps
pip install neo4j nano-vectordb hnswlib future tenacity networkx numpy
```

`services.learning.nano_graphrag_patch` 以 networkx Louvain 取代 Leiden，無需 graspologic。

`.env` 重點：

```text
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=qwen/qwen3-235b-a22b-2507
EMBEDDING_BACKEND=openai
EMBEDDING_MODEL=liquid/lfm-2.5-embedding-350m:free
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
USE_FAKE_LLM=false
```

- 測試／離線：`USE_FAKE_LLM=true` 且 `EMBEDDING_BACKEND=fake`
- OpenRouter free embedding 需在帳號 Privacy 允許 free 端點

## 啟動

```powershell
cd D:\WenH100\Codebase\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 前端：http://127.0.0.1:8000/
- Swagger：http://127.0.0.1:8000/docs
- Health：http://127.0.0.1:8000/health

若出現 `Failed to fetch` 或埠綁定失敗（WinError 10048），多半是舊 uvicorn 佔住 8000：結束相關 python 行程後重開，或改用其他 port（例如 `--port 8001`）。

## API 速查

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/jobs `
  -Form @{ file = Get-Item .\project.zip; days = "5" }
$jobId = $r.job_id
Invoke-RestMethod http://127.0.0.1:8000/api/jobs/$jobId
Invoke-RestMethod http://127.0.0.1:8000/api/plans/$jobId
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/plans/$jobId/assistant" `
  -ContentType "application/json" `
  -Body '{"question":"這個專案怎麼啟動？","day":1}'
Invoke-WebRequest http://127.0.0.1:8000/api/plans/$jobId/days/1/notes.pdf -OutFile day1-notes.pdf
Invoke-WebRequest http://127.0.0.1:8000/api/jobs/$jobId/download -OutFile handover-pack.zip
Invoke-WebRequest http://127.0.0.1:8000/api/jobs/$jobId/download/pdf -OutFile handover-pack.pdf
```

小助手：nano-graphrag **local**；同 plan process 內快取；`top_k=5`、corpus 約 24 檔／6 萬字。**Job 完成後背景預建索引**；失敗不擋 Job，首問可補建。偏慢多半是 embedding／chat API 延遲。

## 測試

```powershell
$env:USE_FAKE_LLM="true"
$env:EMBEDDING_BACKEND="fake"
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

這是本專案的離線回歸基準：會完整跑 ingest 至 package 的 pipeline 與 API 測試，不會呼叫外部 LLM 或 embedding API。2026-09-12 的基準結果為 `63 passed, 1 deselected`；被排除的本機 BGE 測試需要先下載模型。

## 產出

- 網站：課程卡片、每日教材／每日查核、交接期中查核、上手驗收、交接缺口、側欄進度、學習小助手
- ZIP：markdown、cards、days JSON、每日 `*-notes.pdf`、總包 PDF、diagrams
