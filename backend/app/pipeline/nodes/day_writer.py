"""Day writer: DayPackage JSON + legacy curriculum markdown."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.models.enums import DayBlockType
from app.models.schemas import DayBlock, DayPackage, JobOptions, LearningPlan
from app.pipeline.llm import LLMClient
from app.pipeline.prompts import DAY_WRITER_SYSTEM
from app.services.learning.store import (
    load_cards_payload,
    load_learning_plan,
    save_day_package,
)

logger = logging.getLogger(__name__)

_MAX_FILE_CHARS = 2_000
_MAX_TOTAL_SNIPPET_CHARS = 12_000
_MAX_SNIPPET_FILES = 8
_MAX_RELATED_CARDS = 16
DAY_WRITER_WORKERS = 3
_TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".sql",
    ".sh",
    ".ps1",
}


def _collect_source_snippets(work_dir: Path, paths: list[str]) -> str:
    """Load bounded raw-file excerpts for day_writer teaching context."""
    raw = work_dir / "raw"
    if not raw.is_dir():
        return ""
    chunks: list[str] = []
    total = 0
    seen: set[str] = set()
    for rel in paths:
        if not rel or rel in seen:
            continue
        seen.add(rel)
        if len(seen) > _MAX_SNIPPET_FILES or total >= _MAX_TOTAL_SNIPPET_CHARS:
            break
        path = raw / rel
        if not path.is_file():
            path = raw / Path(rel)
        if not path.is_file():
            continue
        if path.suffix.lower() and path.suffix.lower() not in _TEXT_SUFFIXES:
            if path.suffix.lower() not in {"", ".md"}:
                continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = text.strip()
        if not text:
            continue
        if len(text) > _MAX_FILE_CHARS:
            text = text[:_MAX_FILE_CHARS] + "\n…(截斷)…"
        block = f"### FILE: {rel}\n```\n{text}\n```"
        if total + len(block) > _MAX_TOTAL_SNIPPET_CHARS:
            remain = _MAX_TOTAL_SNIPPET_CHARS - total
            if remain < 200:
                break
            block = block[:remain] + "\n…(總量截斷)…"
        chunks.append(block)
        total += len(block)
    return "\n\n".join(chunks)


def _slim_card(c: dict) -> dict:
    cites = []
    for cit in (c.get("citations") or [])[:3]:
        if isinstance(cit, dict) and cit.get("path"):
            cites.append({"path": cit["path"]})
    return {
        "id": c.get("id"),
        "title": c.get("title"),
        "summary": c.get("summary"),
        "details": (c.get("details") or "")[:600],
        "symbol": c.get("symbol"),
        "category": c.get("category"),
        "citations": cites,
    }


def _cards_for_item(item, cards: list[dict]) -> list[dict]:
    paths = set(item.reads or [])
    ids = set(item.card_ids or [])
    out: list[dict] = []
    for c in cards:
        if c.get("id") in ids:
            out.append(c)
            continue
        for cit in c.get("citations") or []:
            if cit.get("path") in paths:
                out.append(c)
                break
    return out[:_MAX_RELATED_CARDS]


def _fallback_day(item, cards: list[dict]) -> DayPackage:
    paths = list(item.reads) or ["README.md"]
    related = _cards_for_item(item, cards)
    goals = "\n".join(f"- {o}" for o in (item.objectives or [])) or f"- 理解「{item.theme}」"
    arch_lines = [
        f"今日主題：{item.theme}",
        "",
        "建議先建立整體印象，再依檔案導覽逐一對照。以下整理自既有知識卡片：",
        "",
    ]
    file_lines = ["針對必讀檔案，先掌握「這個檔負責什麼」：", ""]
    fn_lines = ["重點知識卡片（函式／模組說明以卡片 details 為準）：", ""]
    for c in related:
        title = c.get("title") or ""
        summary = c.get("summary") or ""
        details = (c.get("details") or "").strip()
        symbol = c.get("symbol")
        arch_lines.append(f"- {title}：{summary}")
        if details:
            fn_lines.append(f"### {title}" + (f"（`{symbol}`）" if symbol else ""))
            fn_lines.append(details)
            fn_lines.append("")
        cites = c.get("citations") or []
        for cit in cites:
            p = cit.get("path")
            if p and p in paths:
                file_lines.append(f"### `{p}`")
                file_lines.append(f"- 相關知識：{title} — {summary}")
                if details:
                    file_lines.append(details[:800])
                file_lines.append("")
    if len(file_lines) <= 2:
        for p in paths:
            file_lines.append(f"### `{p}`")
            file_lines.append("- 請對照原始碼與上方知識卡片，整理此檔職責與對外介面。")
            file_lines.append("")
    walk = [
        "1. 先讀今日主題與架構／脈絡，弄清這天在整體專案的位置。",
        "2. 依檔案導覽打開必讀檔，對每個檔寫下一句「它負責什麼」。",
        "3. 對照重點函式／類別，嘗試用自己的話重述輸入與輸出。",
        "4. 用檢查清單自我提問；答不出來就回到對應檔案再看一次。",
    ]
    checklist = "\n".join(f"- {o}" for o in item.objectives) or (
        "- 能用自己的話說明今日主題\n"
        "- 能說出每個必讀檔的主要職責\n"
        "- 能指出至少一個關鍵函式／入口"
    )
    return DayPackage(
        day=item.day,
        theme=item.theme,
        blocks=[
            DayBlock(type=DayBlockType.goal, title="今日目標", body=goals),
            DayBlock(
                type=DayBlockType.note,
                title="今日架構／脈絡",
                body="\n".join(arch_lines).strip(),
            ),
            DayBlock(
                type=DayBlockType.reading,
                title="檔案導覽",
                body="\n".join(file_lines).strip(),
                paths=paths,
            ),
            DayBlock(
                type=DayBlockType.note,
                title="重點函式／類別",
                body="\n".join(fn_lines).strip()
                if len(fn_lines) > 2
                else "目前卡片證據不足以列出具體函式；請在必讀檔中標註你看到的 def／class／export。",
            ),
            DayBlock(
                type=DayBlockType.note,
                title="逐步走讀",
                body="\n".join(walk),
            ),
            DayBlock(type=DayBlockType.checklist, title="檢查清單", body=checklist),
        ],
        source_refs=paths,
    )


def _parse_day(row: dict, fallback: DayPackage) -> DayPackage:
    blocks_raw = row.get("blocks") or []
    blocks: list[DayBlock] = []
    for b in blocks_raw:
        if not isinstance(b, dict):
            continue
        try:
            btype = DayBlockType(str(b.get("type") or "note"))
        except ValueError:
            btype = DayBlockType.note
        body = str(b.get("body") or "").strip()
        blocks.append(
            DayBlock(
                type=btype,
                title=b.get("title"),
                body=body,
                paths=[str(p) for p in (b.get("paths") or [])],
            )
        )
    if len(blocks) < 3:
        return fallback
    has_reading = any(b.type == DayBlockType.reading for b in blocks)
    has_goal = any(b.type == DayBlockType.goal for b in blocks)
    if not (has_reading and has_goal):
        return fallback
    avg_len = sum(len(b.body or "") for b in blocks) / max(len(blocks), 1)
    if avg_len < 40:
        return fallback
    return DayPackage(
        day=int(row.get("day") or fallback.day),
        theme=str(row.get("theme") or fallback.theme),
        blocks=blocks,
        source_refs=[str(p) for p in (row.get("source_refs") or fallback.source_refs)],
    )


def _legacy_from_plan(plan: LearningPlan) -> dict:
    themes = "、".join(it.theme for it in plan.items[:5])
    sources = "\n".join(
        f"- Day {it.day}（{it.theme}）: "
        + ", ".join(f"`{p}`" for p in (it.reads or ["README.md"]))
        for it in plan.items
    )
    return {
        "overview": (
            "# 概覽\n\n"
            f"本交接教材共 {plan.days} 天"
            f"（交接期中查核約第 {plan.midterm_day} 天）。\n\n"
            f"主題含：{themes or '專案交接'}。\n"
            "請依每日教材建立架構心智模型，再深入模組與操作。\n"
        ),
        "architecture": (
            "# 架構\n\n"
            "請依每日「今日架構／脈絡」與檔案導覽建立模組地圖。\n"
        ),
        "runbook": "# Runbook\n\n請對照 README 與每日教材中的啟動／設定說明。\n",
        "mermaid": "flowchart LR\n  A[專案入口] --> B[核心模組]\n  B --> C[產出／服務]\n",
        "sources_index": f"# 必讀\n\n{sources}\n",
    }


def _write_legacy_md(artifacts: Path, data: dict, plan: LearningPlan) -> None:
    (artifacts / "00-overview.md").write_text(
        data.get("overview")
        or "# 概覽\n\n依學習計畫逐日完成交接：先建立架構心智模型，再深入模組與操作。\n",
        encoding="utf-8",
    )
    (artifacts / "02-architecture.md").write_text(
        data.get("architecture") or "# 架構\n\n請依每日「今日架構／脈絡」與檔案導覽建立模組地圖。\n",
        encoding="utf-8",
    )
    (artifacts / "03-runbook.md").write_text(
        data.get("runbook") or "# Runbook\n",
        encoding="utf-8",
    )
    (artifacts / "sources-index.md").write_text(
        data.get("sources_index")
        or "# 必讀\n\n"
        + "\n".join(
            f"- Day {it.day}: " + ", ".join(f"`{p}`" for p in it.reads)
            for it in plan.items
        )
        + "\n",
        encoding="utf-8",
    )
    diagrams = artifacts / "diagrams"
    diagrams.mkdir(parents=True, exist_ok=True)
    mermaid = (data.get("mermaid") or "flowchart LR\n  A[App] --> B[Output]\n").strip()
    if mermaid.startswith("```"):
        mermaid = mermaid.strip("`")
        if mermaid.startswith("mermaid"):
            mermaid = mermaid[len("mermaid") :].lstrip()
    (diagrams / "architecture.mmd").write_text(mermaid + "\n", encoding="utf-8")


def rewrite_day_packages(work_dir: Path, days: list[int]) -> list[DayPackage]:
    """Rebuild selected day packages from plan + cards (deterministic fallback)."""
    plan = load_learning_plan(work_dir)
    cards = load_cards_payload(work_dir)
    by_day = {it.day: it for it in plan.items}
    packages: list[DayPackage] = []
    for d in days:
        item = by_day.get(int(d))
        if item is None:
            continue
        pkg = _fallback_day(item, cards)
        save_day_package(work_dir, pkg)
        packages.append(pkg)
    return packages


def _row_from_llm(data: object, day: int) -> dict | None:
    if isinstance(data, dict) and data.get("blocks"):
        return data
    if isinstance(data, dict):
        for row in data.get("days") or []:
            if isinstance(row, dict) and int(row.get("day") or 0) == day:
                return row
    return None


def _llm_write_one_day(
    work_dir: Path,
    item,
    cards: list[dict],
    options: JobOptions,
    llm: LLMClient,
) -> DayPackage:
    """One-day LLM write; fallback if parse fails or output too thin."""
    fb = _fallback_day(item, cards)
    related = _cards_for_item(item, cards)
    snippets = _collect_source_snippets(work_dir, list(item.reads or []))
    user = (
        f"只寫第 {item.day} 天\n"
        f"language={options.language}\n"
        f"item={item.model_dump_json()}\n"
        f"cards={json.dumps([_slim_card(c) for c in related], ensure_ascii=False)}\n\n"
        f"【原始碼摘錄】（僅供撰寫教材，不得虛構）\n"
        f"{snippets or '（無可用摘錄，請僅依 cards 保守撰寫）'}\n"
    )
    try:
        data = llm.complete_json(DAY_WRITER_SYSTEM, user, dict)
    except Exception:
        logger.exception("day_writer LLM failed: day=%s", item.day)
        return fb
    row = _row_from_llm(data, item.day)
    return _parse_day(row, fb) if row else fb


def run_day_writer(
    work_dir: Path,
    options: JobOptions,
    llm: LLMClient,
    *,
    max_workers: int = DAY_WRITER_WORKERS,
) -> list[DayPackage]:
    """Write each day via LLM in parallel (max 2–3 workers)."""
    artifacts = work_dir / "artifacts"
    plan = load_learning_plan(work_dir)
    cards = load_cards_payload(work_dir)
    workers = max(1, min(int(max_workers), 3, len(plan.items) or 1))

    def _job(item) -> DayPackage:
        pkg = _llm_write_one_day(work_dir, item, cards, options, llm)
        save_day_package(work_dir, pkg)
        return pkg

    packages: list[DayPackage] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, it) for it in plan.items]
        for fut in as_completed(futures):
            packages.append(fut.result())

    packages.sort(key=lambda p: p.day)
    _write_legacy_md(artifacts, _legacy_from_plan(plan), plan)
    return packages
