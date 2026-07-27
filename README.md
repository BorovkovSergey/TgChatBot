# TgChatBot

Telegram-бот для группового чата: отслеживает добровольно вышедших участников и сразу банит их на заданный срок, чтобы они не могли сразу вернуться. Telegram снимает бан автоматически по истечении срока — своей базы банов у бота нет.

Участники, удалённые админом (kicked), игнорируются — они уже забанены. Вышедшие админы и владелец чата не банятся — бот только сообщает об их выходе.

## Команды (только для админов чата)

| Команда | Описание |
|---|---|
| `/bantime 30m\|2h\|3d` | Срок бана (от 1 минуты до 366 дней) |
| `/status` | Текущие настройки |

По умолчанию срок бана — 24 часа. Настройки хранятся per-chat в `data/settings.json` и переживают рестарт.

## Настройка бота

1. Создайте бота у [@BotFather](https://t.me/BotFather) (`/newbot`), получите токен.
2. Добавьте бота в чат и **назначьте администратором** с правом **Ban users** (`can_restrict_members`). Без админки Telegram не присылает боту события выхода участников (`chat_member`), а без Ban users бот не сможет банить.
3. Отключать privacy mode не требуется — события `chat_member` от него не зависят.

## Запуск

```bash
cp .env.example .env   # вписать BOT_TOKEN
docker compose up -d --build
```

Без Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
BOT_TOKEN=... .venv/bin/python -m bot.main
```

## Тесты

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/
```

## Структура

```
bot/main.py      # запуск, long polling (allowed_updates: message, chat_member)
bot/handlers.py  # события выхода, автобан, команды
bot/settings.py  # per-chat настройки (JSON), парсинг сроков
docs/superpowers/specs/  # дизайн-спека
```
