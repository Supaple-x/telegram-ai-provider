# Telegram AI Provider Bot

Telegram-бот с доступом к Claude API (Sonnet 4.5) — профессиональный AI-консультант с поддержкой изображений, документов и сохранением контекста диалогов.

## Возможности

- **Claude Sonnet 4.5** — самая актуальная модель от Anthropic
- **Vision** — анализ изображений (фото, скриншоты, диаграммы)
- **Документы** — чтение PDF, DOCX, TXT файлов
- **Контекст** — запоминает последние 20 сообщений
- **Markdown** — форматированные ответы с кодом

## Быстрый старт

### 1. Клонирование

```bash
git clone https://github.com/Supaple-x/telegram-ai-provider.git
cd telegram-ai-provider
```

### 2. Настройка

```bash
cp .env.example .env
```

Заполните `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
ANTHROPIC_API_KEY=your_api_key
```

### 3. Запуск

```bash
# Docker (рекомендуется)
docker compose up -d

# Или локально
pip install -r requirements.txt
python -m src.main
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и информация |
| `/help` | Справка по использованию |
| `/clear` | Очистить контекст диалога |

## Структура проекта

```
├── src/
│   ├── handlers/      # Обработчики команд и сообщений
│   ├── services/      # Claude API, обработка документов
│   ├── database/      # PostgreSQL, хранение контекста
│   └── utils/         # Вспомогательные функции
├── config/            # Настройки приложения
├── docker/            # Dockerfile
├── docker-compose.yml
├── requirements.txt
└── Makefile
```

## Makefile команды

```bash
make dev      # Запуск локально
make build    # Сборка Docker-образа
make up       # Запуск контейнеров
make down     # Остановка контейнеров
make logs     # Просмотр логов
make deploy   # Деплой на сервер
```

## Технологии

- **Python 3.11+**
- **aiogram 3.x** — Telegram Bot API
- **Anthropic SDK** — Claude API
- **PostgreSQL** — хранение контекста
- **Docker** — контейнеризация

## Лицензия

MIT
