"""Проверка подписки на канал + middleware для пользовательских хендлеров."""
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

import texts
from config import Config, parse_channel_id
from database import Database
from keyboards.user_kb import subscribe_kb

logger = logging.getLogger(__name__)
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

SUBSCRIBED_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


@dataclass
class SubSettings:
    enabled: bool
    channel_id: int | str
    channel_url: str


async def load_sub_settings(db: Database, config: Config) -> SubSettings:
    """Настройки подписки: значения из БД (если менялись в админке) иначе из .env."""
    enabled_raw = await db.get_setting("check_subscription")
    enabled = config.check_subscription if enabled_raw is None else enabled_raw == "1"
    cid_raw = await db.get_setting("channel_id")
    channel_id = parse_channel_id(cid_raw) if cid_raw else config.channel_id
    channel_url = await db.get_setting("channel_url") or config.channel_url
    return SubSettings(enabled, channel_id, channel_url)


async def is_subscribed(bot: Bot, channel_id: int | str, user_id: int) -> bool | None:
    """True/False — статус подписки; None — не удалось проверить (ошибка API/настроек)."""
    if not channel_id:
        logger.error("Проверка подписки включена, но канал не задан")
        return None
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except TelegramAPIError as e:
        logger.error("get_chat_member(%s, %s) не удался: %s (бот должен быть админом канала)",
                     channel_id, user_id, e)
        return None
    if member.status in SUBSCRIBED_STATUSES:
        return True
    if member.status == ChatMemberStatus.RESTRICTED:  # ограничен, но может оставаться участником
        return bool(getattr(member, "is_member", False))
    return False  # left / kicked


class SubscriptionMiddleware(BaseMiddleware):
    """Не пускает неподписанных пользователей к хендлерам; админ не проверяется."""

    def __init__(self, db: Database, config: Config) -> None:
        self.db = db
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id == self.config.admin_id:
            return await handler(event, data)
        # Кнопки «Я подписался» и «О боте» подписку не требуют
        if isinstance(event, CallbackQuery) and (event.data or "").startswith(("chk:", "about")):
            return await handler(event, data)
        # /start без кода — главное меню доступно всем
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            if len(event.text.split(maxsplit=1)) == 1:
                return await handler(event, data)

        sub = await load_sub_settings(self.db, self.config)
        if not sub.enabled:
            return await handler(event, data)

        status = await is_subscribed(data["bot"], sub.channel_id, user.id)
        if status:
            return await handler(event, data)

        target = event if isinstance(event, Message) else getattr(event, "message", None)
        if status is None:
            if isinstance(event, CallbackQuery):
                await event.answer(texts.CHECK_FAILED_ALERT, show_alert=True)
            elif target:
                await target.answer(texts.ERR_CHECK)
            return None

        # Достаём код из /start <код>, чтобы кнопка «Я подписался» выдала нужный файл
        code = None
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            parts = event.text.split(maxsplit=1)
            if len(parts) > 1 and CODE_RE.match(parts[1].strip()):
                code = parts[1].strip()

        text = texts.SUBSCRIBE_TEXT
        if target:
            await target.answer(text, reply_markup=subscribe_kb(sub.channel_url, code))
        if isinstance(event, CallbackQuery):
            await event.answer()
        return None
