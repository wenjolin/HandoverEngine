"""Coverage check: important files not referenced by any card citation."""

from __future__ import annotations

from app.models.schemas import KnowledgeCard
from app.pipeline.extract_support.file_groups import important_static_paths


def build_coverage_report(
    all_paths: list[str],
    cards: list[KnowledgeCard],
) -> dict:
    referenced: set[str] = set()
    for card in cards:
        for cit in card.citations:
            referenced.add(cit.path.replace("\\", "/"))

    indexed = [p.replace("\\", "/") for p in all_paths]
    important = important_static_paths(indexed)
    uncovered = [p for p in important if p not in referenced]

    return {
        "total_files": len(indexed),
        "indexed_files": len(indexed),
        "referenced_files": len(referenced),
        "referenced_paths": sorted(referenced),
        "uncovered_important_files": uncovered[:40],
    }
