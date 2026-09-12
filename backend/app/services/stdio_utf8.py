"""Make stdout/stderr UTF-8 safe on Windows (cp950 cannot print Braille spinners)."""

from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    """Reconfigure process stdio so nano-graphrag progress ticks do not crash."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue
