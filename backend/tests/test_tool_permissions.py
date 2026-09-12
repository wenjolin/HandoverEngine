"""Unit tests for tool permission gate."""

from app.pipeline.repair.permissions import ALLOWED_WORKER_TOOLS, authorize_tool


def test_whitelist_contents():
    assert "rewrite_days" in ALLOWED_WORKER_TOOLS
    assert "revalidate" not in ALLOWED_WORKER_TOOLS
    assert "done" not in ALLOWED_WORKER_TOOLS


def test_permission_denied_unknown():
    r = authorize_tool("shell", {"cmd": "rm -rf /"}, max_day=3)
    assert r.ok is False
