import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Telegram
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    local_bot_api_url: str | None = os.getenv("LOCAL_BOT_API_URL")

    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096

    # Database
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://bot:bot_password@localhost:5432/telegram_bot"
    )

    # Context settings
    max_context_messages: int = 20
    max_message_length: int = 4096  # Telegram limit

    def validate(self) -> None:
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")


settings = Settings()
