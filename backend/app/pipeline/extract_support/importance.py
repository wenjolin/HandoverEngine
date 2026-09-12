"""Static + LLM importance scoring."""

from __future__ import annotations

from app.models.enums import Importance
from app.models.schemas import KnowledgeCard
from app.pipeline.extract_support.file_groups import static_path_score


def _llm_importance_bonus(imp: Importance) -> float:
    if imp == Importance.high:
        return 2.0
    if imp == Importance.medium:
        return 1.0
    return 0.0


def score_card(card: KnowledgeCard) -> float:
    path_scores = [static_path_score(c.path) for c in card.citations] or [0]
    static = max(path_scores)
    # More citations → slightly higher
    cite_bonus = min(len(card.citations), 3) * 0.5
    total = static + cite_bonus + _llm_importance_bonus(card.importance)
    return total


def apply_importance(cards: list[KnowledgeCard]) -> list[KnowledgeCard]:
    for card in cards:
        score = score_card(card)
        card.importance_score = score
        if score >= 5:
            card.importance = Importance.high
        elif score >= 3:
            card.importance = Importance.medium
        else:
            card.importance = Importance.low
        if card.importance == Importance.high and not card.citations:
            card.needs_review = True
    return cards
