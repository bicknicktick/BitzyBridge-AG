"""Minimal loopback-only Chrome DevTools Protocol adapter for Antigravity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Optional

import websocket

CHOICE_TEXTS = {
    1: "Yes, allow this time",
    2: "Yes, and always allow in this project",
    3: "Yes, and always allow",
    4: "No (tell the agent what to do instead)",
}

_FIND_PERMISSION_JS = r"""
function agNorm(value) {
  return String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}
function agChoiceNumber(value) {
  const text = agNorm(value).replace(/^[1-4][.)]?\s*/, '').toLowerCase();
  if (text.includes('allow this time')) return 1;
  if (text.includes('always allow in this project')) return 2;
  if (text === 'yes, and always allow' || text === 'always allow') return 3;
  if (text.startsWith('no') && (text.includes('agent') || text === 'no')) return 4;
  return 0;
}
function agVisible(el) {
  if (!el || !el.isConnected) return false;
  const style = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
}
function agFindPermission() {
  const nodes = [...document.querySelectorAll('body *')].filter(el => {
    if (!agVisible(el)) return false;
    const text = agNorm(el.innerText);
    return text.length < 180 && /^Allow\s+.+\?$/.test(text);
  });
  for (const titleNode of nodes) {
    let root = titleNode;
    for (let depth = 0; root && depth < 12; depth++, root = root.parentElement) {
      const clickables = [...root.querySelectorAll('button,[role="button"],[tabindex],label')]
        .filter(agVisible);
      const choiceElements = {};
      for (const el of clickables) {
        const number = agChoiceNumber(el.innerText || el.getAttribute('aria-label'));
        if (number && !choiceElements[number]) choiceElements[number] = el;
      }
      if ([1,2,3,4].every(n => choiceElements[n])) {
        const submit = clickables.find(el => agNorm(el.innerText || el.getAttribute('aria-label')).toLowerCase().startsWith('submit')) || null;
        const title = agNorm(titleNode.innerText);
        const lines = String(root.innerText || '').split(/\n+/).map(agNorm).filter(Boolean);
        const titleIndex = lines.findIndex(line => line === title);
        let detail = '';
        for (const line of lines.slice(Math.max(0, titleIndex + 1))) {
          if (agChoiceNumber(line)) continue;
          if (/^[1-4]$/.test(line)) continue;
          if (line === title) continue;
          if (/^(skip|submit|↵)$/i.test(line)) continue;
          detail = line.slice(0, 500);
          break;
        }
        return {
          root, titleNode, title, detail, choiceElements, submit,
          choices: Object.fromEntries([1,2,3,4].map(n => [String(n), agNorm(choiceElements[n].innerText || choiceElements[n].getAttribute('aria-label'))]))
        };
      }
    }
  }
  return null;
}
"""


def validate_snapshot(raw: object) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    title = " ".join(str(raw.get("title", "")).split())
    match = re.fullmatch(r"Allow\s+(.{1,120}?)\?", title)
    choices = raw.get("choices")
    if not match or not isinstance(choices, dict) or set(choices) != {"1", "2", "3", "4"}:
        return None
    lowered = {
        key: re.sub(r"^[1-4][.)]?\s*", "", " ".join(str(value).lower().split()))
        for key, value in choices.items()
    }
    if "allow this time" not in lowered["1"]:
        return None
    if "always allow in this project" not in lowered["2"]:
        return None
    if "always allow" not in lowered["3"] or "project" in lowered["3"]:
        return None
    if not lowered["4"].startswith("no"):
        return None
    target_id = str(raw.get("target_id", ""))
    url = str(raw.get("url", ""))
    if not target_id or not url.startswith("https://127.0.0.1:"):
        return None
    detail = " ".join(str(raw.get("detail", "")).split())[:500]
    subject = match.group(1).strip()
    kind_match = re.match(r"([A-Za-z]+)", subject)
    kind = kind_match.group(1).lower() if kind_match else "permission"
    canonical = json.dumps(
        {"target_id": target_id, "url": url, "title": title, "detail": detail, "choices": lowered},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "title": title,
        "detail": detail,
        "kind": kind,
        "choices": {int(k): str(v) for k, v in choices.items()},
        "target_id": target_id,
        "url": url,
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def discover_cdp_port(log_path: Path | None = None) -> int:
    configured = os.environ.get("AG_CDP_PORT", "").strip()
    if configured:
        port = int(configured)
        if not 1 <= port <= 65535:
            raise RuntimeError("AG_CDP_PORT outside valid range")
        return port
    path = log_path or (Path.home() / ".config" / "Antigravity" / "logs" / "language_server.log")
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"Electron WS URL:\s*ws://127\.0\.0\.1:(\d+)/devtools/browser/", text)
    if not matches:
        raise RuntimeError("Antigravity CDP port not found in language_server.log")
    return int(matches[-1])


def _json_get(url: str) -> object:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def list_pages(port: int) -> list[dict]:
    pages = _json_get(f"http://127.0.0.1:{port}/json/list")
    if not isinstance(pages, list):
        raise RuntimeError("CDP /json/list did not return a list")
    return [x for x in pages if isinstance(x, dict) and x.get("type") == "page"]


def _evaluate(websocket_url: str, expression: str) -> object:
    if not websocket_url.startswith("ws://127.0.0.1:"):
        raise RuntimeError("refusing non-loopback CDP websocket")
    ws = websocket.create_connection(websocket_url, timeout=8, suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
        }))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") != 1:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP error: {message['error']}")
            result = message.get("result", {}).get("result", {})
            if result.get("subtype") == "error" or result.get("exceptionDetails"):
                raise RuntimeError(f"CDP evaluation failed: {result}")
            return result.get("value")
    finally:
        ws.close()


def inspect_prompt(port: int | None = None) -> Optional[dict]:
    cdp_port = port or discover_cdp_port()
    expression = _FIND_PERMISSION_JS + r"""
(() => {
  const found = agFindPermission();
  if (!found) return null;
  return {title: found.title, detail: found.detail, choices: found.choices, url: location.href};
})()
"""
    for page in list_pages(cdp_port):
        ws_url = str(page.get("webSocketDebuggerUrl", ""))
        if not ws_url:
            continue
        raw = _evaluate(ws_url, expression)
        if isinstance(raw, dict):
            raw["target_id"] = str(page.get("id", ""))
            prompt = validate_snapshot(raw)
            if prompt:
                return prompt
    return None


def build_apply_choice_js(prompt: dict, choice: int) -> str:
    expected_title = json.dumps(str(prompt.get("title", "")))
    expected_detail = json.dumps(str(prompt.get("detail", "")))
    return _FIND_PERMISSION_JS + f"""
(() => {{
  const found = agFindPermission();
  if (!found) return {{ok:false, reason:'prompt-missing'}};
  if (found.title !== {expected_title} || found.detail !== {expected_detail})
    return {{ok:false, reason:'prompt-changed'}};
  const element = found.choiceElements[{choice}];
  if (!element || !agVisible(element)) return {{ok:false, reason:'choice-missing'}};
  element.focus();
  element.click();
  if (found.submit) {{
    if (!agVisible(found.submit)) return {{ok:false, reason:'submit-missing'}};
    found.submit.focus();
    found.submit.click();
    return {{ok:true, reason:'selected-and-submitted', choice:{choice}}};
  }}
  return {{ok:true, reason:'clicked', choice:{choice}}};
}})()
"""


def apply_choice(prompt: dict, choice: int, port: int | None = None) -> dict:
    if choice not in CHOICE_TEXTS:
        raise ValueError("choice must be 1..4")
    cdp_port = port or discover_cdp_port()
    pages = {str(x.get("id")): x for x in list_pages(cdp_port)}
    page = pages.get(str(prompt.get("target_id", "")))
    if not page:
        return {"ok": False, "reason": "target-missing"}
    expression = build_apply_choice_js(prompt, choice)
    result = _evaluate(str(page.get("webSocketDebuggerUrl", "")), expression)
    return result if isinstance(result, dict) else {"ok": False, "reason": "invalid-cdp-result"}
