import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _parse_allowed_users() -> list[str]:
    """Parse ALLOWED_USERS from env: supports both numeric IDs and usernames."""
    raw = os.getenv("ALLOWED_USERS", "")
    return [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]


@dataclass
class Settings:
    # Telegram
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096

    # OpenAI (fallback)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = "gpt-5.2"

    # Google GenAI (image generation)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    image_model: str = "imagen-4.0-generate-001"

    # Database
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://bot:bot_password@localhost:5432/telegram_bot"
    )

    # Context settings
    max_context_messages: int = 20
    max_message_length: int = 4096  # Telegram limit

    # Access control: comma-separated Telegram IDs and/or usernames
    # Empty = unrestricted access
    allowed_users: list[str] = field(default_factory=_parse_allowed_users)

    # Rate limiting per user
    rate_limit_messages: int = int(os.getenv("RATE_LIMIT_MESSAGES", "10"))
    rate_limit_window: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds

    # Messages auto-cleanup: delete messages older than N days (0 = disabled)
    messages_ttl_days: int = int(os.getenv("MESSAGES_TTL_DAYS", "30"))

    # Voice transcription
    whisper_model: str = "whisper-1"

    # Streaming: interval between message edits (seconds)
    stream_edit_interval: float = 1.5

    def __post_init__(self) -> None:
        # Pre-compute lowercase usernames for case-insensitive matching
        self.allowed_users_lower: list[str] = [
            u.lower() for u in self.allowed_users if not u.isdigit()
        ]

    def validate(self) -> None:
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")


settings = Settings()
