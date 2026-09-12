from app.models.schemas import Citation, QuizItem
from app.services.learning.quiz_utils import (
    answers_match,
    merge_day_quizzes,
    normalize_day_key,
    normalize_quiz_item,
)


def test_normalize_day_key():
    assert normalize_day_key("1") == "1"
    assert normalize_day_key("day1") == "1"
    assert normalize_day_key("Day 2") == "2"
    assert normalize_day_key("d_3") == "3"
    assert normalize_day_key("midterm") is None


def test_merge_day_quizzes_collapses_aliases():
    merged = merge_day_quizzes(
        {
            "day1": [{"id": "a"}],
            "1": [{"id": "b"}],
            "Day 2": [{"id": "c"}],
        }
    )
    assert set(merged) == {"1", "2"}
    assert len(merged["1"]) == 2
    assert len(merged["2"]) == 1


def test_answers_match_letter_and_text():
    item = QuizItem(
        id="q1",
        stem="題目",
        choices=["正確敘述", "錯誤 A", "錯誤 B"],
        answer="A",
        citations=[Citation(path="README.md")],
    )
    item = normalize_quiz_item(item)
    assert item.answer == "正確敘述"
    assert answers_match("正確敘述", item)
    assert answers_match("A", item)
    assert answers_match("1", item)
    assert not answers_match("錯誤 A", item)
