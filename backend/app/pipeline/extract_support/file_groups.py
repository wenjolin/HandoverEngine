"""Group project files by module / path from file tree."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

# Pass 2: docs / config / deploy
_RUNBOOK_NAMES = {
    "readme.md",
    "readme",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "makefile",
    "procfile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "cargo.toml",
    "go.mod",
}
_RUNBOOK_DIR_HINTS = ("deploy", "ops", "infra", "k8s", "helm", "scripts", "ci", ".github")
_CONFIG_SUFFIXES = {
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".env.example",
    ".json",
}
_CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}
_PITFALL_HINTS = ("test", "tests", "spec", "exception", "error", "validat")


def module_key(rel: str) -> str:
    """Top-level module bucket from relative path (file tree based)."""
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if not parts:
        return "_root"
    if len(parts) == 1:
        return "_root"
    # src/foo.py -> src; payment/service.py -> payment
    return parts[0]


def classify_path(rel: str) -> str:
    """Return pass bucket: code | runbook | pitfall | other."""
    p = PurePosixPath(rel.replace("\\", "/"))
    name = p.name.lower()
    parts_l = [x.lower() for x in p.parts]
    suffix = p.suffix.lower()

    if name in _RUNBOOK_NAMES or any(h in parts_l for h in _RUNBOOK_DIR_HINTS):
        return "runbook"
    if suffix in _CONFIG_SUFFIXES and "test" not in parts_l:
        return "runbook"
    if any(h in parts_l or h in name for h in _PITFALL_HINTS):
        return "pitfall"
    if suffix in _CODE_SUFFIXES:
        return "code"
    if name.endswith(".md"):
        return "runbook"
    return "other"


def group_paths_by_module(paths: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for rel in paths:
        groups[module_key(rel)].append(rel)
    return dict(groups)


def important_static_paths(paths: list[str]) -> list[str]:
    """Heuristic important files for coverage check."""
    scored: list[tuple[int, str]] = []
    for rel in paths:
        score = static_path_score(rel)
        if score >= 2:
            scored.append((score, rel))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, p in scored]


def static_path_score(rel: str) -> int:
    name = PurePosixPath(rel.replace("\\", "/")).name.lower()
    parts = [x.lower() for x in PurePosixPath(rel.replace("\\", "/")).parts]
    score = 0
    if name in {"main.py", "app.py", "index.ts", "index.js", "server.py", "manage.py"}:
        score += 3
    if name in {"readme.md", "readme"}:
        score += 2
    if name in {"requirements.txt", "pyproject.toml", "package.json", "go.mod", "cargo.toml"}:
        score += 2
    if any(x in {"config", "configs", "settings"} for x in parts) or "config" in name:
        score += 2
    if any(x.startswith("test") for x in parts) or name.startswith("test_"):
        score += 1
    if any(x in {"util", "utils", "helper", "helpers"} for x in parts):
        score += 1
    if any(x in {"payment", "security", "auth", "deploy"} for x in parts):
        score += 3
    return score
