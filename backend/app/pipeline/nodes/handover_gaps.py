"""Analyze handover gaps: coverage/structure (rules) + contradictions (limited LLM)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.schemas import KnowledgeCard
from app.pipeline.extract_support.coverage import build_coverage_report
from app.pipeline.extract_support.file_groups import classify_path
from app.pipeline.llm import LLMClient
from app.pipeline.prompts import HANDOVER_GAPS_SYSTEM
from app.services.learning.store import artifacts_dir, load_cards_payload

# Cap LLM contradiction items to keep cost/latency bounded.
_MAX_LLM_GAPS = 5
_MAX_CARD_SNIPPETS = 12
_MAX_DOC_CHARS = 2500


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _load_paths(work_dir: Path) -> list[str]:
    tree = artifacts_dir(work_dir) / "file_tree.json"
    if not tree.is_file():
        return []
    data = json.loads(tree.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        files = data.get("analyzable_paths") or data.get("paths") or []
    elif isinstance(data, list):
        files = data
    else:
        files = []
    return [_norm(str(p)) for p in files if p]


def _load_coverage(work_dir: Path, cards: list[dict], paths: list[str]) -> dict:
    cov_path = artifacts_dir(work_dir) / "coverage.json"
    if cov_path.is_file():
        try:
            return json.loads(cov_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    validated: list[KnowledgeCard] = []
    for row in cards:
        try:
            validated.append(KnowledgeCard.model_validate(row))
        except Exception:
            continue
    return build_coverage_report(paths, validated)


def _gap(
    *,
    gid: str,
    kind: str,
    severity: str,
    title: str,
    detail: str,
    sources: list[str],
    question: str,
) -> dict[str, Any]:
    return {
        "id": gid,
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "sources": sources[:8],
        "question": question,
        "status": "unresolved",
        "source_type": "auto",
        "created_at": None,
        "updated_at": None,
    }


def _structural_gaps(paths: list[str], cards: list[dict], coverage: dict) -> list[dict]:
    gaps: list[dict] = []
    n = 0

    uncovered = list(coverage.get("uncovered_important_files") or [])
    for path in uncovered[:15]:
        n += 1
        gaps.append(
            _gap(
                gid=f"cov-{n}",
                kind="coverage",
                severity="high",
                title=f"重要檔案未納入知識卡：`{path}`",
                detail="覆蓋檢查顯示此重要路徑尚未被任何知識卡引用。",
                sources=[path],
                question=f"這個檔案 `{path}` 在系統裡負責什麼？接手時一定要先讀哪一段？",
            )
        )

    lower_names = {Path(_norm(p)).name.lower() for p in paths}
    has_code = any(classify_path(p) == "code" for p in paths)
    has_readme = "readme.md" in lower_names or "readme" in lower_names
    if has_code and not has_readme:
        n += 1
        gaps.append(
            _gap(
                gid=f"struct-{n}",
                kind="structure",
                severity="high",
                title="有程式碼但缺少 README",
                detail="專案含程式檔，但檔案樹中找不到 README，接手者缺少入口說明。",
                sources=[],
                question="專案目的、安裝與啟動方式目前散落在哪？是否應補一份 README？",
            )
        )

    dep_files = [
        p
        for p in paths
        if Path(_norm(p)).name.lower()
        in {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "go.mod",
            "cargo.toml",
        }
    ]
    categories = {str(c.get("category") or "") for c in cards}
    runbook_cards = [c for c in cards if str(c.get("category") or "") == "runbook"]
    if dep_files and not runbook_cards:
        n += 1
        gaps.append(
            _gap(
                gid=f"struct-{n}",
                kind="structure",
                severity="medium",
                title="有依賴清單但缺少 Runbook 知識卡",
                detail="偵測到依賴／套件清單，但萃取結果沒有 runbook 類知識卡。",
                sources=dep_files[:5],
                question="正式環境怎麼安裝依賴、啟動服務，以及如何確認啟動成功？",
            )
        )

    deploy_paths = [
        p
        for p in paths
        if classify_path(p) == "runbook"
        and any(
            h in _norm(p).lower()
            for h in ("docker", "deploy", "k8s", "helm", "compose", ".github")
        )
    ]
    cited: set[str] = set()
    for c in cards:
        for cit in c.get("citations") or []:
            if isinstance(cit, dict) and cit.get("path"):
                cited.add(_norm(str(cit["path"])))
    uncited_deploy = [p for p in deploy_paths if _norm(p) not in cited][:8]
    if uncited_deploy:
        n += 1
        gaps.append(
            _gap(
                gid=f"struct-{n}",
                kind="structure",
                severity="medium",
                title="部署／CI 相關檔案未被知識卡引用",
                detail="存在 Docker／部署／CI 路徑，但尚未出現在知識卡 citations。",
                sources=uncited_deploy,
                question="部署與 CI 流程的標準步驟是什麼？失敗時先看哪個設定檔？",
            )
        )

    if has_code and "architecture" not in categories and "module" not in categories:
        n += 1
        gaps.append(
            _gap(
                gid=f"struct-{n}",
                kind="structure",
                severity="medium",
                title="缺少架構／模組類知識卡",
                detail="有程式碼，但萃取結果沒有 architecture 或 module 類卡片。",
                sources=[],
                question="系統的主要模組邊界與請求／資料流入口在哪裡？",
            )
        )

    return gaps


def _card_briefs(cards: list[dict]) -> list[dict]:
    briefs: list[dict] = []
    for c in cards[:_MAX_CARD_SNIPPETS]:
        paths = []
        for cit in c.get("citations") or []:
            if isinstance(cit, dict) and cit.get("path"):
                paths.append(_norm(str(cit["path"])))
        briefs.append(
            {
                "id": c.get("id"),
                "title": c.get("title"),
                "category": c.get("category"),
                "summary": (c.get("summary") or "")[:240],
                "details": (c.get("details") or "")[:400],
                "paths": paths[:4],
            }
        )
    return briefs


def _doc_snippets(work_dir: Path, paths: list[str]) -> list[dict]:
    """Read a few markdown/docs from raw/ for contradiction check."""
    raw = work_dir / "raw"
    preferred = []
    for p in paths:
        name = Path(_norm(p)).name.lower()
        if name in {"readme.md", "readme"} or name.endswith(".md"):
            preferred.append(p)
    snippets: list[dict] = []
    for rel in preferred[:4]:
        fp = raw / rel
        if not fp.is_file():
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        snippets.append({"path": _norm(rel), "text": text[:_MAX_DOC_CHARS]})
    return snippets


def _llm_contradiction_gaps(llm: LLMClient, cards: list[dict], docs: list[dict]) -> list[dict]:
    if not cards and not docs:
        return []
    user = json.dumps(
        {
            "cards": _card_briefs(cards),
            "docs": docs,
            "max_items": _MAX_LLM_GAPS,
        },
        ensure_ascii=False,
    )
    try:
        data = llm.complete_json(HANDOVER_GAPS_SYSTEM, user, dict)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("gaps") or data.get("contradictions") or []
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for i, row in enumerate(rows[:_MAX_LLM_GAPS], start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("topic") or "").strip()
        detail = str(row.get("detail") or row.get("explanation") or "").strip()
        question = str(row.get("question") or "").strip()
        if not title or not question:
            continue
        sources = row.get("sources") or row.get("paths") or []
        if not isinstance(sources, list):
            sources = []
        out.append(
            _gap(
                gid=f"contra-{i}",
                kind="contradiction",
                severity=str(row.get("severity") or "medium"),
                title=title[:160],
                detail=(detail or "文件或知識卡描述可能互相矛盾／含糊。")[:500],
                sources=[_norm(str(s)) for s in sources if s][:6],
                question=question[:200],
            )
        )
    return out


def run_handover_gaps(work_dir: Path, llm: LLMClient) -> dict:
    """Build handover_gaps.json from coverage/structure rules + limited LLM pass."""
    paths = _load_paths(work_dir)
    cards = load_cards_payload(work_dir)
    coverage = _load_coverage(work_dir, cards, paths)

    gaps = _structural_gaps(paths, cards, coverage)
    gaps.extend(_llm_contradiction_gaps(llm, cards, _doc_snippets(work_dir, paths)))

    by_kind = {"coverage": 0, "structure": 0, "contradiction": 0, "manual": 0}
    for g in gaps:
        k = str(g.get("kind") or "")
        if k in by_kind:
            by_kind[k] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(gaps),
            "coverage": by_kind["coverage"],
            "structure": by_kind["structure"],
            "contradiction": by_kind["contradiction"],
            "manual": by_kind["manual"],
        },
        "gaps": gaps,
    }
    out = artifacts_dir(work_dir) / "handover_gaps.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
