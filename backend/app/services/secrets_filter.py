"""Path filters for ignored directories and secret files."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "build",
        ".venv",
        "venv",
        "env",
        "__pycache__",
    }
)

_SECRET_NAME_RE = re.compile(
    r"(^\.env$|^\.env\.|.*\.pem$|.*\.key$|^id_rsa$|^id_dsa$|"
    r".*credentials.*|.*secret.*)",
    re.IGNORECASE,
)


def is_ignored_path(rel: str) -> bool:
    """Return True if any path segment is an ignored directory name."""
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    return any(part in _IGNORED_DIR_NAMES for part in parts)


def is_secret_path(rel: str) -> bool:
    """Return True if the file looks like a secret / credential path."""
    name = PurePosixPath(rel.replace("\\", "/")).name
    return bool(_SECRET_NAME_RE.match(name))
