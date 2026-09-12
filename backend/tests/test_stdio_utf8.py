"""Windows stdio encoding helpers."""

from __future__ import annotations

import io
import sys

from app.services.stdio_utf8 import ensure_utf8_stdio


def test_ensure_utf8_stdio_allows_braille_print():
    ensure_utf8_stdio()
    # Simulate nano-graphrag progress tick (U+2819).
    tick = "\u2819 Processed 1 chunks\r"
    try:
        sys.stdout.write(tick)
        sys.stdout.flush()
    except UnicodeEncodeError as exc:
        raise AssertionError(f"stdio still cannot print Braille: {exc}") from exc

    # Also verify a StringIO with replace would accept it.
    buf = io.StringIO()
    buf.write(tick)
    assert "\u2819" in buf.getvalue()
