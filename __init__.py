"""Hermes plugin: consume Antigravity reply-keyboard decisions before LLM dispatch."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:
    from .bridge import parse_button_label, queue_decision
    from .schemas import ANTIGRAVITY_CONTROL
    from .tool_handlers import antigravity_control
except ImportError:
    from bridge import parse_button_label, queue_decision
    from schemas import ANTIGRAVITY_CONTROL
    from tool_handlers import antigravity_control

_DEFAULT_STATE_DIR = Path.home() / ".cache" / "bitzybridge-ag"
_STATE_DIR = Path(os.environ.get("AG_STATE_DIR", str(_DEFAULT_STATE_DIR))).expanduser()
PENDING_DIR = _STATE_DIR / "pending"
RESPONSE_DIR = _STATE_DIR / "responses"
ALLOWED_CHAT_ID = os.environ.get("AG_TELEGRAM_CHAT_ID", "").strip()
ALLOWED_USER_ID = os.environ.get("AG_TELEGRAM_USER_ID", "").strip()

_BITZY_HELP = """**BitzyBridge-AG**

Control the active Antigravity conversation from Hermes.

• `/bitzy status` — inspect the visible Antigravity conversation
• `/bitzy send <exact conversation> :: <task>` — send a coding task
• `/bitzy stop <exact conversation>` — stop that conversation's active run
• `/skill bitzybridge-ag` — load the full prompt/workflow skill

You can also speak naturally, for example:
`Ask Antigravity in Exact Conversation to fix the failing tests.`

Send and stop fail closed when the exact visible conversation title does not match.
"""


def _source_value(source, name: str) -> str:
    if isinstance(source, dict):
        value = source.get(name, "")
    else:
        value = getattr(source, name, "")
    value = getattr(value, "value", value)
    return str(value or "")


def handle_gateway_message(event, **kwargs):
    del kwargs
    text = getattr(event, "text", "") or ""
    parsed = parse_button_label(text)
    if not parsed:
        return None

    if not ALLOWED_CHAT_ID or not ALLOWED_USER_ID:
        return {"action": "skip", "reason": "bitzybridge-ag-misconfigured"}

    source = getattr(event, "source", None)
    platform = _source_value(source, "platform").lower()
    chat_id = _source_value(source, "chat_id")
    user_id = _source_value(source, "user_id")
    if platform != "telegram" or chat_id != ALLOWED_CHAT_ID or user_id != ALLOWED_USER_ID:
        return {"action": "skip", "reason": "bitzybridge-ag-unauthorized"}

    status = queue_decision(
        PENDING_DIR,
        RESPONSE_DIR,
        parsed["nonce"],
        parsed["choice"],
        chat_id=chat_id,
        user_id=user_id,
    )
    return {"action": "skip", "reason": f"bitzybridge-ag-{status}"}


def _inline_code(value) -> str:
    return " ".join(str(value or "").replace("`", "'").split()) or "Unknown"


def _plain_preview(value, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return ""
    for character in "\\`*_[]()":
        text = text.replace(character, "\\" + character)
    return text


def _format_status(result) -> str:
    data = result
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except (TypeError, ValueError):
            return result
    if not isinstance(data, dict):
        return str(result)

    if not data.get("ok"):
        reason = _inline_code(data.get("reason") or "status unavailable")
        return f"**BitzyBridge-AG Status**\n\n🔴 **Unavailable**\n\n**Reason:** `{reason}`"

    if data.get("busy"):
        state = "🟡 **Running**"
    elif data.get("ready"):
        state = "🟢 **Ready**"
    else:
        state = "🔴 **Unavailable**"

    conversation = _inline_code(data.get("conversation"))
    composer = "⚠️ Has unsent text" if data.get("composer_text") else "Empty"
    latest = _plain_preview(data.get("latest_text"))

    lines = [
        "**BitzyBridge-AG Status**",
        "",
        state,
        "",
        f"**Conversation:** `{conversation}`",
        f"**Composer:** {composer}",
    ]
    if latest:
        lines.extend(["", "**Latest activity**", f"> {latest}"])
    url = str(data.get("url") or "").strip()
    if url.startswith(("http://", "https://")):
        lines.extend(["", f"[Open conversation]({url})"])
    return "\n".join(lines)


def _make_bitzy_command(ctx):
    def handle(raw_args: str):
        value = (raw_args or "").strip()
        if not value or value.lower() in {"help", "menu"}:
            return _BITZY_HELP

        operation, _, remainder = value.partition(" ")
        operation = operation.lower()
        remainder = remainder.strip()

        if operation == "status" and not remainder:
            result = ctx.dispatch_tool("antigravity_control", {"action": "status"})
            return _format_status(result)

        if operation == "stop" and remainder:
            return ctx.dispatch_tool(
                "antigravity_control",
                {"action": "stop", "expected_conversation": remainder},
            )

        if operation == "send" and "::" in remainder:
            conversation, task = (part.strip() for part in remainder.split("::", 1))
            if conversation and task:
                return ctx.dispatch_tool(
                    "antigravity_control",
                    {
                        "action": "send",
                        "expected_conversation": conversation,
                        "task": task,
                    },
                )

        return "Usage:\n\n" + _BITZY_HELP

    return handle


def register(ctx):
    ctx.register_tool(
        name="antigravity_control",
        toolset="antigravity",
        schema=ANTIGRAVITY_CONTROL,
        handler=antigravity_control,
    )
    ctx.register_hook("pre_gateway_dispatch", handle_gateway_message)
    ctx.register_command(
        name="bitzy",
        handler=_make_bitzy_command(ctx),
        description="Control Antigravity with BitzyBridge-AG",
        args_hint="",
    )
