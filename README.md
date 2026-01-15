# Pinterest Automation (RU)

Краткое описание:
Сервис для автоматизации Pinterest‑контента: парсинг референсов, генерация изображений или видео, публикация и управление через Telegram‑бота.

## Возможности
- Работа с несколькими аккаунтами Pinterest (Late API).
- Автоматический пайплайн: парсинг → генерация → публикация.
- Генерация изображений (Gemini или OpenAI).
- Генерация видео (Freepik image‑to‑video) + наложение текста через ffmpeg.
- Управление через Telegram‑бот (аккаунты, промпты, модель, запуск).
- Очистка референсов и результатов после успешной публикации.

## Основные файлы
- `bot.py` — Telegram‑бот и пайплайн `/run`.
- `parse.py` — парсинг референсов из Pinterest.
- `main1.py` — генерация изображений через Gemini.
- `main.py` — генерация изображений через OpenAI.
- `main3.py` — генерация видео и промо‑видео.
- `proxy.py` — публикация в Pinterest через Late API.
- `settings.json` / `accounts.json` — локальные настройки (не коммитятся).

## Быстрый старт (локально)
1) Создай `settings.json` и `accounts.json` по шаблонам:
   - `settings.example.json`
   - `accounts.example.json`
2) Запуск:
```
python3 bot.py
```

## Docker
```
docker compose up --build -d
```

## Команды бота
- `/accounts` — список аккаунтов
- `/account_set <alias>` — выбрать аккаунт
- `/prompt_show <key>` — показать промпт
- `/prompt_edit <key>` — изменить промпт
- `/model gemini|openai|video` — выбрать модель
- `/run` — запустить полный пайплайн
- `/status` — статус задачи
