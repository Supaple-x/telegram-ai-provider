# Telegram AI Provider Bot — Контекст для Qwen

## Обзор проекта

Telegram-бот с доступом к мультимодальным AI-сервисам:
- **Claude Sonnet 4.5** (Anthropic) — основная модель
- **GPT-5.2** (OpenAI) — fallback при недоступности Claude
- **Imagen 4** (Google GenAI) — генерация изображений
- **Whisper** (OpenAI) — транскрипция голосовых
- **DuckDuckGo** — веб-поиск без API ключа

**Ключевые возможности:**
- Анализ изображений (vision) и документов (PDF/DOCX/TXT)
- Контекст диалога: последние 20 сообщений + до 3 изображений
- Долгосрочная память (`/remember`, `/memories`, `/forget`)
- Переключение моделей (`/model`)
- Streaming ответов с прогресс-индикатором
- Rate limiting и контроль доступа по списку пользователей

## Быстрый старт

### 1. Клонирование и настройка
```bash
git clone https://github.com/Supaple-x/telegram-ai-provider.git
cd telegram-ai-provider
cp .env.example .env
# Заполните .env своими ключами
```

### 2. Запуск
```bash
# Docker (рекомендуется)
docker compose up -d

# Локально
pip install -r requirements.txt
python -m src.main
```

### 3. Миграции БД
```bash
make migrate          # alembic upgrade head
make migrate-new      # создать новую миграцию
make migrate-down     # откат на 1 миграцию
```

## Структура проекта

```
telegram-ai-provider/
├── src/
│   ├── main.py              # Точка входа, middleware, background cleanup
│   ├── middleware/
│   │   ├── auth.py          # Проверка ALLOWED_USERS (ID + username)
│   │   └── throttle.py      # Rate limiting per user (in-memory deque)
│   ├── handlers/
│   │   ├── commands.py      # /start, /help, /clear, /stats, /model
│   │   ├── messages.py      # Текст, фото, документы + streaming + fallback
│   │   ├── voice.py         # Голосовые (Whisper → Claude)
│   │   ├── image.py         # /imagine (Imagen 4)
│   │   ├── search.py        # /search (DuckDuckGo → Claude)
│   │   └── memory.py        # /remember, /memories, /forget
│   ├── services/
│   │   ├── claude.py        # Anthropic API, streaming, FallbackError
│   │   ├── openai_fallback.py # OpenAI API для fallback
│   │   ├── transcription.py # Whisper API
│   │   ├── image_gen.py     # Google GenAI (Imagen 4)
│   │   ├── web_search.py    # DuckDuckGo (sync → asyncio.to_thread)
│   │   └── documents.py     # PDF/DOCX/TXT extraction
│   ├── database/
│   │   ├── connection.py    # asyncpg pool, init_db/close_db, safety-net CREATE TABLE
│   │   ├── context.py       # ensure_user, get/add/clear messages, MAX_CONTEXT_IMAGES=3
│   │   ├── memory.py        # user_memory CRUD
│   │   └── preferences.py   # user_preferences (модель)
│   └── utils/
│       └── text.py          # split_message (Telegram 4096 limit)
├── config/
│   ├── settings.py          # dataclass Settings из .env
│   └── prompts.py           # CLAUDE_SYSTEM_PROMPT
├── alembic/versions/        # Миграции 001..004
├── tests/                   # 83 unit tests (pytest)
├── docker/Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── Makefile
```

## База данных (PostgreSQL)

### Таблицы

**users**
| Column | Type | Notes |
|--------|------|-------|
| telegram_id | BIGINT PK | Telegram user ID |
| username | VARCHAR(255) | |
| created_at | TIMESTAMP | DEFAULT NOW() |

**messages**
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | BIGINT FK→users | |
| role | VARCHAR(20) | 'user' / 'assistant' |
| content | TEXT | |
| created_at | TIMESTAMP | DEFAULT NOW() |

**message_attachments**
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| message_id | INT FK→messages | ON DELETE CASCADE |
| attachment_type | VARCHAR(20) | DEFAULT 'image' |
| data | TEXT | base64 encoded |
| media_type | VARCHAR(50) | DEFAULT 'image/jpeg' |
| created_at | TIMESTAMP | DEFAULT NOW() |

**user_memory**
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | BIGINT FK→users | |
| content | VARCHAR(500) | |
| created_at | TIMESTAMP | DEFAULT NOW() |

**user_preferences**
| Column | Type | Notes |
|--------|------|-------|
| user_id | BIGINT PK FK→users | |
| preferred_model | VARCHAR(20) | 'claude' / 'openai' |
| updated_at | TIMESTAMP | |

## Константы и лимиты

| Константа | Значение | Файл |
|-----------|----------|------|
| MAX_CONTEXT_MESSAGES | 20 | settings.py |
| MAX_CONTEXT_IMAGES | 3 | context.py |
| MAX_MESSAGE_LENGTH | 4096 | settings.py |
| MAX_MEMORIES | 10 | memory.py |
| MAX_MEMORY_LENGTH | 500 | memory.py (handler) |
| STREAM_EDIT_INTERVAL | 1.5s | settings.py |
| STREAM_SPLIT_THRESHOLD | 3800 chars | messages.py |
| FILE_SIZE_LIMIT | 20 MB | messages.py, voice.py |
| SEARCH_RESULTS | 5 | web_search.py |
| TTL_CLEANUP_INTERVAL | 6 часов | main.py |
| MESSAGES_TTL_DAYS | 30 | settings.py |

## Makefile команды

```bash
make dev      # Запуск локально: python -m src.main
make install  # pip install -e ".[dev]"
make build    # docker compose build
make up       # docker compose up -d
make down     # docker compose down
make logs     # docker compose logs -f bot
make deploy   # rsync + ssh deploy на 65.109.142.30
make migrate  # alembic upgrade head
make migrate-down  # alembic downgrade -1
make migrate-new   # alembic revision -m "msg"
make test     # pytest -v
make lint     # ruff check src/
make format   # ruff format src/
make clean    # удалить __pycache__, *.pyc
```

## Environment Variables

```env
TELEGRAM_BOT_TOKEN=your_bot_token
ANTHROPIC_API_KEY=your_api_key
OPENAI_API_KEY=your_openai_key          # fallback + Whisper
GEMINI_API_KEY=your_gemini_api_key      # Imagen 4 (требуется billing)
DATABASE_URL=postgresql://bot:bot_password@postgres:5432/telegram_bot
ALLOWED_USERS=Zhagell,HolmesSherlok     # ID/usernames, пусто = нет ограничений
RATE_LIMIT_MESSAGES=10                  # per user per window
RATE_LIMIT_WINDOW=60                    # seconds
MESSAGES_TTL_DAYS=30                    # auto-delete (0 = off)
STREAM_EDIT_INTERVAL=1.5                # seconds между edit
```

## Архитектурные паттерны

### Flow обработки сообщений
```
ensure_user → get_context → get_memory_texts → get_preferred_model
→ add_message (user) → build_system_prompt → handle_ai_response
→ add_message (assistant)
```

### Мультимодальный контекст (изображения)
- `add_message(image_data=(base64, media_type))` → transaction: INSERT messages + INSERT attachments
- `get_context()` → LEFT JOIN message_attachments, хранит 3 новейших изображения
- `_build_api_messages()` / `_build_openai_messages()` — поддержка images в любой позиции

### Streaming
- `generate_*_stream()` → async generator yielding chunks
- `stream_to_message()` → progressive edit с курсором `▍`, auto-split при 3800 chars

### Fallback (Claude → GPT-5.2)
- `generate_response_stream()` raises `FallbackError` при ошибках API
- Handlers ловят → inline кнопка "Отправить в GPT-5.2"
- Callback handler стримит через OpenAI с суффиксом `_via GPT-5.2_`

### Middleware (порядок: auth → throttle)
- `AuthMiddleware` — проверка ALLOWED_USERS
- `ThrottleMiddleware` — per-user rate limit (in-memory deque)
- Registered на `dp.message` и `dp.callback_query` (outer_middleware)

### Порядок регистрации handlers (в `__init__.py`)
`commands_router` → `memory_router` → `search_router` → `voice_router` → `image_router` → **`messages_router` (последний — catch-all)**

## Ключевые функции

```python
# database/context.py
async def add_message(telegram_id: int, role: str, content: str,
                      image_data: tuple[str, str] | None = None) -> None
async def get_context(telegram_id: int) -> list[dict]
    # Returns: [{"role": str, "content": str, "image_data"?: (base64, media_type)}]

# services/claude.py
def build_system_prompt(memories: list[str] | None = None) -> str
def _build_api_messages(messages: list[dict],
                        image_data: tuple[str, str] | None = None) -> list[dict]
async def generate_response_stream(messages, image_data=None,
                                   system_prompt=None) -> AsyncGenerator[str, None]
    # Raises FallbackError on Claude API errors

# services/openai_fallback.py
def _build_openai_messages(messages, image_data=None,
                           system_prompt=None) -> list[dict]
async def generate_openai_response_stream(messages, image_data=None,
                                          system_prompt=None) -> AsyncGenerator[str, None]

# handlers/messages.py
async def handle_ai_response(message, bot, user_id, context, system_prompt,
                             preferred_model, image_data=None) -> None
async def stream_to_message(message, stream, bot, suffix="") -> str
```

## Как добавлять новое

### Новая команда
1. Создать `src/handlers/mycommand.py` с `router = Router()`
2. Зарегистрировать в `src/handlers/__init__.py` (перед `messages_router`)
3. Добавить текст в `/help` в `commands.py`

### Новый handler сообщений
1. Добавить в `src/handlers/messages.py` с filter (перед `handle_text` catch-all)
2. Использовать `_user_locks[user_id]` для per-user locking
3. Следовать паттерну: `ensure_user → get_context → ... → handle_ai_response`

### Новая таблица БД
1. Создать миграцию: `make migrate-new` → редактировать `alembic/versions/NNN_*.py`
2. Добавить safety-net `CREATE TABLE IF NOT EXISTS` в `connection.py` `init_db()`
3. Создать `src/database/mytable.py` с CRUD функциями
4. Deploy: `docker compose build bot && docker compose up -d bot` → `alembic stamp NNN`

### Запуск тестов
```bash
pytest -v                    # локально
docker compose exec bot python -m pytest tests/ -v  # в Docker
```

## Правила разработки

- **Type hints** везде
- Каждый handler — отдельный файл с `Router()`
- Все I/O через `async/await`
- `parse_mode=None` для сообщений об ошибках
- Per-user lock в message handlers
- `exc_info=True` для unexpected exceptions
- Зависимости: `>=X.Y.Z,<X+1.0.0` в requirements.txt
- **НЕ хардкодить токены**, **НЕ забывать** `docker compose build` после изменений

## Известные проблемы

1. **Global mutable state** — клиенты (Anthropic, OpenAI, GenAI) как module-level globals. Приемлемо для текущего масштаба.
2. **No PostgreSQL reconnect decorator** — asyncpg pool auto-reconnects, но нет retry для отдельных запросов.
3. **DB size with images** — base64 images в `message_attachments` (~666KB/image). TTL cleanup + `/clear` clean up via CASCADE.
4. **Imagen 4 requires billing** — бесплатный Google AI аккаунт не поддерживает Imagen (~$0.02/image).

## Changelog

- **2026-02-24**: Initial release + architecture audit (17 issues found, 12 fixed)
- **Session A**: 45 tests + Alembic (migrations 001)
- **Session B**: Voice messages (Whisper) + Web Search (DuckDuckGo)
- **Session C**: Long-term memory (`/remember`, migration 002) + Model switching (`/model`, migration 003)
- **Session D**: Multimodal context (images in DB, migration 004, 83 total tests)

## Deploy на сервер

```bash
# 1. Копирование файлов
scp -r src/ config/ alembic/ tests/ requirements.txt docker-compose.yml docker/ Makefile alembic.ini \
  root@65.109.142.30:/opt/telegram-ai-bot/

# 2. Сборка и перезапуск
ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose build bot && docker compose up -d bot"

# 3. Stamp новой миграции (если есть)
ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose exec bot alembic stamp NNN"

# 4. Проверка логов
ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose logs --tail=50 bot"
```
