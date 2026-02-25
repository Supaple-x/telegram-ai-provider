# Telegram AI Provider Bot

## Overview
Telegram-бот — AI-консультант. Основная модель: Claude Sonnet 4.5, fallback: GPT-5.2 (OpenAI). Переключение моделей `/model`. Vision (мультимодальный контекст — AI помнит изображения), документы (PDF/DOCX/TXT), голосовые (Whisper), генерация изображений (Imagen 4), веб-поиск (DuckDuckGo), долгосрочная память (`/remember`), streaming ответов. PostgreSQL для хранения контекста.

## Tech Stack
- **Runtime**: Python 3.11+, aiogram 3.x
- **AI**: Anthropic Claude (`claude-sonnet-4-5-20250929`), OpenAI GPT-5.2 (`gpt-5.2`), Whisper (`whisper-1`)
- **Image Gen**: Google Imagen 4 (`imagen-4.0-generate-001`) — требует платный Google AI аккаунт
- **Search**: DuckDuckGo (`duckduckgo-search`) — бесплатный, без API ключа
- **Database**: PostgreSQL (asyncpg)
- **Deploy**: Docker + docker-compose, сервер `65.109.142.30:/opt/telegram-ai-bot/`

## Architecture
```
src/
  main.py                  — точка входа, middleware, cleanup task
  middleware/
    auth.py                — ALLOWED_USERS (ID + username)
    throttle.py            — rate limiting per user (in-memory)
  handlers/
    commands.py            — /start, /help, /clear, /stats, /model
    memory.py              — /remember, /memories, /forget
    messages.py            — текст, фото, документы + streaming + fallback + per-user lock
    voice.py               — голосовые (Whisper → Claude)
    search.py              — /search (DuckDuckGo → Claude)
    image.py               — /imagine (Imagen 4)
  services/
    claude.py              — Anthropic API, _build_api_messages(), FallbackError
    openai_fallback.py     — OpenAI API, _build_openai_messages()
    transcription.py       — Whisper API
    web_search.py          — DuckDuckGo (sync → asyncio.to_thread)
    image_gen.py           — Google GenAI (Imagen 4)
    documents.py           — PDF/DOCX/TXT extraction
  database/
    connection.py          — asyncpg pool, init_db/close_db, safety-net CREATE TABLEs
    context.py             — ensure_user, get/add/clear messages, MAX_CONTEXT_IMAGES
    memory.py              — user_memory CRUD
    preferences.py         — user_preferences CRUD (in-memory cache)
  utils/
    text.py                — split_message (Telegram 4096 limit)
config/
  settings.py              — dataclass Settings from .env
tests/                     — 83 unit tests (pytest)
alembic/versions/          — 001..004 migrations
```

## Database Schema

### `users`
| Column | Type | Notes |
|--------|------|-------|
| telegram_id | BIGINT PK | Telegram user ID |
| username | VARCHAR(255) | |
| created_at | TIMESTAMP | DEFAULT NOW() |

### `messages`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | BIGINT FK→users | |
| role | VARCHAR(20) | 'user' / 'assistant' |
| content | TEXT | |
| created_at | TIMESTAMP | DEFAULT NOW() |

### `message_attachments`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| message_id | INT FK→messages | ON DELETE CASCADE |
| attachment_type | VARCHAR(20) | DEFAULT 'image' |
| data | TEXT | base64 encoded |
| media_type | VARCHAR(50) | DEFAULT 'image/jpeg' |
| created_at | TIMESTAMP | DEFAULT NOW() |

### `user_memory`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | BIGINT FK→users | |
| content | VARCHAR(500) | |
| created_at | TIMESTAMP | DEFAULT NOW() |

### `user_preferences`
| Column | Type | Notes |
|--------|------|-------|
| user_id | BIGINT PK FK→users | |
| preferred_model | VARCHAR(20) | 'claude' (default) / 'openai' |
| updated_at | TIMESTAMP | |

## Constants & Limits

| Constant | Value | Location |
|----------|-------|----------|
| MAX_CONTEXT_MESSAGES | 20 | settings.py |
| MAX_CONTEXT_IMAGES | 3 | context.py |
| MAX_MESSAGE_LENGTH | 4096 | settings.py |
| MAX_MEMORIES | 10 | memory.py (database) |
| MAX_MEMORY_LENGTH | 500 | memory.py (handler) |
| STREAM_EDIT_INTERVAL | 1.5s | settings.py |
| STREAM_SPLIT_THRESHOLD | 3800 chars | messages.py |
| TELEGRAM_MSG_LIMIT | 4096 chars | text.py |
| FILE_SIZE_LIMIT | 20 MB | messages.py, voice.py |
| SEARCH_RESULTS | 5 | web_search.py |
| TTL_CLEANUP_INTERVAL | 6 hours | main.py |

## Key Function Signatures

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

## Key Patterns

### Message flow (all handlers)
```
ensure_user → get_context → get_memory_texts → get_preferred_model
→ add_message (user) → build_system_prompt → handle_ai_response
→ add_message (assistant)
```

### Multimodal context (images across turns)
- `add_message(image_data=(base64, media_type))` → transaction: INSERT messages RETURNING id → INSERT attachments
- `get_context()` → LEFT JOIN message_attachments, keeps 3 newest images (iterates DESC), returns chronological
- `_build_api_messages()` / `_build_openai_messages()` — `msg.get("image_data")` for any position; explicit `image_data` param overrides for last message

### Streaming
- `generate_*_stream()` → async generator yielding chunks
- `stream_to_message()` → progressive edit with cursor `▍`, auto-split at 3800 chars, Markdown → plain text fallback

### Fallback (Claude → GPT-5.2)
- `generate_response_stream()` raises `FallbackError` on API errors
- Handlers catch → inline button "Отправить в GPT-5.2"
- Callback handler streams via OpenAI with suffix `_via GPT-5.2_`

### Middleware (порядок: auth → throttle)
- `AuthMiddleware` — ALLOWED_USERS check. Пустой = нет ограничений
- `ThrottleMiddleware` — per-user rate limit (in-memory)
- Registered on `dp.message` and `dp.callback_query` (outer_middleware)

### Handler registration order (in `__init__.py`)
`commands_router`, `memory_router`, `search_router`, `voice_router`, `image_router`, **`messages_router` (last — catch-all)**

## How To

### Add a new command
1. Create `src/handlers/mycommand.py` with `router = Router()`
2. Register in `src/handlers/__init__.py` (before `messages_router`)
3. Add to `/help` text in `commands.py`

### Add a new message handler
1. Add to `src/handlers/messages.py` with filter (before `handle_text` catch-all)
2. Use `_user_locks[user_id]` for per-user locking
3. Follow pattern: `ensure_user → get_context → get_memory_texts → get_preferred_model → add_message → handle_ai_response`

### Add a new database table
1. Create migration: `make migrate-new` → edit `alembic/versions/NNN_*.py`
2. Add safety-net `CREATE TABLE IF NOT EXISTS` in `connection.py` `init_db()`
3. Create `src/database/mytable.py` with CRUD functions
4. Deploy: `docker compose build bot && docker compose up -d bot` → `alembic stamp NNN`

### Run tests
```bash
pytest -v                    # locally
docker compose exec bot python -m pytest tests/ -v  # in Docker
```

## Environment Variables
```
TELEGRAM_BOT_TOKEN        # Telegram Bot API token
ANTHROPIC_API_KEY         # Claude API key
OPENAI_API_KEY            # OpenAI API key (fallback + Whisper)
GEMINI_API_KEY            # Google AI key (Imagen 4, requires billing)
DATABASE_URL              # postgresql://bot:bot_password@postgres:5432/telegram_bot
ALLOWED_USERS             # IDs/usernames через запятую (пусто = нет ограничений)
RATE_LIMIT_MESSAGES=10    # per user per window
RATE_LIMIT_WINDOW=60      # seconds
MESSAGES_TTL_DAYS=30      # auto-delete (0 = off)
STREAM_EDIT_INTERVAL=1.5  # seconds between message edits
```

## Deploy
```bash
# 1. Copy files to server
scp -r src/ config/ alembic/ tests/ requirements.txt docker-compose.yml docker/ Makefile alembic.ini \
  root@65.109.142.30:/opt/telegram-ai-bot/

# 2. Build and restart
ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose build bot && docker compose up -d bot"

# 3. Stamp new migration (if any)
ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose exec bot alembic stamp NNN"

# 4. Check logs
ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose logs --tail=50 bot"
```

## Development Rules
- Type hints везде
- Каждый handler — отдельный файл с Router
- Все I/O через async/await
- `parse_mode=None` для сообщений об ошибках
- Per-user lock в message handlers
- `exc_info=True` для unexpected exceptions
- Зависимости: `>=X.Y.Z,<X+1.0.0` в requirements.txt
- НЕ хардкодить токены, НЕ забывать `docker compose build` после изменений

## Known Issues
1. **Global mutable state** — клиенты (Anthropic, OpenAI, GenAI) как module-level globals. Приемлемо для текущего масштаба.
2. **No PostgreSQL reconnect decorator** — asyncpg pool auto-reconnects, но нет retry для отдельных запросов.
3. **DB size with images** — base64 images in `message_attachments` (~666KB/image). TTL cleanup + `/clear` clean up via CASCADE.
4. **Imagen 4 requires billing** — бесплатный Google AI аккаунт не поддерживает Imagen (~$0.02/image).

## Changelog
- **2026-02-24**: Initial release + architecture audit (17 issues found, 12 fixed)
- **Session A**: 45 tests + Alembic (migrations 001)
- **Session B**: Voice messages (Whisper) + Web Search (DuckDuckGo)
- **Session C**: Long-term memory (`/remember`, migration 002) + Model switching (`/model`, migration 003)
- **Session D**: Multimodal context (images in DB, migration 004, 83 total tests)
