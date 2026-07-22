"""Hermes tool handler for local Antigravity control."""

from __future__ import annotations

import json

try:
    from .cdp_control import inspect_control_state, public_state, send_task, stop_agent
except ImportError:
    from cdp_control import inspect_control_state, public_state, send_task, stop_agent


def antigravity_control(args: dict, **kwargs) -> str:
    del kwargs
    action = str((args or {}).get("action", "")).strip().lower()
    expected = str((args or {}).get("expected_conversation", "")).strip() or None
    try:
        if action == "status":
            return json.dumps({"ok": True, "reason": "status", **public_state(inspect_control_state(expected_conversation=expected))}, ensure_ascii=False)
        if action == "send":
            task = (args or {}).get("task")
            if task is None or not str(task).strip():
                return json.dumps({"ok": False, "reason": "task-required"})
            return json.dumps(send_task(task, expected_conversation=expected), ensure_ascii=False)
        if action == "stop":
            return json.dumps(stop_agent(expected_conversation=expected), ensure_ascii=False)
        return json.dumps({"ok": False, "reason": "invalid-action"})
    except Exception as exc:
        return json.dumps({"ok": False, "reason": "control-error", "error": str(exc)[:500]}, ensure_ascii=False)
