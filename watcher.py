#!/usr/bin/env python3
"""CDP-first Antigravity permission bridge with scoped bypass and Telegram fallback."""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

from bridge import make_button_label, write_pending
from cdp_client import apply_choice, discover_cdp_port, inspect_prompt
from policy import decide

LOG = logging.getLogger("bitzybridge-ag")
PLUGIN_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("AG_STATE_DIR", str(Path.home() / ".cache" / "bitzybridge-ag"))).expanduser()
PENDING_DIR = STATE_DIR / "pending"
RESPONSE_DIR = STATE_DIR / "responses"
PROCESSED_DIR = STATE_DIR / "processed"
AUDIT_LOG = STATE_DIR / "audit.jsonl"
POLICY_FILE = Path(os.environ.get("AG_POLICY_FILE", str(PLUGIN_DIR / "policy.json")))
POLL_SECONDS = 0.75
DECISION_TTL_SECONDS = 300
CHOICE_LABELS = {1: "Allow once", 2: "Allow project", 3: "Always allow", 4: "Deny"}


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _ensure_dirs() -> None:
    for directory in (STATE_DIR, PENDING_DIR, RESPONSE_DIR, PROCESSED_DIR):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)


def _private_json(path: Path) -> dict | None:
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def load_policy() -> dict:
    config = _private_json(POLICY_FILE)
    if config is None:
        # Installed policy is read-only under systemd and may be 0644; validate explicitly here.
        try:
            if POLICY_FILE.is_symlink() or not POLICY_FILE.is_file():
                raise RuntimeError("policy file is not a regular file")
            config = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"invalid policy file: {exc}") from exc
    if config.get("version") != 1 or config.get("mode") not in ("remote-confirm", "scoped-bypass"):
        raise RuntimeError("unsupported policy version or mode")
    if config.get("auto_choice") not in (1, 2):
        raise RuntimeError("policy auto_choice must be 1 or 2; global Always is forbidden")
    for key in ("allowed_kinds", "allow_roots", "deny_roots"):
        if not isinstance(config.get(key), list):
            raise RuntimeError(f"policy {key} must be a list")
    return config


def _audit(event: str, *, prompt: dict | None = None, **fields) -> None:
    _ensure_dirs()
    record = {"at": time.time(), "event": event, **fields}
    if prompt:
        record.update({
            "kind": prompt.get("kind"),
            "detail": str(prompt.get("detail", ""))[:500],
            "fingerprint": prompt.get("fingerprint"),
            "target_id": prompt.get("target_id"),
        })
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(AUDIT_LOG, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def telegram_api(method: str, payload: dict) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {body[:300]}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API rejected request: {result}")
    return result


def send_prompt(prompt: dict, nonce: str) -> None:
    chat_id = required_env("AG_TELEGRAM_CHAT_ID")
    detail = prompt.get("detail") or "(detail tidak tersedia — tidak akan dibypass otomatis)"
    keyboard = {
        "keyboard": [
            [make_button_label(nonce, 1), make_button_label(nonce, 2)],
            [make_button_label(nonce, 3), make_button_label(nonce, 4)],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
        "input_field_placeholder": "Pilih keputusan Antigravity",
    }
    telegram_api("sendMessage", {
        "chat_id": chat_id,
        "text": (
            "🛂 Antigravity minta izin\n\n"
            f"{prompt['title']}\n{detail}\n\n"
            f"ID: {nonce} · Berlaku 5 menit · Sekali pakai"
        ),
        "reply_markup": keyboard,
        "disable_notification": False,
    })


def send_resolution(text: str, *, notify: bool = False) -> None:
    telegram_api("sendMessage", {
        "chat_id": required_env("AG_TELEGRAM_CHAT_ID"),
        "text": text,
        "reply_markup": {"remove_keyboard": True},
        "disable_notification": not notify,
    })


def archive(path: Path, category: str) -> None:
    if not path.exists() or path.is_symlink():
        return
    destination = PROCESSED_DIR / f"{path.stem}-{category}-{time.time_ns()}{path.suffix}"
    path.rename(destination)


def _wait_until_prompt_changes(fingerprint: str, port: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = inspect_prompt(port)
        if not current or current.get("fingerprint") != fingerprint:
            return True
        time.sleep(0.1)
    return False


def _verified_apply(prompt: dict, choice: int, port: int) -> dict:
    current = inspect_prompt(port)
    if not current or current.get("fingerprint") != prompt.get("fingerprint"):
        return {"ok": False, "reason": "prompt-changed-before-click"}
    result = apply_choice(current, choice, port)
    if not result.get("ok"):
        return result
    result["prompt_changed_after_click"] = _wait_until_prompt_changes(prompt["fingerprint"], port)
    return result


def recover_pending(prompt: dict, *, now: float | None = None) -> dict | None:
    expected_chat = required_env("AG_TELEGRAM_CHAT_ID")
    expected_user = required_env("AG_TELEGRAM_USER_ID")
    current_time = time.time() if now is None else float(now)
    matches: list[dict] = []
    for path in sorted(PENDING_DIR.glob("*.json")):
        payload = _private_json(path)
        if not payload or path.stem != str(payload.get("nonce", "")):
            continue
        if payload.get("fingerprint") != prompt.get("fingerprint"):
            continue
        if str(payload.get("chat_id", "")) != expected_chat or str(payload.get("user_id", "")) != expected_user:
            continue
        try:
            if current_time > float(payload["expires_at"]):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        matches.append(payload)
    if len(matches) > 1:
        raise RuntimeError("multiple matching pending requests")
    return matches[0] if matches else None


def _create_pending(prompt: dict) -> dict:
    nonce = secrets.token_hex(3).upper()
    now = time.time()
    request = {
        "nonce": nonce,
        "created_at": now,
        "expires_at": now + DECISION_TTL_SECONDS,
        "chat_id": required_env("AG_TELEGRAM_CHAT_ID"),
        "user_id": required_env("AG_TELEGRAM_USER_ID"),
        "fingerprint": prompt["fingerprint"],
        "target_id": prompt["target_id"],
        "title": prompt["title"],
        "detail": prompt.get("detail", ""),
    }
    if not write_pending(PENDING_DIR, request):
        raise RuntimeError("nonce collision while creating pending request")
    try:
        send_prompt(prompt, nonce)
    except Exception:
        archive(PENDING_DIR / f"{nonce}.json", "send-failed")
        raise
    _audit("telegram-requested", prompt=prompt, nonce=nonce)
    return request


def inspect_prompt_with_refresh(previous_port: int | None) -> tuple[int, dict | None]:
    port = discover_cdp_port()
    if previous_port is not None and port != previous_port:
        LOG.info("Antigravity CDP port changed: %d -> %d", previous_port, port)
    return port, inspect_prompt(port)


def inspect_once() -> dict:
    port, prompt = inspect_prompt_with_refresh(None)
    return {"cdp_port": port, "prompt": prompt, "policy": load_policy()}


def self_test() -> dict:
    _ensure_dirs()
    policy_config = load_policy()
    port = discover_cdp_port()
    pages_ok = inspect_prompt(port)  # None is a valid idle result.
    return {
        "ok": True,
        "cdp_port": port,
        "prompt_active": pages_ok is not None,
        "policy_mode": policy_config["mode"],
        "telegram_token_present": bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()),
        "chat_id_present": bool(os.environ.get("AG_TELEGRAM_CHAT_ID", "").strip()),
        "user_id_present": bool(os.environ.get("AG_TELEGRAM_USER_ID", "").strip()),
    }


def watch() -> None:
    _ensure_dirs()
    policy_config = load_policy()
    port = discover_cdp_port()
    current: dict | None = None
    resolved_fingerprint: str | None = None
    clear_polls = 0
    LOG.info("Bridge ready: CDP=127.0.0.1:%d mode=%s", port, policy_config["mode"])

    while True:
        try:
            port, prompt = inspect_prompt_with_refresh(port)
            if prompt:
                clear_polls = 0
                fingerprint = prompt["fingerprint"]
                if resolved_fingerprint == fingerprint:
                    time.sleep(POLL_SECONDS)
                    continue

                if current and current["fingerprint"] != fingerprint:
                    archive(PENDING_DIR / f"{current['nonce']}.json", "superseded")
                    archive(RESPONSE_DIR / f"{current['nonce']}.json", "superseded")
                    _audit("superseded", fingerprint=current["fingerprint"], nonce=current["nonce"])
                    current = None

                if current is None:
                    current = recover_pending(prompt)
                    if current is not None:
                        LOG.info("Recovered pending permission (nonce=%s)", current["nonce"])

                automatic = decide(policy_config, prompt)
                if current is None and automatic is not None:
                    result = _verified_apply(prompt, automatic, port)
                    _audit("automatic-decision", prompt=prompt, choice=automatic, result=result)
                    if result.get("ok"):
                        action = "auto-denied" if automatic == 4 else "scoped bypass: Allow once"
                        send_resolution(f"🛡️ Antigravity {action}\n{prompt.get('detail') or prompt['title']}")
                        resolved_fingerprint = fingerprint
                    else:
                        LOG.warning("Automatic decision failed: %s", result)
                        current = _create_pending(prompt)
                        current["fingerprint"] = fingerprint
                    time.sleep(POLL_SECONDS)
                    continue

                if current is None:
                    current = _create_pending(prompt)
                    current["fingerprint"] = fingerprint
                    LOG.info("Permission prompt queued (nonce=%s)", current["nonce"])

                now = time.time()
                if now > float(current["expires_at"]):
                    archive(PENDING_DIR / f"{current['nonce']}.json", "expired")
                    archive(RESPONSE_DIR / f"{current['nonce']}.json", "expired")
                    send_resolution("⌛ Keputusan Antigravity kedaluwarsa; tidak diterapkan.")
                    _audit("expired", prompt=prompt, nonce=current["nonce"])
                    resolved_fingerprint = fingerprint
                    current = None
                    time.sleep(POLL_SECONDS)
                    continue

                response_path = RESPONSE_DIR / f"{current['nonce']}.json"
                if response_path.exists():
                    payload = _private_json(response_path)
                    if not payload or payload.get("fingerprint") != fingerprint:
                        result = {"ok": False, "reason": "invalid-or-mismatched-response"}
                    else:
                        result = _verified_apply(prompt, int(payload.get("choice", 0)), port)
                    archive(response_path, "processed")
                    archive(PENDING_DIR / f"{current['nonce']}.json", "processed")
                    _audit("telegram-decision", prompt=prompt, nonce=current["nonce"], choice=payload.get("choice") if payload else None, result=result)
                    if result.get("ok"):
                        choice = int(payload["choice"])
                        send_resolution(f"✅ Antigravity: {CHOICE_LABELS[choice]} diterapkan.")
                        resolved_fingerprint = fingerprint
                    else:
                        send_resolution(f"⚠️ Keputusan tidak diterapkan: {result.get('reason', 'unknown')}.", notify=True)
                    current = None
            else:
                resolved_fingerprint = None
                if current:
                    clear_polls += 1
                    if clear_polls >= 2:
                        archive(PENDING_DIR / f"{current['nonce']}.json", "closed-locally")
                        archive(RESPONSE_DIR / f"{current['nonce']}.json", "closed-locally")
                        send_resolution("ℹ️ Prompt Antigravity sudah ditutup di komputer; keputusan dibatalkan.")
                        _audit("closed-locally", nonce=current["nonce"], fingerprint=current["fingerprint"])
                        current = None
                        clear_polls = 0
        except Exception:
            LOG.exception("Watcher iteration failed")
        time.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="inspect once without side effects")
    parser.add_argument("--self-test", action="store_true", help="validate runtime dependencies without Telegram side effects")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.once:
        print(json.dumps(inspect_once(), indent=2, ensure_ascii=False))
    elif args.self_test:
        print(json.dumps(self_test(), indent=2, ensure_ascii=False))
    else:
        watch()


if __name__ == "__main__":
    main()
