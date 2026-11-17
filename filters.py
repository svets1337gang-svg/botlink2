"""Общие фильтры."""
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from config import Config


class IsAdmin(BaseFilter):
    """Пропускает только администратора (ADMIN_ID из .env)."""

    async def __call__(self, event: TelegramObject, config: Config) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id == config.admin_id)
