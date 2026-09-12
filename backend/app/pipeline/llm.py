"""LLM clients: protocol, Fake (tests), OpenAI-compatible (production)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: type) -> Any: ...


def parse_llm_json(text: str) -> Any:
    """Parse model output that should be JSON (fences / trailing commas tolerated)."""
    raw = (text or "").strip()
    if not raw:
        return {}

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)

    candidates = [raw]
    obj_start, obj_end = raw.find("{"), raw.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        candidates.append(raw[obj_start : obj_end + 1])
    arr_start, arr_end = raw.find("["), raw.rfind("]")
    if arr_start >= 0 and arr_end > arr_start:
        candidates.append(raw[arr_start : arr_end + 1])

    last_err: Exception | None = None
    seen: set[str] = set()
    for cand in candidates:
        for variant in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            if variant in seen:
                continue
            seen.add(variant)
            try:
                return json.loads(variant)
            except json.JSONDecodeError as exc:
                last_err = exc
    assert last_err is not None
    raise last_err


def _card(
    *,
    id: str,
    title: str,
    category: str,
    path: str,
    chunk_id: str | None = None,
    importance: str = "medium",
) -> dict:
    return {
        "id": id,
        "title": title,
        "category": category,
        "summary": title,
        "details": f"{title}（FakeLLM）",
        "symbol": None,
        "citations": [
            {
                "chunk_id": chunk_id or f"{path}::0",
                "path": path,
                "start_line": 1,
                "end_line": 5,
            }
        ],
        "importance": importance,
        "needs_review": False,
    }


def _mcq(qid: str, stem: str, path: str = "README.md") -> dict:
    return {
        "id": qid,
        "type": "mcq",
        "stem": stem,
        "choices": ["正確敘述", "錯誤 A", "錯誤 B", "錯誤 C"],
        "answer": "正確敘述",
        "explanation": "FakeLLM",
        "citations": [{"path": path}],
    }


class FakeLLMClient:
    def complete_json(self, system: str, user: str, schema: type) -> Any:
        blob = system + user
        days = 7
        m = re.search(r"days?\s*=\s*(\d+)", user, re.I)
        if m:
            days = int(m.group(1))

        # Must be before「每日」等關鍵字分支（planner prompt 也可能含那些字）
        if "課綱修復規劃師" in blob or "課綱修復代理人" in blob:
            last = "none"
            m_last = re.search(r"last_worker_tool=(\w+)", user)
            if m_last:
                last = m_last.group(1)
            if last in {
                "rewrite_days",
                "top_up_quizzes",
                "search_chunks",
                "list_issues",
            }:
                return {"tool": "stop_planning", "args": {}}
            if "missing_day_package" in user:
                days_found = [int(x) for x in re.findall(r'"day":\s*(\d+)', user)]
                return {"tool": "rewrite_days", "args": {"days": days_found or [1]}}
            if any(
                c in user
                for c in ("day_quiz_short", "midterm_short", "final_short")
            ):
                return {"tool": "top_up_quizzes", "args": {}}
            return {"tool": "stop_planning", "args": {}}

        if "交接缺漏" in blob or "文件矛盾" in blob:
            return {
                "gaps": [
                    {
                        "title": "啟動方式描述含糊",
                        "detail": "README 與知識卡對啟動指令說法不一致（FakeLLM）。",
                        "severity": "medium",
                        "sources": ["README.md"],
                        "question": "正式啟動指令到底是哪一個？開發與正式環境是否不同？",
                    }
                ]
            }

        if "出題" in blob or "每日查核" in blob or "day_quizzes" in blob:
            day_quizzes = {
                str(i): [_mcq(f"d{i}-q{j}", f"Day{i} 題目 {j}") for j in range(1, 4)]
                for i in range(1, days + 1)
            }
            return {"day_quizzes": day_quizzes}

        m_day = re.search(r"只寫第\s*(\d+)\s*天", user)
        if m_day or "單日交接" in blob:
            i = int(m_day.group(1)) if m_day else 1
            return {
                "day": i,
                "theme": f"第 {i} 天",
                "blocks": [
                    {
                        "type": "goal",
                        "title": "今日目標",
                        "body": (
                            f"- 能說明第 {i} 天主題在專案中的位置\n"
                            f"- 能說出今日必讀檔的主要職責\n"
                            f"- 能指出至少一個相關入口或函式"
                        ),
                        "paths": [],
                    },
                    {
                        "type": "note",
                        "title": "今日架構／脈絡",
                        "body": (
                            f"第 {i} 天聚焦交接主題。先建立模組心智模型："
                            "從入口或 README 理解系統邊界，再對照必讀檔案的職責與呼叫關係。"
                        ),
                        "paths": [],
                    },
                    {
                        "type": "reading",
                        "title": "檔案導覽",
                        "body": (
                            "### `README.md`\n"
                            "- 職責：說明專案目的、安裝與啟動方式。\n"
                            "- 接手時先看：快速開始／依賴／環境變數章節。\n"
                        ),
                        "paths": ["README.md"],
                    },
                    {
                        "type": "note",
                        "title": "重點函式／類別",
                        "body": (
                            "依知識卡片與原始碼摘錄整理今日符號。"
                            "若證據不足，請在閱讀時自行標註 def／class／export。"
                        ),
                        "paths": [],
                    },
                    {
                        "type": "note",
                        "title": "逐步走讀",
                        "body": (
                            "1. 讀今日目標與架構／脈絡。\n"
                            "2. 依檔案導覽打開必讀檔並寫下職責。\n"
                            "3. 對照重點函式，重述輸入與輸出。\n"
                            "4. 用檢查清單自我提問。"
                        ),
                        "paths": [],
                    },
                    {
                        "type": "checklist",
                        "title": "檢查清單",
                        "body": "- 能用自己的話說明今日主題\n- 能說出必讀檔職責\n- 完成每日查核",
                        "paths": [],
                    },
                ],
                "source_refs": ["README.md"],
            }

        if "每日" in blob or "DayPackage" in blob or "typed blocks" in blob or "檔案導覽" in blob:
            return {
                "days": [
                    {
                        "day": i,
                        "theme": f"第 {i} 天",
                        "blocks": [
                            {
                                "type": "goal",
                                "title": "今日目標",
                                "body": (
                                    f"- 能說明第 {i} 天主題在專案中的位置\n"
                                    f"- 能說出今日必讀檔的主要職責\n"
                                    f"- 能指出至少一個相關入口或函式"
                                ),
                                "paths": [],
                            },
                            {
                                "type": "note",
                                "title": "今日架構／脈絡",
                                "body": (
                                    f"第 {i} 天聚焦交接主題。先建立模組心智模型："
                                    "從入口或 README 理解系統邊界，再對照必讀檔案的職責與呼叫關係。"
                                ),
                                "paths": [],
                            },
                            {
                                "type": "reading",
                                "title": "檔案導覽",
                                "body": (
                                    "### `README.md`\n"
                                    "- 職責：說明專案目的、安裝與啟動方式。\n"
                                    "- 接手時先看：快速開始／依賴／環境變數章節。\n"
                                ),
                                "paths": ["README.md"],
                            },
                            {
                                "type": "note",
                                "title": "重點函式／類別",
                                "body": (
                                    "依知識卡片與原始碼摘錄整理今日符號。"
                                    "若證據不足，請在閱讀時自行標註 def／class／export。"
                                ),
                                "paths": [],
                            },
                            {
                                "type": "note",
                                "title": "逐步走讀",
                                "body": (
                                    "1. 讀今日目標與架構／脈絡。\n"
                                    "2. 依檔案導覽打開必讀檔並寫下職責。\n"
                                    "3. 對照重點函式，重述輸入與輸出。\n"
                                    "4. 用檢查清單自我提問。"
                                ),
                                "paths": [],
                            },
                            {
                                "type": "checklist",
                                "title": "檢查清單",
                                "body": "- 能用自己的話說明今日主題\n- 能說出必讀檔職責\n- 完成每日查核",
                                "paths": [],
                            },
                        ],
                        "source_refs": ["README.md"],
                    }
                    for i in range(1, days + 1)
                ],
                "overview": "# 概覽\n\n本專案交接教材由 FakeLLM 產生，用於測試流程。\n",
                "architecture": "# 架構\n\n入口與模組關係請見每日教材。\n\n```mermaid\nflowchart LR\n  A --> B\n```\n",
                "runbook": "# Runbook\n\n依 README 安裝與啟動。\n",
                "mermaid": "flowchart LR\n  A --> B\n",
                "sources_index": "# 必讀\n\n- Day 1: `README.md`\n",
            }

        if "學習規" in blob or "學習計" in blob or "midterm_day" in blob:
            mid = max(1, days // 2)
            return {
                "days": days,
                "midterm_day": mid,
                "items": [
                    {
                        "day": i,
                        "theme": f"第 {i} 天",
                        "objectives": [f"Day{i} 任務"],
                        "card_ids": ["p1"],
                        "reads": ["README.md"],
                        "pass_score": 1.0,
                    }
                    for i in range(1, days + 1)
                ],
            }

        if "去重" in blob or "可能重複" in user:
            return {"cards": [_card(id="m1", title="合併", category="module", path="src/app.py")]}

        if "架構" in blob or "模組" in blob:
            return {
                "cards": [
                    _card(
                        id="p1",
                        title="入口模組",
                        category="module",
                        path="src/app.py",
                        importance="high",
                    )
                ]
            }

        if "Runbook" in blob or "依賴" in blob:
            return {
                "cards": [
                    _card(
                        id="p2",
                        title="啟動",
                        category="runbook",
                        path="README.md",
                        importance="high",
                    )
                ]
            }

        if "陷阱" in blob or "業務規則" in blob:
            return {
                "cards": [
                    _card(id="p3", title="注意事項", category="pitfall", path="README.md")
                ]
            }

        if "補漏" in blob:
            return {
                "cards": [
                    _card(id="cov", title="補覆蓋", category="module", path="src/app.py")
                ]
            }

        return {"cards": [_card(id="c1", title="概覽", category="overview", path="README.md")]}


class OpenAICompatLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-5-mini",
        base_url: str | None = None,
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def _chat(self, system: str, user: str) -> str:
        request = {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": user + "\n\n請只輸出合法 JSON。",
                },
            ],
        }
        # GPT-5 models currently accept only their default temperature. Keep the
        # existing deterministic setting for other OpenAI-compatible providers.
        if not self._model.lower().startswith("gpt-5"):
            request["temperature"] = 0.2
        resp = self._client.chat.completions.create(
            **request,
        )
        return resp.choices[0].message.content or "{}"

    def complete_json(self, system: str, user: str, schema: type) -> Any:
        content = self._chat(system, user)
        try:
            data = parse_llm_json(content)
        except json.JSONDecodeError as exc:
            logger.warning("LLM JSON parse failed (%s); retrying once", exc)
            repair_user = (
                "下列文字不是合法 JSON（常見原因：字串內未跳脫雙引號或尾逗號）。"
                "請修正為合法 JSON 物件後只輸出 JSON，不要解釋：\n\n"
                f"{content[:6000]}"
            )
            content = self._chat(system, repair_user)
            data = parse_llm_json(content)
        if isinstance(data, dict) and "cards" in data and schema is list:
            data = data["cards"]
        return data


def get_llm_client(settings) -> LLMClient:
    if settings.use_fake_llm or not settings.openai_api_key:
        return FakeLLMClient()
    return OpenAICompatLLMClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )
