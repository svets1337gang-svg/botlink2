"""Хендлеры обычных пользователей: меню, выдача файла по реферальной ссылке."""
import logging
import os
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message

import texts
from config import Config
from database import Database
from keyboards.user_kb import main_menu
from middlewares.subscription import CODE_RE, is_subscribed, load_sub_settings

logger = logging.getLogger(__name__)
router = Router(name="user")

# тип файла -> (метод бота, имя параметра с file_id)
SEND_METHODS = {
    "document": ("send_document", "document"),
    "photo": ("send_photo", "photo"),
    "video": ("send_video", "video"),
    "audio": ("send_audio", "audio"),
    "voice": ("send_voice", "voice"),
    "animation": ("send_animation", "animation"),
}

_thumb_cache: dict[str, bytes] = {}   # photo_file_id -> JPEG-байты миниатюры
_banner_file_id: str | None = None    # после первой отправки баннера используем file_id


async def _load_thumb(bot: Bot, photo_file_id: str) -> BufferedInputFile | None:
    """thumbnail нельзя передать как file_id — скачиваем и загружаем заново."""
    data = _thumb_cache.get(photo_file_id)
    if data is None:
        try:
            buf = await bot.download(photo_file_id)
            data = buf.getvalue() if buf else None
        except TelegramAPIError as e:
            logger.warning("Не удалось скачать обложку %s: %s", photo_file_id, e)
            return None
        if not data or len(data) > 200 * 1024:  # лимит Telegram для thumbnail
            return None
        _thumb_cache[photo_file_id] = data
    return BufferedInputFile(data, filename="cover.jpg")


async def send_publication(bot: Bot, chat_id: int, pub: dict) -> None:
    caption = texts.FILE_CAPTION.format(title=escape(pub["title"]))

    # Документ + обложка (thumbnail)
    if pub["file_type"] == "document" and pub.get("photo_file_id"):
        thumb = await _load_thumb(bot, pub["photo_file_id"])
        if thumb:
            try:
                await bot.send_document(chat_id=chat_id, document=pub["file_id"],
                                        thumbnail=thumb, caption=caption)
                return
            except TelegramBadRequest as e:
                logger.warning("Отправка с thumbnail не удалась (#%s): %s", pub["id"], e)
                # идём дальше — отправим без обложки

    # Без обложки (или другой тип файла)
    method, param = SEND_METHODS[pub["file_type"]]
    await getattr(bot, method)(chat_id=chat_id, **{param: pub["file_id"]}, caption=caption)


async def deliver(bot: Bot, db: Database, config: Config, user_id: int, code: str) -> str | None:
    """Отправляет файл. Возвращает текст ошибки для пользователя или None."""
    if not CODE_RE.match(code):
        return texts.ERR_NOT_FOUND
    pub = await db.get_by_code(code)
    if not pub:
        return texts.ERR_NOT_FOUND
    try:
        await send_publication(bot, user_id, pub)
    except TelegramForbiddenError:
        logger.warning("Пользователь %s заблокировал бота — файл не отправлен", user_id)
        return None
    except TelegramBadRequest as e:
        # file_id больше недействителен (файл удалён с серверов Telegram и т.п.)
        logger.error("Не удалось отправить публикацию #%s: %s", pub["id"], e)
        try:
            await bot.send_message(
                config.admin_id,
                f"⚠️ Публикация <b>#{pub['id']}</b> «{escape(pub['title'])}» недоступна: "
                f"{escape(str(e))}\nЗагрузите файл заново.",
            )
        except TelegramAPIError:
            pass
        return texts.ERR_FILE_UNAVAILABLE
    # Считаем переход только после успешной отправки
    await db.register_view(pub["id"], user_id)
    return None


def _banner():
    if _banner_file_id:
        return _banner_file_id
    src = texts.WELCOME_PHOTO
    return FSInputFile(src) if src and os.path.isfile(src) else src


async def send_main_menu(message: Message, config: Config) -> None:
    global _banner_file_id
    caption = texts.WELCOME_TEXT
    if message.from_user.id == config.admin_id:
        caption += texts.ADMIN_HINT
    kb = main_menu(config.channel_url)
    try:
        sent = await message.answer_photo(photo=_banner(), caption=caption, reply_markup=kb)
        _banner_file_id = sent.photo[-1].file_id
    except (TelegramBadRequest, FileNotFoundError, TypeError) as e:
        logger.error("Не удалось отправить баннер (%s) — шлём текстом", e)
        await message.answer(caption, reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot,
                    db: Database, config: Config) -> None:
    code = (command.args or "").strip()
    if not code:
        await send_main_menu(message, config)
        return
    error = await deliver(bot, db, config, message.from_user.id, code)
    if error:
        await message.answer(error)


@router.callback_query(F.data == "about")
async def cb_about(call: CallbackQuery) -> None:
    await call.answer(texts.ABOUT_ALERT, show_alert=True)


@router.callback_query(F.data.startswith("chk:"))
async def cb_check(call: CallbackQuery, bot: Bot, db: Database, config: Config) -> None:
    code = call.data.split(":", 1)[1]
    user_id = call.from_user.id
    sub = await load_sub_settings(db, config)
    if sub.enabled and user_id != config.admin_id:
        status = await is_subscribed(bot, sub.channel_id, user_id)
        if status is None:
            await call.answer(texts.CHECK_FAILED_ALERT, show_alert=True)
            return
        if not status:
            await call.answer(texts.NOT_SUBSCRIBED_ALERT, show_alert=True)
            return
    await call.answer(texts.THANKS_ALERT)
    try:
        await call.message.delete()
    except TelegramAPIError:
        pass
    if code == "-":
        await bot.send_message(user_id, texts.SUBSCRIBED_NO_CODE)
        return
    error = await deliver(bot, db, config, user_id, code)
    if error:
        await bot.send_message(user_id, error)
