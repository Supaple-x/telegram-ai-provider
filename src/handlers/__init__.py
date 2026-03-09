from src.handlers.commands import router as commands_router
from src.handlers.messages import router as messages_router
from src.handlers.image import router as image_router
from src.handlers.voice import router as voice_router
from src.handlers.search import router as search_router
from src.handlers.memory import router as memory_router
from src.handlers.video import router as video_router
from src.handlers.auth import router as auth_router

__all__ = [
    "commands_router",
    "messages_router",
    "image_router",
    "voice_router",
    "search_router",
    "memory_router",
    "video_router",
    "auth_router",
]
