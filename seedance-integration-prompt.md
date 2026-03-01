# Задача: Интеграция генерации видео (Seedance 1.5 Pro) в Telegram-бот

## Контекст проекта

Существующий Telegram-бот (`C:\Dev\telegram-ai-provider`) на Python 3.11 + aiogram 3.x.
Архитектура: handlers (Router) → services → database. Claude Sonnet 4.5 primary, GPT-5.2 fallback, Imagen 4 для картинок. PostgreSQL (asyncpg), Docker, Alembic миграции. 83 теста.

Изучи CLAUDE.md — там полная документация проекта.

## Что нужно сделать

Добавить генерацию видео через **Seedance 1.5 Pro** (ByteDance) с API-провайдером **fal.ai**.

### Функционал:
1. **Команда `/video <промпт>`** — быстрая генерация text-to-video
2. **Команда `/video` (без аргумента)** — запуск пошагового wizard
3. **Image-to-video** — если пользователь отправляет фото с подписью `/video <промпт>`
4. **Wizard** — пошаговый мастер через inline-кнопки:
   - Шаг 1: Тип (text-to-video / image-to-video)
   - Шаг 2: Aspect ratio (16:9 / 9:16 / 1:1)
   - Шаг 3: Длительность (5с / 8с / 10с)
   - Шаг 4: Разрешение (720p / 1080p)
   - Шаг 5: Аудио (да / нет)
   - Шаг 6: Ввод промпта (или отправка фото для i2v)
   - Шаг 7: Подтверждение + редактирование промпта с помощью AI
   - Генерация → отправка видео пользователю

## API-справка: fal.ai Seedance 1.5 Pro

### Установка
```bash
pip install fal-client
```

### Аутентификация
Переменная окружения `FAL_KEY` — автоматически подхватывается клиентом.

### Эндпоинты
- **Text-to-video**: `fal-ai/bytedance/seedance/v1.5/pro/text-to-video`
- **Image-to-video**: `fal-ai/bytedance/seedance/v1.5/pro/image-to-video`

### Пример text-to-video (Python)
```python
import fal_client

result = fal_client.subscribe(
    "fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
    arguments={
        "prompt": "A golden retriever playing fetch in a park at sunset, slow motion",
        "duration": "5",           # "5" | "8" | "10"
        "resolution": "720p",      # "720p" | "1080p"
        "aspect_ratio": "16:9",    # "16:9" | "9:16" | "1:1" | "4:3" | "3:4"
        "generate_audio": True,    # нативная генерация аудио
        "enable_safety_checker": True
    }
)
# result = {"video": {"url": "https://..."}, "seed": 42}
video_url = result["video"]["url"]
```

### Пример image-to-video (Python)
```python
result = fal_client.subscribe(
    "fal-ai/bytedance/seedance/v1.5/pro/image-to-video",
    arguments={
        "prompt": "The character starts walking forward slowly",
        "image_url": "https://publicly-accessible-url.com/image.jpg",
        "duration": "5",
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "generate_audio": True,
        "enable_safety_checker": True
    }
)
video_url = result["video"]["url"]
```

### Загрузка файлов на fal storage (для image-to-video)
```python
# Загрузка локального файла → получение публичного URL
url = fal_client.upload_file("path/to/image.jpg")
# или из bytes
url = fal_client.upload("image.jpg", image_bytes)
```

### Важные детали
- `subscribe()` — блокирующий (sync). Для async использовать `asyncio.to_thread()`
- Генерация занимает 30-120 секунд в зависимости от параметров
- Цена: ~$0.26 за 720p 5с видео с аудио
- Telegram лимит на отправку видео: 50 MB
- Ответ всегда содержит URL на .mp4 файл

## Технические требования

### 1. Создать `src/services/video_gen.py`
По аналогии с `src/services/image_gen.py`:
- `init_video_client()` — инициализация (проверка FAL_KEY)
- `get_video_client()` — проверка доступности
- `generate_video(prompt, duration, resolution, aspect_ratio, generate_audio) -> str | dict` — text-to-video, возвращает `{"url": ..., "seed": ...}` или строку ошибки
- `generate_video_from_image(prompt, image_url, ...) -> str | dict` — image-to-video
- `upload_image_to_fal(image_bytes, filename) -> str` — загрузка фото на fal storage
- Все вызовы fal_client через `asyncio.to_thread()` (он sync)
- Retry с backoff при RateLimitError (макс 3 попытки)
- Человекочитаемые ошибки на русском

### 2. Создать `src/handlers/video.py`
Router с:
- `/video <промпт>` — быстрая генерация (16:9, 5с, 720p, аудио вкл)
- `/video` без аргумента — запуск wizard
- Обработка фото с подписью `/video` — image-to-video
- Wizard через FSM (aiogram states) или callback_data
- Прогресс-сообщение: "🎬 Генерирую видео... ⏳ ~30-60 сек" с периодическим обновлением
- Скачивание видео по URL → отправка через `answer_video` (BufferedInputFile)
- Если видео > 50MB → отправить ссылкой
- Per-user lock (как в messages.py) — один видео-запрос за раз
- Шаг "улучшение промпта с AI": отправить промпт пользователя в Claude с системным промптом для улучшения видео-промптов, показать оба варианта кнопками

### 3. Обновить существующие файлы
- `config/settings.py` — добавить `fal_api_key`, эндпоинты моделей
- `.env.example` — добавить `FAL_KEY`
- `src/handlers/__init__.py` — зарегистрировать `video_router` (перед messages_router)
- `src/main.py` — вызвать `init_video_client()` при старте
- `src/handlers/commands.py` — добавить `/video` в /help
- `requirements.txt` — добавить `fal-client>=0.5.0,<1.0.0`

### 4. Миграция `alembic/versions/006_add_video_generations.py`
Таблица `video_generations`:
- id SERIAL PK
- user_id BIGINT FK→users
- prompt TEXT
- mode VARCHAR(20) — 'text-to-video' / 'image-to-video'
- duration VARCHAR(5)
- resolution VARCHAR(10)
- aspect_ratio VARCHAR(10)
- video_url TEXT
- seed INTEGER
- created_at TIMESTAMP DEFAULT NOW()

Safety-net CREATE TABLE в `connection.py`.

### 5. Тесты в `tests/test_video.py`
По аналогии с test_services.py:
- Мок fal_client.subscribe
- Тест generate_video с успешным результатом
- Тест generate_video с ошибками (rate limit, validation)
- Тест generate_video_from_image
- Тест upload_image_to_fal
- Тест хендлера /video с аргументом
- Тест wizard flow

## Паттерны проекта (ОБЯЗАТЕЛЬНО соблюдать)

1. **parse_mode=None** для всех сообщений от бота
2. **Per-user lock** через `_user_locks[user_id]` (asyncio.Lock)
3. **Logging**: `logger = logging.getLogger(__name__)` в каждом модуле
4. **Type hints** везде
5. **Русский язык** в пользовательских сообщениях
6. **Ошибки** — человекочитаемые, без traceback пользователю
7. **Handler registration** — video_router ПЕРЕД messages_router (catch-all)
8. **Зависимости** — `>=X.Y.Z,<X+1.0.0` формат в requirements.txt
9. **exc_info=True** для unexpected exceptions в логах

## План работы
1. Начни с подключения к серверу и проверки что всё работает
2. Следуй TODO.md пофазово
3. После каждой задачи — коммит в репозиторий
4. Начни с Phase 1: `src/services/video_gen.py` + простой `/video <prompt>` команды
5. Затем wizard и image-to-video
6. В конце — миграция и тесты
