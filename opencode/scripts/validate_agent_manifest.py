#!/usr/bin/env python3
"""Validate agents.json against canonical agent Markdown frontmatter."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_scalar(value: str):
    value = value.strip()
    if value in {"allow", "ask", "deny"}:
        return value
    if value in {"true", "false"}:
        return value == "true"
    return value.strip('"').strip("'")


def parse_frontmatter(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"Missing frontmatter: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"Unterminated frontmatter: {path}") from error

    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for raw_line in lines[1:end]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, separator, raw_value = raw_line.strip().partition(":")
        if not separator:
            raise ValueError(f"Unsupported frontmatter line in {path}: {raw_line}")
        key = key.strip('"').strip("'")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if raw_value.strip():
            parent[key] = parse_scalar(raw_value)
        else:
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def main() -> int:
    manifest = json.loads((ROOT / "agents.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    for name, expected in manifest.items():
        frontmatter = parse_frontmatter(ROOT / "agents" / f"{name}.md")
        actual = {
            key: frontmatter[key]
            for key in ("mode", "model", "permission")
            if key in frontmatter
        }
        if actual != expected:
            errors.append(f"{name}: agents.json={expected!r}, frontmatter={actual!r}")
    if errors:
        raise SystemExit("Agent manifest mismatch:\n" + "\n".join(errors))
    print(f"Validated {len(manifest)} agent definitions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
