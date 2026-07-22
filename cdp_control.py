"""Semantic CDP control surface for the active Antigravity conversation."""

from __future__ import annotations

import json
import time
from typing import Optional

try:
    from .cdp_client import _evaluate, discover_cdp_port, list_pages
except ImportError:
    from cdp_client import _evaluate, discover_cdp_port, list_pages

MAX_TASK_CHARS = 20_000

_CONTROL_STATE_JS = r"""
(() => {
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const composers = [...document.querySelectorAll('[contenteditable="true"][aria-label="Message input"]')].filter(visible);
  const sends = [...document.querySelectorAll('button[data-testid="send-button"][aria-label="Send message"]')].filter(visible);
  const stops = [...document.querySelectorAll('button,[role="button"]')].filter(el => {
    if (!visible(el)) return false;
    const aria = String(el.getAttribute('aria-label') || '').trim();
    const testid = String(el.getAttribute('data-testid') || '').trim();
    return /^(Stop|Cancel|Interrupt)(\s|$)/i.test(aria) || /^(stop|cancel|interrupt)-button$/i.test(testid);
  });
  const bodyText = String(document.body?.innerText || '').trim();
  return {
    title: document.title,
    url: location.href,
    composer_count: composers.length,
    send_count: sends.length,
    stop_count: stops.length,
    composer_text: composers.length === 1 ? String(composers[0].innerText || composers[0].textContent || '') : '',
    send_disabled: sends.length === 1 ? !!sends[0].disabled : true,
    latest_text: bodyText.slice(-4000)
  };
})()
"""


def normalize_task(task: object) -> str:
    text = str(task or '').replace('\r\n', '\n').replace('\r', '\n')
    if not text.strip():
        raise ValueError('task is required')
    if len(text) > MAX_TASK_CHARS:
        raise ValueError(f'task exceeds {MAX_TASK_CHARS} characters')
    if '\x00' in text:
        raise ValueError('task contains NUL')
    return text


def validate_control_snapshot(raw: object) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    target_id = str(raw.get('target_id', ''))
    url = str(raw.get('url', ''))
    try:
        composer_count = int(raw.get('composer_count', -1))
        send_count = int(raw.get('send_count', -1))
        stop_count = int(raw.get('stop_count', -1))
    except (TypeError, ValueError):
        return None
    if not target_id or not url.startswith('https://127.0.0.1:'):
        return None
    if composer_count != 1 or (send_count, stop_count) not in ((1, 0), (0, 1)):
        return None
    return {
        'ready': True,
        'busy': stop_count == 1,
        'conversation': str(raw.get('title', ''))[:300],
        'url': url,
        'target_id': target_id,
        'composer_text': str(raw.get('composer_text', ''))[:MAX_TASK_CHARS],
        'send_disabled': bool(raw.get('send_disabled', True)),
        'latest_text': str(raw.get('latest_text', ''))[-4000:],
    }


def select_control_state(states: list[dict], expected_conversation: str | None = None) -> dict:
    candidates = states
    if expected_conversation:
        candidates = [state for state in candidates if state.get('conversation') == expected_conversation]
    if len(candidates) != 1:
        suffix = f' matching {expected_conversation!r}' if expected_conversation else ''
        raise RuntimeError(f'expected exactly one Antigravity control surface{suffix}, found {len(candidates)}')
    return candidates[0]


def inspect_control_state(port: int | None = None, expected_conversation: str | None = None) -> dict:
    cdp_port = port or discover_cdp_port()
    candidates = []
    for page in list_pages(cdp_port):
        ws = str(page.get('webSocketDebuggerUrl', ''))
        if not ws:
            continue
        raw = _evaluate(ws, _CONTROL_STATE_JS)
        if isinstance(raw, dict):
            raw['target_id'] = str(page.get('id', ''))
            state = validate_control_snapshot(raw)
            if state:
                state['_ws'] = ws
                candidates.append(state)
    return select_control_state(candidates, expected_conversation)


def public_state(state: dict) -> dict:
    return {k: v for k, v in state.items() if not k.startswith('_')}


def _matches_expected(state: dict, expected_conversation: str | None) -> bool:
    return not expected_conversation or state.get('conversation') == expected_conversation


def build_insert_text_js(text: str) -> str:
    encoded = json.dumps(text)
    return f"""
(() => {{
  const nodes = [...document.querySelectorAll('[contenteditable="true"][aria-label="Message input"]')]
    .filter(el => {{ const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; }});
  if (nodes.length !== 1) return {{ok:false,reason:'composer-ambiguous'}};
  const el=nodes[0]; el.focus();
  const selection=window.getSelection(), range=document.createRange();
  range.selectNodeContents(el); selection.removeAllRanges(); selection.addRange(range);
  document.execCommand('insertText', false, {encoded});
  return {{ok:true,text:String(el.innerText||el.textContent||'')}};
}})()
"""


def wait_for_composer_text(
    websocket_url: str,
    expected: str,
    *,
    timeout: float = 2.0,
    poll_interval: float = 0.02,
) -> bool:
    expression = r"""
(() => {
  const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
  const nodes=[...document.querySelectorAll('[contenteditable="true"][aria-label="Message input"]')].filter(visible);
  if(nodes.length!==1) return null;
  return String(nodes[0].innerText||nodes[0].textContent||'');
})()
"""
    deadline = time.monotonic() + timeout
    while True:
        if _evaluate(websocket_url, expression) == expected:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


def send_task(task: object, *, expected_conversation: str | None = None, port: int | None = None) -> dict:
    text = normalize_task(task)
    cdp_port = port or discover_cdp_port()
    state = inspect_control_state(cdp_port, expected_conversation)
    if not _matches_expected(state, expected_conversation):
        return {'ok': False, 'reason': 'conversation-mismatch', **public_state(state)}
    if state['busy']:
        return {'ok': False, 'reason': 'agent-busy', **public_state(state)}
    if state['composer_text'].strip():
        return {'ok': False, 'reason': 'composer-not-empty', **public_state(state)}

    encoded = json.dumps(text)
    inserted = _evaluate(state['_ws'], build_insert_text_js(text))
    if not isinstance(inserted, dict) or not inserted.get('ok'):
        return {'ok': False, 'reason': 'composer-insert-failed'}
    if not wait_for_composer_text(state['_ws'], text):
        return {'ok': False, 'reason': 'composer-insert-failed'}

    deadline = time.monotonic() + 3.0
    clicked = None
    click_js = f"""
(() => {{
  const composer=[...document.querySelectorAll('[contenteditable="true"][aria-label="Message input"]')];
  const sends=[...document.querySelectorAll('button[data-testid="send-button"][aria-label="Send message"]')];
  if (composer.length!==1 || sends.length!==1) return {{ok:false,reason:'controls-changed'}};
  if (String(composer[0].innerText||composer[0].textContent||'') !== {encoded}) return {{ok:false,reason:'composer-changed'}};
  if (sends[0].disabled) return {{ok:false,reason:'send-disabled'}};
  sends[0].focus(); sends[0].click(); return {{ok:true,reason:'clicked'}};
}})()
"""
    while time.monotonic() < deadline:
        clicked = _evaluate(state['_ws'], click_js)
        if isinstance(clicked, dict) and clicked.get('ok'):
            break
        if isinstance(clicked, dict) and clicked.get('reason') not in ('send-disabled',):
            break
        time.sleep(0.1)
    if not isinstance(clicked, dict) or not clicked.get('ok'):
        return {'ok': False, 'reason': (clicked or {}).get('reason', 'send-click-failed')}

    deadline = time.monotonic() + 3.0
    latest = inspect_control_state(cdp_port, expected_conversation)
    while time.monotonic() < deadline and latest.get('composer_text') == text:
        time.sleep(0.1)
        latest = inspect_control_state(cdp_port, expected_conversation)
    if latest.get('composer_text') == text:
        return {'ok': False, 'reason': 'send-not-confirmed', **public_state(latest)}
    return {'ok': True, 'reason': 'sent', 'task_chars': len(text), **public_state(latest)}


def stop_agent(*, expected_conversation: str | None = None, port: int | None = None) -> dict:
    cdp_port = port or discover_cdp_port()
    state = inspect_control_state(cdp_port, expected_conversation)
    if not _matches_expected(state, expected_conversation):
        return {'ok': False, 'reason': 'conversation-mismatch', **public_state(state)}
    if not state['busy']:
        return {'ok': False, 'reason': 'agent-idle', **public_state(state)}
    result = _evaluate(state['_ws'], r"""
(() => {
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};
  const nodes=[...document.querySelectorAll('button,[role="button"]')].filter(el=>{
    const aria=String(el.getAttribute('aria-label')||'').trim(), testid=String(el.getAttribute('data-testid')||'').trim();
    return visible(el) && (/^(Stop|Cancel|Interrupt)(\s|$)/i.test(aria)||/^(stop|cancel|interrupt)-button$/i.test(testid));
  });
  if(nodes.length!==1)return {ok:false,reason:'stop-ambiguous'};
  nodes[0].focus();nodes[0].click();return {ok:true,reason:'clicked'};
})()
""")
    if not isinstance(result, dict) or not result.get('ok'):
        return {'ok': False, 'reason': (result or {}).get('reason', 'stop-click-failed')}
    return {'ok': True, 'reason': 'stop-requested', **public_state(inspect_control_state(cdp_port, expected_conversation))}
