"""Merge knowledge cards: rules → embedding dups → LLM only on dup groups."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from app.models.schemas import Citation, KnowledgeCard
from app.pipeline.llm import LLMClient
from app.pipeline.prompts import MERGE_DUP_SYSTEM
from app.services.indexing.chroma_store import ChromaStore, cosine_similarity


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", "", title.strip().lower())


def _merge_group(group: list[KnowledgeCard]) -> KnowledgeCard:
    base = group[0].model_copy(deep=True)
    cites: list[Citation] = []
    seen: set[tuple] = set()
    details = [base.details]
    for g in group:
        for cit in g.citations:
            key = (cit.chunk_id, cit.path, cit.start_line, cit.end_line)
            if key not in seen:
                seen.add(key)
                cites.append(cit)
        if g is not group[0] and g.details and g.details not in details:
            details.append(g.details)
    base.citations = cites
    base.details = "\n\n".join(details)
    return base


def merge_by_rules(cards: list[KnowledgeCard]) -> list[KnowledgeCard]:
    by_symbol: dict[str, list[KnowledgeCard]] = defaultdict(list)
    by_title: dict[str, list[KnowledgeCard]] = defaultdict(list)
    for card in cards:
        if card.symbol:
            by_symbol[f"{card.category.value}|{card.symbol.lower()}"].append(card)
        else:
            paths = tuple(sorted({c.path for c in card.citations}))
            by_title[f"{card.category.value}|{_norm_title(card.title)}|{paths}"].append(
                card
            )
    merged: list[KnowledgeCard] = []
    for group in list(by_symbol.values()) + list(by_title.values()):
        merged.append(group[0] if len(group) == 1 else _merge_group(group))
    return merged


def mark_embedding_duplicates(
    cards: list[KnowledgeCard],
    store: ChromaStore,
    *,
    threshold: float = 0.92,
) -> list[list[KnowledgeCard]]:
    if len(cards) < 2:
        return []
    texts = [f"{c.title}\n{c.summary}" for c in cards]
    vecs = store.embed_texts(texts)
    parent = list(range(len(cards)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            if cards[i].category != cards[j].category:
                continue
            if cosine_similarity(vecs[i], vecs[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[KnowledgeCard]] = defaultdict(list)
    for i, card in enumerate(cards):
        groups[find(i)].append(card)
    return [g for g in groups.values() if len(g) >= 2]


def llm_merge_duplicate_groups(
    groups: list[list[KnowledgeCard]],
    llm: LLMClient,
) -> list[KnowledgeCard]:
    out: list[KnowledgeCard] = []
    for group in groups:
        user = "下列卡片可能重複，請合併或保留：\n" + json.dumps(
            {"cards": [c.model_dump() for c in group]}, ensure_ascii=False
        )
        try:
            raw = llm.complete_json(MERGE_DUP_SYSTEM, user, list)
            if isinstance(raw, dict) and "cards" in raw:
                raw = raw["cards"]
            merged = [KnowledgeCard.model_validate(c) for c in raw]  # type: ignore[arg-type]
            out.extend(merged)
        except Exception:
            out.extend(group)
    return out


def merge_cards(
    cards: list[KnowledgeCard],
    *,
    store: ChromaStore,
    llm: LLMClient,
) -> list[KnowledgeCard]:
    cards = merge_by_rules(cards)
    dup_groups = mark_embedding_duplicates(cards, store)
    if not dup_groups:
        return cards
    dup_ids = {c.id for g in dup_groups for c in g}
    kept = [c for c in cards if c.id not in dup_ids]
    return kept + llm_merge_duplicate_groups(dup_groups, llm)
