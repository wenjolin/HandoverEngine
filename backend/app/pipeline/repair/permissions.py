"""Worker tool whitelist and argument sanitization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Planner 只能提出這些；不含 revalidate／done（由 Critic／迴圈控制）
ALLOWED_WORKER_TOOLS = frozenset(
    {
        "list_issues",
        "rewrite_days",
        "top_up_quizzes",
        "search_chunks",
    }
)


@dataclass
class AuthResult:
    ok: bool
    tool: str
    args: dict[str, Any]
    error: str | None = None


def authorize_tool(
    tool: str,
    args: dict[str, Any] | None,
    *,
    max_day: int,
) -> AuthResult:
    """Reject unknown tools and clamp args to safe ranges."""
    name = (tool or "").strip()
    raw = args if isinstance(args, dict) else {}

    if name not in ALLOWED_WORKER_TOOLS:
        return AuthResult(
            ok=False,
            tool=name or "unknown",
            args={},
            error=f"工具不在白名單：{name!r}（允許：{sorted(ALLOWED_WORKER_TOOLS)}）",
        )

    if name == "list_issues":
        return AuthResult(ok=True, tool=name, args={})

    if name == "top_up_quizzes":
        return AuthResult(ok=True, tool=name, args={})

    if name == "rewrite_days":
        days: list[int] = []
        for d in raw.get("days") or []:
            try:
                n = int(d)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= max_day:
                days.append(n)
        days = sorted(set(days))
        if not days:
            return AuthResult(
                ok=False,
                tool=name,
                args={},
                error=f"rewrite_days 需要 1..{max_day} 的 days 列表",
            )
        return AuthResult(ok=True, tool=name, args={"days": days})

    if name == "search_chunks":
        query = str(raw.get("query") or "").strip()[:200]
        if not query:
            query = "README"
        try:
            k = int(raw.get("k") or 4)
        except (TypeError, ValueError):
            k = 4
        k = max(1, min(k, 8))
        return AuthResult(ok=True, tool=name, args={"query": query, "k": k})

    return AuthResult(ok=False, tool=name, args={}, error="未處理的工具")
