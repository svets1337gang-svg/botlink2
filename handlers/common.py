"""Общие хендлеры: /help, ответ на неизвестные сообщения, обработка ошибок."""
import logging

from aiogram import Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, ExceptionTypeFilter
from aiogram.types import ErrorEvent, Message

import texts
from config import Config

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    if message.from_user.id == config.admin_id:
        await message.answer(
            "/admin — админ-панель\n/list — список публикаций\n/cancel — отмена действия\n"
            "Просто пришлите файл, чтобы создать публикацию."
        )
    else:
        await message.answer(texts.HELP_USER)


@router.message()
async def fallback(message: Message, config: Config) -> None:
    if message.from_user.id == config.admin_id:
        await message.answer("Не понял. Откройте панель: /admin")
    else:
        await message.answer(texts.FALLBACK_USER)


@router.error(ExceptionTypeFilter(TelegramForbiddenError))
async def on_forbidden(event: ErrorEvent) -> bool:
    # Пользователь заблокировал бота — это не ошибка бота
    logger.warning("Бот заблокирован пользователем / нет прав: %s", event.exception)
    return True


@router.error()
async def on_error(event: ErrorEvent) -> bool:
    logger.error("Необработанная ошибка: %s", event.exception, exc_info=event.exception)
    return True
