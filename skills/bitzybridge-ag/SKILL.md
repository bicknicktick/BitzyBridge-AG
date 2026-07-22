---
name: bitzybridge-ag
description: Use when the user asks to control the visible Antigravity coding conversation from Hermes or Telegram—send coding work, inspect current progress, stop the exact active run, or handle Antigravity approval prompts through BitzyBridge-AG.
version: 0.1.0
author: Bitzy
license: MIT
metadata:
  hermes:
    tags: [antigravity, telegram, coding-agent, remote-control]
    related_skills: []
---

# BitzyBridge-AG

## Overview

Use the `antigravity_control` tool as the only control path. Do not substitute terminal keystrokes, generic browser automation, or guessed UI state when this tool is available.

## When to Use

- The user asks Hermes to send a coding task to Antigravity.
- The user asks what the visible Antigravity conversation is doing.
- The user explicitly asks to stop the exact Antigravity run.
- An Antigravity permission prompt must be resolved through the bridge.

Do not use this skill for unrelated background jobs, cron tasks, system services, or coding agents other than the visible Antigravity conversation.

## Actions

### Inspect status

Call:

```json
{"action":"status"}
```

Report the exact visible conversation title and run state returned by the tool.

### Send a coding task

If the user supplied the exact active conversation title, call:

```json
{
  "action":"send",
  "expected_conversation":"<exact visible title>",
  "task":"<complete coding instruction>"
}
```

If no exact title was supplied, inspect status first, then use the returned title. Preserve the user's scope, constraints, paths, test requirements, and requested output in the task. A title mismatch must fail closed; never retry against a different conversation by guessing.

### Stop an active run

Stop only when the user explicitly asks to stop Antigravity. Inspect status first unless the exact title is already known, then call:

```json
{
  "action":"stop",
  "expected_conversation":"<exact visible title>"
}
```

Never interpret a cron job, watcher, service, or unrelated process as the Antigravity production run.

## Telegram command menu

The plugin registers `/bitzy` in Hermes gateway sessions:

- `/bitzy` or `/bitzy help` — show command help
- `/bitzy status` — inspect the active conversation
- `/bitzy send <exact conversation> :: <task>` — send work directly
- `/bitzy stop <exact conversation>` — stop the exact conversation

Natural-language requests remain supported. Examples:

- `Cek status Antigravity.`
- `Kirim ke Antigravity conversation Exact Title: perbaiki semua test sampai lulus.`
- `Stop run Antigravity di conversation Exact Title.`

## Approval behavior

Antigravity permission prompts are governed by the bridge's scoped approval policy. Do not claim approval was granted unless the tool or bridge returns verified evidence. Denials, title mismatches, expired prompts, and ambiguous targets must remain fail-closed.

## Completion reporting

Treat Antigravity's response as a self-report. For code changes or external side effects, verify the resulting files, tests, git state, URL, or other concrete artifact before telling the user the work succeeded.

## Common Pitfalls

1. **Guessing a title.** Inspect status and use the exact visible title.
2. **Stopping the wrong process.** Stop only the matched Antigravity conversation after an explicit user request.
3. **Treating dispatch as completion.** A successful send proves task delivery, not that the code works.
4. **Bypassing fail-closed behavior.** Never weaken title matching, sender binding, prompt expiry, or approval policy to make an operation succeed.

## Verification Checklist

- [ ] The requested action matches `status`, `send`, or explicit `stop` intent.
- [ ] `send` and `stop` target the exact visible conversation title.
- [ ] Tool output confirms the requested operation's postcondition.
- [ ] Any claimed code result or side effect was independently verified.
