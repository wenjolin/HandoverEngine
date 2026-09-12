"""Ingest node: unzip project into raw/ and write file_tree.json."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.services.secrets_filter import is_ignored_path, is_secret_path
from app.services.unzip_safe import safe_extract_zip

_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".rst",
        ".css",
        ".html",
        ".sh",
        ".ps1",
        ".sql",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".cs",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
    }
)


def _is_analyzable_text(rel: str) -> bool:
    if is_ignored_path(rel) or is_secret_path(rel):
        return False
    suffix = Path(rel).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return True
    name = Path(rel).name
    return name in {"Dockerfile", "Makefile", "LICENSE", "Procfile"}


def run_ingest(work_dir: Path, settings: Settings) -> dict:
    zip_path = work_dir / "input.zip"
    if not zip_path.is_file():
        raise ValueError("找不到 input.zip")

    raw_dir = work_dir / "raw"
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    safe_extract_zip(
        zip_path,
        raw_dir,
        max_files=settings.max_extract_files,
        max_bytes=settings.max_extract_bytes,
    )

    paths: list[str] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(raw_dir).as_posix()
        if is_ignored_path(rel) or is_secret_path(rel):
            continue
        paths.append(rel)

    analyzable = [p for p in paths if _is_analyzable_text(p)]
    if not analyzable:
        raise ValueError("專案中找不到可分析的原始碼或文件")

    tree = {"paths": paths, "analyzable_paths": analyzable}
    (artifacts / "file_tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"file_count": len(paths), "analyzable_count": len(analyzable)}
