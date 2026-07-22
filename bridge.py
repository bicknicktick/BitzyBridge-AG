"""Pure, fail-closed helpers for the Antigravity ↔ Telegram approval bridge."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

_BUTTONS = {
    1: "Allow once",
    2: "Allow project",
    3: "Always allow",
    4: "Deny",
}
_BUTTON_RE = re.compile(
    r"^AG\s+([A-F0-9]{6})\s+·\s+([1-4])\s+"
    r"(?:Allow once|Allow project|Always allow|Deny)$"
)
_NONCE_RE = re.compile(r"^[A-F0-9]{6}$")


def _clean_ocr(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def detect_permission_prompt(text: str) -> Optional[dict]:
    """Normalize a permission prompt only when its complete four-choice contract exists."""
    clean = _clean_ocr(text)
    lowered = clean.lower()
    required = ("allow", "allow this time", "always allow", "no")
    if not all(token in lowered for token in required):
        return None

    title_match = re.search(r"(?im)^allow\s+(.{1,120}?)\?\s*$", clean)
    if not title_match:
        return None

    subject = title_match.group(1).strip()
    kind_match = re.match(r"([a-zA-Z]+)", subject)
    kind = kind_match.group(1).lower() if kind_match else "permission"
    lines = clean.splitlines()
    title_index = next(
        (i for i, line in enumerate(lines) if line.lower().startswith("allow ") and line.endswith("?")),
        -1,
    )
    detail = ""
    if title_index >= 0:
        for line in lines[title_index + 1 : title_index + 6]:
            normalized = re.sub(r"^[1-4][.)]?\s*", "", line).lower()
            if normalized.startswith(("yes,", "no", "allow this time", "always allow")):
                break
            if line:
                detail = line[:500]
                break

    return {
        "title": f"Allow {subject}?",
        "kind": kind,
        "detail": detail,
        "text": clean[:4000],
    }


def make_button_label(nonce: str, choice: int) -> str:
    if not _NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be six uppercase hexadecimal characters")
    if choice not in _BUTTONS:
        raise ValueError("choice must be 1..4")
    return f"AG {nonce} · {choice} {_BUTTONS[choice]}"


def parse_button_label(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    match = _BUTTON_RE.fullmatch(raw)
    if not match:
        return None
    nonce = match.group(1)
    choice = int(match.group(2))
    if raw != make_button_label(nonce, choice):
        return None
    return {"nonce": nonce, "choice": choice}


def _atomic_json(path: Path, payload: dict) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _read_private_json(path: Path) -> Optional[dict]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if path.is_symlink() or not path.is_file():
        return None
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def write_pending(pending_dir: Path, request: dict) -> bool:
    """Persist an active prompt contract once, with owner-only permissions."""
    nonce = str(request.get("nonce", ""))
    required = ("created_at", "expires_at", "chat_id", "user_id", "fingerprint")
    if not _NONCE_RE.fullmatch(nonce) or not all(key in request for key in required):
        return False
    try:
        created = float(request["created_at"])
        expires = float(request["expires_at"])
    except (TypeError, ValueError):
        return False
    if expires <= created:
        return False
    payload = dict(request)
    payload["nonce"] = nonce
    payload["chat_id"] = str(payload["chat_id"])
    payload["user_id"] = str(payload["user_id"])
    return _atomic_json(pending_dir / f"{nonce}.json", payload)


def write_decision(response_dir: Path, nonce: str, choice: int, **extra) -> bool:
    """Persist one decision exactly once; return False on replay."""
    if not _NONCE_RE.fullmatch(nonce) or choice not in _BUTTONS:
        return False
    payload = {"nonce": nonce, "choice": choice, "created_at": time.time(), **extra}
    return _atomic_json(response_dir / f"{nonce}.json", payload)


def queue_decision(
    pending_dir: Path,
    response_dir: Path,
    nonce: str,
    choice: int,
    *,
    chat_id: str,
    user_id: str,
    now: float | None = None,
) -> str:
    """Bind a Telegram decision to one live prompt. Return a stable status string."""
    if not _NONCE_RE.fullmatch(nonce) or choice not in _BUTTONS:
        return "invalid"
    pending = _read_private_json(pending_dir / f"{nonce}.json")
    if pending is None or pending.get("nonce") != nonce:
        return "missing"
    if str(pending.get("chat_id", "")) != str(chat_id) or str(pending.get("user_id", "")) != str(user_id):
        return "unauthorized"
    current_time = time.time() if now is None else float(now)
    try:
        if current_time > float(pending["expires_at"]):
            return "expired"
    except (KeyError, TypeError, ValueError):
        return "invalid"
    fingerprint = str(pending.get("fingerprint", ""))
    if not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint):
        return "invalid"
    accepted = write_decision(
        response_dir,
        nonce,
        choice,
        fingerprint=fingerprint,
        chat_id=str(chat_id),
        user_id=str(user_id),
    )
    return "accepted" if accepted else "replay"
