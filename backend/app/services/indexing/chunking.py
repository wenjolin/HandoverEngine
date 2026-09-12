"""Split source files into structure-aware chunks (with length fallback)."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.pipeline.extract_support.file_groups import module_key

# 頂層結構起點（欄位 0，不含縮排內的巢狀 def/class）
_PY_BREAK = re.compile(r"^(?:async\s+def|def|class)\s+\w+")
_JS_BREAK = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\b|class\b)"
)
_MD_BREAK = re.compile(r"^#{1,3}\s+\S")


def _break_pattern(rel: str) -> re.Pattern[str] | None:
    suffix = PurePosixPath(rel.replace("\\", "/")).suffix.lower()
    if suffix == ".py":
        return _PY_BREAK
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return _JS_BREAK
    if suffix in {".md", ".markdown"}:
        return _MD_BREAK
    return None


def _structural_spans(lines: list[str], pattern: re.Pattern[str] | None) -> list[tuple[int, int]]:
    """Return [start, end) line-index spans for structural units."""
    n = len(lines)
    if n == 0:
        return []
    if pattern is None:
        return [(0, n)]

    breaks = [i for i, line in enumerate(lines) if pattern.match(line)]
    if not breaks:
        return [(0, n)]

    spans: list[tuple[int, int]] = []
    if breaks[0] > 0:
        spans.append((0, breaks[0]))
    for i, start in enumerate(breaks):
        end = breaks[i + 1] if i + 1 < len(breaks) else n
        spans.append((start, end))
    return spans


def _length_chunks(
    lines: list[str],
    rel: str,
    module: str,
    *,
    line_offset: int,
    max_chars: int,
    overlap: int,
    start_id: int,
) -> list[dict]:
    """Fallback: sliding window by character budget within a span."""
    chunks: list[dict] = []
    chunk_i = start_id
    start_idx = 0
    n = len(lines)

    while start_idx < n:
        buf: list[str] = []
        char_count = 0
        end_idx = start_idx
        while end_idx < n and char_count < max_chars:
            buf.append(lines[end_idx])
            char_count += len(lines[end_idx])
            end_idx += 1

        chunk_text = "".join(buf)
        if chunk_text.strip():
            abs_start = line_offset + start_idx
            abs_end = line_offset + end_idx
            chunks.append(
                {
                    "id": f"{rel}::{chunk_i}",
                    "path": rel,
                    "module": module,
                    "start_line": abs_start + 1,
                    "end_line": abs_end,
                    "text": chunk_text,
                }
            )
            chunk_i += 1

        if end_idx >= n:
            break

        overlap_chars = 0
        new_start = end_idx - 1
        while new_start > start_idx and overlap_chars < overlap:
            overlap_chars += len(lines[new_start])
            new_start -= 1
        start_idx = max(new_start + 1, start_idx + 1)

    return chunks


def chunk_file(
    path: Path,
    rel: str,
    *,
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[dict]:
    """Chunk by top-level structure (def/class/heading); length only if a unit is huge."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []

    lines = text.splitlines(keepends=True)
    module = module_key(rel)
    pattern = _break_pattern(rel)
    spans = _structural_spans(lines, pattern)

    chunks: list[dict] = []
    chunk_i = 0
    for start, end in spans:
        span_lines = lines[start:end]
        span_text = "".join(span_lines)
        if not span_text.strip():
            continue
        if len(span_text) <= max_chars:
            chunks.append(
                {
                    "id": f"{rel}::{chunk_i}",
                    "path": rel,
                    "module": module,
                    "start_line": start + 1,
                    "end_line": end,
                    "text": span_text,
                }
            )
            chunk_i += 1
        else:
            part = _length_chunks(
                span_lines,
                rel,
                module,
                line_offset=start,
                max_chars=max_chars,
                overlap=overlap,
                start_id=chunk_i,
            )
            chunks.extend(part)
            chunk_i += len(part)

    return chunks
