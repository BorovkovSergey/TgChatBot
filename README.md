# TgChatBot

Telegram-бот для группового чата: отслеживает добровольно вышедших участников и временно банит их, чтобы они не могли сразу вернуться. Telegram снимает бан автоматически по истечении срока — своей базы банов у бота нет.

## Режимы

- **manual** (по умолчанию) — при выходе участника бот постит сообщение с кнопками «Забанить на N» / «Пропустить». Нажать может только админ чата.
- **auto** — банит сразу при выходе.

Участники, удалённые админом (kicked), игнорируются — они уже забанены.

## Команды (только для админов чата)

| Команда | Описание |
|---|---|
| `/banmode auto\|manual` | Переключить режим |
| `/bantime 30m\|2h\|3d` | Срок бана (от 30 секунд до 366 дней — лимит Telegram) |
| `/status` | Текущие настройки |

Настройки хранятся per-chat в `data/settings.json` и переживают рестарт.

## Настройка бота

1. Создайте бота у [@BotFather](https://t.me/BotFather) (`/newbot`), получите токен.
2. Добавьте бота в чат и **назначьте администратором** с правом **Ban users** (`can_restrict_members`). Это обязательно для обоих режимов: без админки Telegram не присылает боту события выхода участников (`chat_member`), а бан выполняет сам бот.
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
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/
```

## Структура

```
bot/main.py      # запуск, long polling (allowed_updates: message, chat_member, callback_query)
bot/handlers.py  # события выхода, кнопки, команды
bot/settings.py  # per-chat настройки (JSON), парсинг сроков
docs/superpowers/specs/  # дизайн-спека
```
