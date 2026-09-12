from app.models.schemas import Citation, QuizItem
from app.services.learning.quiz_utils import (
    answers_match,
    distribute_mcq_choices,
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


def test_distribute_mcq_choices_balances_correct_positions():
    items = [
        QuizItem(
            id=f"q{i}", stem=f"題目 {i}", choices=["正解", "錯誤 A", "錯誤 B", "錯誤 C"],
            answer="正解", citations=[Citation(path="README.md")],
        )
        for i in range(4)
    ]
    distributed = distribute_mcq_choices(items)
    positions = [item.choices.index(item.answer) for item in distributed]
    assert positions == [0, 1, 2, 3]
    assert all(answers_match(item.answer, item) for item in distributed)
