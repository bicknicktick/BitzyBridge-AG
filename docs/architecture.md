# BitzyBridge-AG architecture

## Data flow

```text
User on Telegram
  │ normal task message / approval keyboard label
  ▼
Hermes gateway
  │ pre_gateway_dispatch consumes exact approval labels
  ▼
BitzyBridge-AG Hermes plugin
  │ atomic response JSON, owner-only
  ▼
Watcher service
  │ validates TTL + identity + fingerprint
  ▼
Loopback Chrome DevTools Protocol
  │ exact DOM contract and synchronous click
  ▼
Antigravity
```

For task control, Hermes calls the registered `antigravity_control` tool. The tool discovers the current CDP port, selects exactly one control surface, verifies the expected conversation when supplied, inserts exact text through one native composer path, verifies the committed text, clicks Send, and verifies that the composer changed.

## Components

| File | Responsibility |
|---|---|
| `__init__.py` | Hermes plugin registration and pre-gateway approval interception |
| `bridge.py` | Button contract, atomic state, identity/TTL/replay validation |
| `cdp_client.py` | Dynamic CDP discovery, permission inspection and application |
| `cdp_control.py` | Status, exact prompt insertion, send, and stop control |
| `policy.py` | Canonical path checks and scoped fail-closed policy |
| `watcher.py` | Telegram request lifecycle, restart recovery, audit and resolution |
| `tool_handlers.py` | JSON tool handler exposed to Hermes |
| `schemas.py` | Hermes tool schema |

## Persistence

Default state directory:

```text
~/.cache/bitzybridge-ag/
├── pending/
├── responses/
├── processed/
└── audit.jsonl
```

The state directory is private to the current OS user. Pending approvals can be recovered after watcher restart only if exactly one unexpired request matches the live prompt and configured Telegram identity.

## Restart behavior

- Antigravity restart: CDP port is rediscovered from the latest live endpoint.
- Watcher restart: eligible pending approval is recovered from private state.
- Hermes gateway restart: plugin and pre-dispatch hook are loaded again.
- Expired nonces are never reused.
