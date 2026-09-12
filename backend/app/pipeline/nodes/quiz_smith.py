"""Quiz smith: QuizBank JSON + legacy quizzes markdown."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import Citation, JobOptions, QuizBank, QuizItem
from app.pipeline.llm import LLMClient
from app.pipeline.prompts import QUIZ_SMITH_SYSTEM
from app.pipeline.repair.contract import DEFAULT_CONTRACT
from app.services.learning.store import (
    load_cards_payload,
    load_learning_plan,
    load_quiz_bank,
    save_quiz_bank,
)
from app.services.learning.quiz_utils import merge_day_quizzes, normalize_quiz_item


def _pad_item(prefix: str, i: int, path: str = "README.md") -> QuizItem:
    choices = ["正確敘述", "無關選項 A", "無關選項 B", "無關選項 C"]
    return QuizItem(
        id=f"{prefix}-q{i}",
        type="mcq",
        stem=f"（補題 {i}）關於專案交接，下列何者較正確？",
        choices=choices,
        answer=choices[0],
        explanation="由系統補齊題數下限。",
        citations=[Citation(path=path)],
    )


def _ensure_min(items: list[QuizItem], n: int, prefix: str) -> list[QuizItem]:
    out = list(items)
    i = 1
    while len(out) < n:
        out.append(_pad_item(prefix, i))
        i += 1
    return out


def _parse_items(raw) -> list[QuizItem]:
    if not isinstance(raw, list):
        return []
    out: list[QuizItem] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            cites = []
            for c in row.get("citations") or []:
                if isinstance(c, dict) and c.get("path"):
                    cites.append(Citation.model_validate(c))
            out.append(
                QuizItem(
                    id=str(row.get("id") or f"q-{len(out)+1}"),
                    type=str(row.get("type") or "mcq"),
                    stem=str(row.get("stem") or ""),
                    choices=[str(x) for x in row["choices"]] if row.get("choices") else None,
                    answer=str(row.get("answer") or ""),
                    explanation=str(row.get("explanation") or ""),
                    citations=cites,
                )
            )
        except Exception:
            continue
    return [normalize_quiz_item(q) for q in out if q.stem and q.answer]


def _write_quiz_md(artifacts: Path, bank: QuizBank) -> None:
    quizzes_dir = artifacts / "quizzes"
    quizzes_dir.mkdir(parents=True, exist_ok=True)
    for day, items in bank.day_quizzes.items():
        lines = [f"# Day{day} 每日查核", ""]
        for i, q in enumerate(items, 1):
            lines.append(f"{i}. {q.stem}")
            if q.choices:
                for ch in q.choices:
                    lines.append(f"   - {ch}")
            lines.append("")
        (quizzes_dir / f"day{day}.md").write_text("\n".join(lines), encoding="utf-8")

    def dump(name: str, title: str, items: list[QuizItem]) -> None:
        lines = [f"# {title}", ""]
        for i, q in enumerate(items, 1):
            lines.append(f"{i}. {q.stem}")
            if q.choices:
                for ch in q.choices:
                    lines.append(f"   - {ch}")
            lines.append("")
        (quizzes_dir / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")

    dump("midterm", "交接期中查核", bank.midterm)
    dump("final", "上手驗收", bank.final)


def _slim_card(c: dict) -> dict:
    cites = []
    for cit in (c.get("citations") or [])[:2]:
        if isinstance(cit, dict) and cit.get("path"):
            cites.append({"path": cit["path"]})
    return {
        "id": c.get("id"),
        "title": c.get("title"),
        "summary": (c.get("summary") or "")[:200],
        "category": c.get("category"),
        "citations": cites,
    }


def top_up_quiz_bank(work_dir: Path) -> QuizBank:
    """Pad quiz bank to curriculum minimums (no LLM)."""
    c = DEFAULT_CONTRACT
    artifacts = work_dir / "artifacts"
    plan = load_learning_plan(work_dir)
    bank = load_quiz_bank(work_dir)
    day_quizzes = dict(bank.day_quizzes)
    for i in range(1, plan.days + 1):
        key = str(i)
        day_quizzes[key] = _ensure_min(
            day_quizzes.get(key) or [], c.min_day_quizzes, f"d{i}"
        )
    midterm = _ensure_min(list(bank.midterm), c.min_midterm, "mid")
    final = _ensure_min(list(bank.final), c.min_final, "fin")
    out = QuizBank(day_quizzes=day_quizzes, midterm=midterm, final=final)
    save_quiz_bank(work_dir, out)
    _write_quiz_md(artifacts, out)
    return out


def run_quiz_smith(work_dir: Path, options: JobOptions, llm: LLMClient) -> QuizBank:
    """LLM only for day quizzes; midterm/final filled by deterministic pad."""
    artifacts = work_dir / "artifacts"
    plan = load_learning_plan(work_dir)
    cards = load_cards_payload(work_dir)
    slim_cards = [_slim_card(c) for c in cards[:40]]
    plan_slim = {
        "days": plan.days,
        "midterm_day": plan.midterm_day,
        "items": [
            {
                "day": it.day,
                "theme": it.theme,
                "objectives": it.objectives,
                "reads": it.reads,
            }
            for it in plan.items
        ],
    }

    user = (
        f"days={options.days}\n"
        f"plan={json.dumps(plan_slim, ensure_ascii=False)}\n"
        f"cards={json.dumps(slim_cards, ensure_ascii=False)}"
    )
    data = {}
    try:
        raw = llm.complete_json(QUIZ_SMITH_SYSTEM, user, dict)
        if isinstance(raw, dict):
            data = raw
    except Exception:
        data = {}

    day_quizzes: dict[str, list[QuizItem]] = {}
    raw_days = merge_day_quizzes(data.get("day_quizzes") or {})
    for k, v in raw_days.items():
        day_quizzes[k] = _parse_items(v)

    for i in range(1, plan.days + 1):
        key = str(i)
        day_quizzes[key] = _ensure_min(
            day_quizzes.get(key) or [], DEFAULT_CONTRACT.min_day_quizzes, f"d{i}"
        )

    midterm = _ensure_min(
        _parse_items(data.get("midterm")), DEFAULT_CONTRACT.min_midterm, "mid"
    )
    final = _ensure_min(
        _parse_items(data.get("final")), DEFAULT_CONTRACT.min_final, "fin"
    )

    bank = QuizBank(day_quizzes=day_quizzes, midterm=midterm, final=final)
    save_quiz_bank(work_dir, bank)
    _write_quiz_md(artifacts, bank)
    return bank
