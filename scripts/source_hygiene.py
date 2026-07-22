#!/usr/bin/env python3
"""Fail when public source contains local identity, secrets, or generated artifacts."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SKIP_PARTS = {".git", ".backups", "__pycache__", ".pytest_cache", ".venv", "venv"}
TEXT_SUFFIXES = {"", ".py", ".md", ".json", ".yaml", ".yml", ".sh", ".txt", ".service", ".example"}
PATTERNS = {
    "local-home": re.compile(r"/home/(?!you\b|example\b)[A-Za-z0-9._-]+"),
    "telegram-bot-token": re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),
    "private-key": re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY-----"),
    "hardcoded-telegram-id": re.compile(r"AG_TELEGRAM_(?:CHAT|USER)_ID\s*=\s*['\"]?-?\d{5,}"),
}

findings: list[str] = []
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
        continue
    if path.suffix.lower() not in TEXT_SUFFIXES:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    relative = path.relative_to(ROOT)
    for name, pattern in PATTERNS.items():
        if pattern.search(text):
            findings.append(f"{relative}: {name}")

if findings:
    print("Source hygiene FAILED:")
    for finding in findings:
        print(f"- {finding}")
    raise SystemExit(1)

print("Source hygiene: PASS")
