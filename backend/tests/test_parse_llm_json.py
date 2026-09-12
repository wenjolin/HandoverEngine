"""Tests for resilient LLM JSON parsing."""

from __future__ import annotations

import json

import pytest

from app.pipeline.llm import parse_llm_json


def test_parse_llm_json_plain():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_parse_llm_json_fenced():
    text = '```json\n{"days": [{"day": 1}]}\n```'
    assert parse_llm_json(text)["days"][0]["day"] == 1


def test_parse_llm_json_trailing_comma():
    assert parse_llm_json('{"a": 1, "b": [2, 3,],}') == {"a": 1, "b": [2, 3]}


def test_parse_llm_json_prefix_noise():
    assert parse_llm_json('Here you go:\n{"ok": true}\nThanks')["ok"] is True


def test_parse_llm_json_invalid_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json('{"stem": "說 "hello" 即可"}')
