# TgChatBot

Telegram bot for a group chat: it tracks members who leave voluntarily and immediately bans them for a configurable period so they cannot rejoin right away. Telegram lifts the ban automatically when the period expires — the bot keeps no ban database of its own.

Members removed by an admin (kicked) are ignored — they are already banned. Admins and the chat owner who leave are not banned — the bot only announces their departure.

Works only in **supergroups**: in a basic group Telegram ignores the ban duration (the ban would become permanent), so there the bot does not ban and asks to convert the group to a supergroup instead.

## Commands (chat admins only)

| Command | Description |
|---|---|
| `/bantime 30m\|2h\|3d` | Ban duration (from 1 minute to 365 days) |
| `/status` | Current settings |

The default ban duration is 24 hours. Settings are stored per chat in `data/settings.json` and survive restarts.

## Bot setup

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and get the token.
2. Add the bot to the chat and **promote it to administrator** with the **Ban users** right (`can_restrict_members`). This is mandatory: without admin status Telegram does not deliver member-leave events (`chat_member`) to the bot, and without Ban users the bot cannot ban.
3. Disabling privacy mode is not required — `chat_member` events do not depend on it.

## Running

```bash
cp .env.example .env   # put your BOT_TOKEN there
docker compose up -d --build
```

Without Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
BOT_TOKEN=... .venv/bin/python -m bot.main
```

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/
```

## Layout

```
bot/main.py      # startup, long polling (allowed_updates derived from handlers)
bot/handlers.py  # leave events, auto-ban, commands
bot/settings.py  # per-chat settings (JSON), duration parsing
docs/superpowers/specs/  # design spec
```

## Deploy

`./deploy.sh` syncs the sources to the VPS (ssh alias `vps`), builds the image remotely and restarts the container. The container has `restart: unless-stopped` and the docker daemon is enabled, so the bot comes back up on VPS reboots by itself. The `.env` on the VPS is the source of truth for the token; a local `.env` is copied once as a bootstrap.
