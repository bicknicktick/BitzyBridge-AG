# Security Policy

## Security model

BitzyBridge-AG treats Antigravity, Telegram messages, browser DOM state, and persisted decisions as untrusted inputs.

Security invariants:

1. CDP connections must remain loopback-only (`127.0.0.1`).
2. Exactly one compatible control surface must match before status, send, or stop is accepted.
3. Permission decisions are bound to an exact nonce, choice label, chat ID, user ID, expiry, target, and prompt fingerprint.
4. Decision files are atomic, owner-only, and single use.
5. Unknown, changed, ambiguous, expired, or replayed requests fail closed.
6. Automatic policy may choose only Allow once or Allow project; automatic global Always allow is forbidden.
7. The default policy performs no automatic approval.
8. Secrets belong in the private environment file and must never be committed.

## Reporting vulnerabilities

Do not open a public issue for a vulnerability that could expose credentials or bypass approval checks. Contact the repository owner privately with reproduction steps, affected version, and impact.

## Supported environment

The initial release targets a single-user Linux desktop running a systemd user session, Hermes Agent, Telegram gateway, and Antigravity. Exposing Antigravity CDP beyond loopback is unsupported.
