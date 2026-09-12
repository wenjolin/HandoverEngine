"""Normalize quiz day keys and answer/choice matching."""

from __future__ import annotations

import re

from app.models.schemas import QuizItem

_DAY_KEY_RE = re.compile(r"^(?:day|d)[_\-]?(\d+)$|^(\d+)$", re.IGNORECASE)
_LETTER_PREFIX_RE = re.compile(r"^([A-Za-z]|[0-9]+)[.\):、\s]+(.*)$")


def normalize_day_key(key: object) -> str | None:
    """Map day1 / Day 1 / d1 / 1 → '1'. Return None if not a day key."""
    s = str(key).strip()
    if not s:
        return None
    compact = re.sub(r"\s+", "", s)
    m = _DAY_KEY_RE.fullmatch(compact)
    if not m:
        return None
    num = m.group(1) or m.group(2)
    return str(int(num))


def merge_day_quizzes(raw: dict) -> dict[str, list]:
    """Collapse variously keyed day quiz lists into {'1': [...], ...}."""
    out: dict[str, list] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        nk = normalize_day_key(k)
        if nk is None:
            continue
        items = v if isinstance(v, list) else []
        out.setdefault(nk, []).extend(items)
    return out


def _choice_by_letter_or_index(token: str, choices: list[str]) -> str | None:
    t = token.strip()
    if not t or not choices:
        return None
    if len(t) == 1 and t.isalpha():
        idx = ord(t.upper()) - ord("A")
        if 0 <= idx < len(choices):
            return choices[idx]
    if t.isdigit():
        idx = int(t) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    return None


def resolve_to_choice_text(token: str, choices: list[str] | None) -> str:
    """Resolve A/1/'A. foo' to the matching choice text when possible."""
    t = (token or "").strip()
    if not t:
        return t
    choices = list(choices or [])
    for c in choices:
        if t == c or t.lower() == c.lower():
            return c

    mapped = _choice_by_letter_or_index(t, choices)
    if mapped:
        return mapped

    m = _LETTER_PREFIX_RE.match(t)
    if m:
        head, rest = m.group(1), m.group(2).strip()
        mapped = _choice_by_letter_or_index(head, choices)
        if mapped:
            return mapped
        if rest:
            for c in choices:
                if rest == c or rest.lower() == c.lower() or c.startswith(rest):
                    return c
    return t


def normalize_quiz_item(item: QuizItem) -> QuizItem:
    """Rewrite answer to canonical choice text when it is a letter/index."""
    if not item.choices:
        return item
    resolved = resolve_to_choice_text(item.answer, item.choices)
    if resolved != item.answer:
        return item.model_copy(update={"answer": resolved})
    return item


def answers_match(given: str, item: QuizItem) -> bool:
    g = resolve_to_choice_text(given, item.choices)
    a = resolve_to_choice_text(item.answer, item.choices)
    if not g and not a:
        return False
    if g == a:
        return True
    return g.lower() == a.lower()
