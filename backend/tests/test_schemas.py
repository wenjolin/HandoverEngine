from app.models.schemas import KnowledgeCard, Citation


def test_card_needs_review_default_false():
    card = KnowledgeCard(
        id="c1",
        title="啟動方式",
        category="runbook",
        summary="用 make up",
        details="詳見 README",
        citations=[Citation(path="README.md", start_line=1, end_line=10)],
        importance="high",
    )
    assert card.needs_review is False
