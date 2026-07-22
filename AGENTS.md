# Repository rules

- This repository is the canonical source of truth for BitzyBridge-AG.
- Make and test changes here first; never develop directly in the installed Hermes plugin.
- Back up every existing file before editing it.
- Never permanently delete files; move obsolete artifacts to a backup or trash location.
- Never commit Telegram IDs, bot tokens, usernames, local home paths, active conversation titles, or state files.
- CDP must remain loopback-only and all ambiguous states must fail closed.
- Never auto-select global Always allow.
- Run the full unittest suite, compile check, offline doctor, and secret/path scan before completion.
- Deployment to `~/.hermes/plugins/bitzybridge-ag` must back up any existing installation first.
