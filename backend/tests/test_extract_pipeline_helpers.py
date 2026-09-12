"""Unit tests for grouping, merge rules, coverage, importance."""

from pathlib import Path

from app.models.enums import CardCategory, Importance
from app.models.schemas import Citation, KnowledgeCard
from app.pipeline.extract_support.card_merge import merge_by_rules
from app.pipeline.extract_support.coverage import build_coverage_report
from app.pipeline.extract_support.file_groups import classify_path, group_paths_by_module, module_key
from app.pipeline.extract_support.importance import apply_importance


def test_module_key_and_group():
    assert module_key("src/app.py") == "src"
    assert module_key("README.md") == "_root"
    groups = group_paths_by_module(["src/a.py", "src/b.py", "payment/x.py"])
    assert set(groups["src"]) == {"src/a.py", "src/b.py"}
    assert groups["payment"] == ["payment/x.py"]


def test_classify_path():
    assert classify_path("src/service.py") == "code"
    assert classify_path("README.md") == "runbook"
    assert classify_path("tests/test_foo.py") == "pitfall"


def test_merge_by_rules_same_title_path():
    c1 = KnowledgeCard(
        id="a",
        title="登入",
        category=CardCategory.module,
        summary="s1",
        details="d1",
        citations=[Citation(chunk_id="auth.py::0", path="auth.py", start_line=1, end_line=2)],
        importance=Importance.medium,
    )
    c2 = KnowledgeCard(
        id="b",
        title="登入",
        category=CardCategory.module,
        summary="s2",
        details="d2",
        citations=[Citation(chunk_id="auth.py::1", path="auth.py", start_line=3, end_line=4)],
        importance=Importance.medium,
    )
    merged = merge_by_rules([c1, c2])
    assert len(merged) == 1
    assert len(merged[0].citations) == 2


def test_coverage_uncovers_important(tmp_path: Path):
    paths = ["README.md", "main.py", "payment/service.py", "utils/x.py"]
    cards = [
        KnowledgeCard(
            id="1",
            title="readme",
            category=CardCategory.overview,
            summary="s",
            details="d",
            citations=[Citation(chunk_id="README.md::0", path="README.md")],
            importance=Importance.high,
        )
    ]
    report = build_coverage_report(paths, cards)
    assert "payment/service.py" in report["uncovered_important_files"] or "main.py" in report[
        "uncovered_important_files"
    ]


def test_apply_importance_raises_main():
    card = KnowledgeCard(
        id="1",
        title="入口",
        category=CardCategory.module,
        summary="s",
        details="d",
        citations=[Citation(chunk_id="main.py::0", path="main.py")],
        importance=Importance.low,
    )
    apply_importance([card])
    assert card.importance_score is not None
    assert card.importance_score >= 3
