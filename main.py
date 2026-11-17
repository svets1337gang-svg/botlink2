"""Точка входа: запуск бота (long polling)."""
import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from config import load_config
from database import Database
from handlers import admin, common, user
from middlewares.subscription import SubscriptionMiddleware


def setup_logging() -> None:
    """Логирование одновременно в консоль и в файл bot.log (с ротацией)."""
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file = RotatingFileHandler("bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(file)


async def main() -> None:
    setup_logging()
    log = logging.getLogger("main")
    config = load_config()

    db = Database(config.db_path)
    await db.connect()

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    # Зависимости, доступные в хендлерах по имени параметра
    dp["db"] = db
    dp["config"] = config

    # Проверка подписки — только для пользовательского роутера (админ пропускается внутри)
    mw = SubscriptionMiddleware(db, config)
    user.router.message.middleware(mw)
    user.router.callback_query.middleware(mw)

    # Порядок важен: админ -> пользователь -> общий (fallback)
    dp.include_routers(admin.router, user.router, common.router)

    try:
        await bot.set_my_commands([BotCommand(command="start", description="Начать")])
        await bot.set_my_commands(
            [BotCommand(command="admin", description="Админ-панель"),
             BotCommand(command="list", description="Список публикаций"),
             BotCommand(command="cancel", description="Отмена действия")],
            scope=BotCommandScopeChat(chat_id=config.admin_id),
        )
    except Exception as e:  # например, админ ещё не писал боту
        log.warning("Не удалось установить команды: %s", e)

    me = await bot.me()
    log.info("Бот запущен: @%s", me.username)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()
        log.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
