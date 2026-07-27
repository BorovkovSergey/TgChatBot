# Design: leave-ban bot for a group chat

Date: 2026-07-27. Status: approved.

> **Change 2026-07-27:** the `manual` mode (inline buttons) was removed by the user's decision — the bot works in auto-ban mode only. Reason: manual mode still required the Ban users right for the bot (the button-triggered ban is executed by the bot), so the mode brought no permission benefit. The `/banmode` command and callback handlers were removed. The sections below describe the original design.

## Problem

A Telegram bot for a group chat: track members who leave voluntarily and temporarily ban them so they cannot rejoin immediately. The ban duration is configurable via a chat command. Two modes:

- `auto` — ban immediately on leave;
- `manual` — the bot posts a "user left" message with an inline button, the ban is executed after an admin presses it.

## Key Telegram Bot API facts

- The bot receives `chat_member` updates about other users **only while it is a chat admin**. The `left_chat_member` service message is not delivered in groups of 50+ members. Hence admin status is required in both modes.
- The ban is executed by the bot itself via `banChatMember`, which requires the `can_restrict_members` (Ban users) right — even in `manual` mode: the admin only confirms, the bot acts.
- `banChatMember(until_date=...)`: Telegram lifts the ban automatically when it expires. No own ban database or scheduler is needed. A duration outside 30 seconds…366 days is treated as a permanent ban — validated.
- A voluntary leave is a status transition to `left`. A transition to `kicked` means an admin banned the member — ignored.
- Buttons (inline keyboard + `callback_query`) are more reliable than reactions: the presser is known, admin status is easy to check. Reactions were rejected.

## Decisions

| Question | Decision |
|---|---|
| Stack | Python 3.12 + aiogram 3.x |
| Update delivery | Long polling (`allowed_updates=["message", "chat_member", "callback_query"]`) |
| Deployment | Docker + docker-compose, `restart: unless-stopped` |
| Settings | Per-chat JSON file (`data/settings.json`), volume; SQLite is overkill |
| Defaults | `manual` mode, 24h duration |

## Behavior

### Member leaves (`ChatMemberUpdated`, groups/supergroups only)

- `auto`: `ban_chat_member(until_date=now+duration)`, chat message "X left, banned for N".
- `manual`: message "X left the chat" with "Ban for N" / "Skip" buttons (`user_id` in `callback_data`).

### Buttons

The presser is checked via `get_chat_member` — status `administrator`/`creator`. Non-admins get an alert. "Ban" — ban and edit the message to "Banned (admin Y)". "Skip" — edit to "Skipped".

### Commands (admins only)

- `/banmode auto|manual` — mode;
- `/bantime 30m|2h|3d` — ban duration (validated 30s…366d);
- `/status` — current settings.

### Errors

API errors (missing rights, target is an admin) — a clear chat message, the bot does not crash.

## Layout

```
bot/main.py      # startup, allowed_updates, polling
bot/handlers.py  # chat_member, commands, callbacks
bot/settings.py  # ChatSettings, SettingsStore (JSON, atomic writes), parse/format duration
tests/           # unit tests for settings and duration
Dockerfile, docker-compose.yml, requirements.txt, .env.example, README.md
```

## Testing

- pytest units: `parse_duration`/`format_duration` (30s/366d boundaries, errors), `SettingsStore` round-trip, defaults.
- Live test in a sandbox chat: manual button, auto-ban, settings changes, persistence across container restarts.
