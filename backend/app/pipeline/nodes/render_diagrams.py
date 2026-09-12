"""Render Mermaid diagrams to SVG (optional npx mermaid-cli) with placeholder fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


_PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="200">
  <rect width="100%" height="100%" fill="#f5f5f5"/>
  <text x="20" y="100" font-family="sans-serif" font-size="16" fill="#666">
    Mermaid 渲染失敗：請查看 architecture.mmd
  </text>
</svg>
"""


def run_render_diagrams(work_dir: Path) -> list[str]:
    diagrams = work_dir / "artifacts" / "diagrams"
    diagrams.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    mmd_files = list(diagrams.glob("*.mmd"))
    if not mmd_files:
        warnings.append("找不到 .mmd 圖檔")
        return warnings

    # Opt-in: downloading mermaid-cli via npx is slow/flaky; default to placeholder SVG.
    use_cli = os.environ.get("HANDOVER_MERMAID_CLI", "").lower() in {"1", "true", "yes"}
    npx = shutil.which("npx") if use_cli else None

    for mmd in mmd_files:
        svg = mmd.with_suffix(".svg")
        ok = False
        if npx:
            try:
                subprocess.run(
                    [npx, "--yes", "@mermaid-js/mermaid-cli", "-i", str(mmd), "-o", str(svg)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                ok = svg.is_file() and svg.stat().st_size > 0
            except (subprocess.SubprocessError, OSError) as exc:
                warnings.append(f"Mermaid CLI 失敗（{mmd.name}）：{exc}")
        else:
            warnings.append("未啟用 Mermaid CLI（設 HANDOVER_MERMAID_CLI=1 可啟用）")

        if not ok:
            svg.write_text(_PLACEHOLDER_SVG, encoding="utf-8")
            warnings.append(f"已寫入占位 SVG：{svg.name}")
    return warnings
