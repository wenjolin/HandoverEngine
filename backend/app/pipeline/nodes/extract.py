"""Multi-pass extract: module groups → specialized LLM → merge; coverage gap via graph."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.models.schemas import KnowledgeCard
from app.pipeline.llm import LLMClient
from app.pipeline.prompts import (
    EXTRACT_COVERAGE_SYSTEM,
    EXTRACT_PASS1_SYSTEM,
    EXTRACT_PASS2_SYSTEM,
    EXTRACT_PASS3_SYSTEM,
)
from app.pipeline.extract_support.card_merge import merge_cards
from app.services.indexing.chroma_store import ChromaStore
from app.pipeline.extract_support.coverage import build_coverage_report
from app.pipeline.extract_support.file_groups import classify_path, group_paths_by_module
from app.pipeline.extract_support.importance import apply_importance
from app.services.learning.store import load_cards_payload

_MAX_CHUNKS = 8
MAX_COVERAGE_RETRIES = 1


@dataclass
class CoverageCheckResult:
    ok: bool
    uncovered_paths: list[str] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)


def _format_chunks(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        cid = c.get("id") or ""
        parts.append(
            f"[chunk_id={cid} path={c.get('path')} "
            f"lines={c.get('start_line')}-{c.get('end_line')}]\n{c.get('text', '')}"
        )
    return "\n---\n".join(parts)


def _parse_cards(raw: object, *, id_prefix: str) -> list[KnowledgeCard]:
    if isinstance(raw, dict) and "cards" in raw:
        raw = raw["cards"]
    if not isinstance(raw, list):
        return []
    cards: list[KnowledgeCard] = []
    for i, item in enumerate(raw):
        try:
            card = KnowledgeCard.model_validate(item)
            if not card.id:
                card.id = f"{id_prefix}-{i}"
            cards.append(card)
        except Exception:
            continue
    return cards


def _call_extract(
    llm: LLMClient,
    system: str,
    scope: str,
    chunks: list[dict],
    *,
    id_prefix: str,
) -> list[KnowledgeCard]:
    if not chunks:
        return []
    paths = sorted({c.get("path", "") for c in chunks if c.get("path")})
    user = (
        f"分析範圍（僅限）：{', '.join(paths)}\n"
        f"任務：{scope}\n\n{_format_chunks(chunks)}"
    )
    last_err: Exception | None = None
    for _ in range(3):
        try:
            return _parse_cards(llm.complete_json(system, user, list), id_prefix=id_prefix)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"extract 失敗（{id_prefix}）：{last_err}")


def _chunks_for_paths(store: ChromaStore, paths: set[str]) -> list[dict]:
    return [
        {
            "id": row.get("id"),
            "path": row.get("path"),
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
            "text": row.get("text"),
        }
        for row in store.iter_chunks()
        if row.get("path") in paths
    ]


def _limit(chunks: list[dict], n: int = _MAX_CHUNKS) -> list[dict]:
    if len(chunks) <= n:
        return chunks
    step = len(chunks) / n
    idxs = sorted({min(len(chunks) - 1, int(i * step)) for i in range(n)})
    return [chunks[i] for i in idxs]


def _batch_modules(
    groups: dict[str, list[str]],
    *,
    max_paths: int = 8,
    max_modules: int = 4,
) -> list[tuple[list[str], list[str]]]:
    """Batch tiny modules into fewer pass1 LLM calls."""
    batches: list[tuple[list[str], list[str]]] = []
    cur_mods: list[str] = []
    cur_paths: list[str] = []
    for mod, paths in groups.items():
        if len(paths) >= max_paths:
            if cur_mods:
                batches.append((cur_mods, cur_paths))
                cur_mods, cur_paths = [], []
            batches.append(([mod], list(paths)))
            continue
        if cur_mods and (
            len(cur_mods) >= max_modules or len(cur_paths) + len(paths) > max_paths
        ):
            batches.append((cur_mods, cur_paths))
            cur_mods, cur_paths = [], []
        cur_mods.append(mod)
        cur_paths.extend(paths)
    if cur_mods:
        batches.append((cur_mods, cur_paths))
    return batches


def _open_store(work_dir: Path, settings: Settings) -> ChromaStore:
    return ChromaStore(
        work_dir / "index",
        embedding_backend=settings.embedding_backend,
        openai_api_key=settings.embedding_api_key or settings.openai_api_key,
        openai_base_url=settings.embedding_base_url or settings.openai_base_url,
        embedding_model=settings.embedding_model,
    )


def _load_paths(work_dir: Path) -> list[str]:
    tree_path = work_dir / "artifacts" / "file_tree.json"
    if not tree_path.is_file():
        return []
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    return tree.get("analyzable_paths") or tree.get("paths") or []


def _persist_cards(
    work_dir: Path, cards: list[KnowledgeCard], coverage: dict
) -> None:
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {"cards": [c.model_dump() for c in cards], "coverage": coverage}
    (artifacts / "cards.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (artifacts / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_extract(
    work_dir: Path, settings: Settings, llm: LLMClient
) -> list[KnowledgeCard]:
    """Main extract passes only (coverage gap handled by graph nodes)."""
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    store = _open_store(work_dir, settings)
    paths = _load_paths(work_dir)

    code_paths = [p for p in paths if classify_path(p) == "code"]
    runbook_paths = [p for p in paths if classify_path(p) == "runbook"]
    pitfall_paths = [p for p in paths if classify_path(p) == "pitfall"]

    all_cards: list[KnowledgeCard] = []

    for mods, mod_paths in _batch_modules(group_paths_by_module(code_paths)):
        label = "+".join(mods)
        chunks = _limit(_chunks_for_paths(store, set(mod_paths)))
        all_cards.extend(
            _call_extract(
                llm,
                EXTRACT_PASS1_SYSTEM,
                f"只分析模組「{label}」的架構與模組職責。",
                chunks,
                id_prefix=f"p1-{label.replace('/', '_')[:40]}",
            )
        )

    all_cards.extend(
        _call_extract(
            llm,
            EXTRACT_PASS2_SYSTEM,
            "只從 README／設定／部署檔萃取 runbook、dependency、overview。",
            _limit(_chunks_for_paths(store, set(runbook_paths)), 12),
            id_prefix="p2",
        )
    )

    p3_paths = set(pitfall_paths)
    for q in ("exception raise error", "validation", "TODO FIXME"):
        for h in store.query(q, k=4):
            if h.get("path"):
                p3_paths.add(h["path"])
    all_cards.extend(
        _call_extract(
            llm,
            EXTRACT_PASS3_SYSTEM,
            "只從例外／驗證／測試相關片段萃取 pitfall 與 business_rule。",
            _limit(_chunks_for_paths(store, p3_paths), 12),
            id_prefix="p3",
        )
    )

    all_cards = merge_cards(all_cards, store=store, llm=llm)
    coverage = build_coverage_report(paths, all_cards)
    all_cards = apply_importance(all_cards)
    _persist_cards(work_dir, all_cards, coverage)
    return all_cards


def run_check_coverage(work_dir: Path) -> CoverageCheckResult:
    """Recompute coverage from cards.json; persist coverage.json."""
    paths = _load_paths(work_dir)
    cards: list[KnowledgeCard] = []
    for row in load_cards_payload(work_dir):
        try:
            cards.append(KnowledgeCard.model_validate(row))
        except Exception:
            continue
    coverage = build_coverage_report(paths, cards)
    uncovered = list(coverage.get("uncovered_important_files") or [])
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cards_path = artifacts / "cards.json"
    if cards_path.is_file():
        payload = json.loads(cards_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["coverage"] = coverage
            cards_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return CoverageCheckResult(
        ok=len(uncovered) == 0, uncovered_paths=uncovered, coverage=coverage
    )


def run_extract_gap(
    work_dir: Path,
    settings: Settings,
    llm: LLMClient,
    uncovered_paths: list[str],
) -> list[KnowledgeCard]:
    """Fill coverage gaps for uncovered important paths only."""
    store = _open_store(work_dir, settings)
    paths = _load_paths(work_dir)
    existing: list[KnowledgeCard] = []
    for row in load_cards_payload(work_dir):
        try:
            existing.append(KnowledgeCard.model_validate(row))
        except Exception:
            continue

    if uncovered_paths:
        cov_chunks = _limit(_chunks_for_paths(store, set(uncovered_paths)), 10)
        if cov_chunks:
            existing.extend(
                _call_extract(
                    llm,
                    EXTRACT_COVERAGE_SYSTEM,
                    f"補分析：{', '.join(uncovered_paths[:15])}",
                    cov_chunks,
                    id_prefix="cov",
                )
            )
            existing = merge_cards(existing, store=store, llm=llm)

    coverage = build_coverage_report(paths, existing)
    existing = apply_importance(existing)
    _persist_cards(work_dir, existing, coverage)
    return existing


def decide_coverage_route(
    *,
    coverage_ok: bool,
    uncovered_paths: list[str],
    coverage_retries: int,
) -> str:
    """Rule router: one gap pass max, then continue to handover_gaps."""
    if (
        not coverage_ok
        and uncovered_paths
        and coverage_retries < MAX_COVERAGE_RETRIES
    ):
        return "extract_gap"
    return "handover_gaps"
