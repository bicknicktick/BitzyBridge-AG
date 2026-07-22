"""Scoped auto-bypass policy. Unknown or ambiguous prompts always fall back to confirmation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


def _extract_path(detail: str) -> Optional[Path]:
    text = (detail or "").strip()
    if text.startswith("file://"):
        text = text[7:]
    if not text.startswith("/"):
        match = re.search(r"(?<![\w.-])(/[\w@%+=:,./~ -]+)", text)
        if not match:
            return None
        text = match.group(1).strip().rstrip(".,;:)")
    try:
        return Path(os.path.abspath(os.path.expanduser(text)))
    except (OSError, ValueError):
        return None


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _canonical(path: Path) -> Path:
    """Resolve existing parents so symlink escapes cannot gain automatic approval."""
    if path.exists():
        return path.resolve()
    suffix = []
    cursor = path
    while not cursor.exists() and cursor != cursor.parent:
        suffix.append(cursor.name)
        cursor = cursor.parent
    resolved = cursor.resolve()
    for name in reversed(suffix):
        resolved /= name
    return resolved


def decide(config: dict, prompt: dict) -> Optional[int]:
    """Return 1/2 for scoped bypass, 4 for hard deny, or None for Telegram confirmation."""
    path = _extract_path(str(prompt.get("detail", "")))
    if path is None:
        return None
    path = _canonical(path)

    deny_roots = [_canonical(Path(os.path.expanduser(str(x)))) for x in config.get("deny_roots", [])]
    if any(_within(path, root) for root in deny_roots):
        return 4

    if config.get("mode") != "scoped-bypass":
        return None
    if str(prompt.get("kind", "")).lower() not in {
        str(x).lower() for x in config.get("allowed_kinds", [])
    }:
        return None

    choice = config.get("auto_choice")
    if choice not in (1, 2):
        return None
    allow_roots = [_canonical(Path(os.path.expanduser(str(x)))) for x in config.get("allow_roots", [])]
    if any(_within(path, root) for root in allow_roots):
        return int(choice)
    return None
