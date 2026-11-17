"""Админ-панель: загрузка файлов, список, статистика, настройки."""
import logging
from datetime import datetime
from html import escape
from math import ceil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import Config, parse_channel_id
from database import Database
from filters import IsAdmin
from keyboards.admin_kb import (
    admin_menu, back_menu_kb, cancel_kb, confirm_delete_kb, created_kb,
    list_kb, pub_stat_kb, settings_kb, skip_photo_kb,
)
from middlewares.subscription import load_sub_settings

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE_SIZE = 5
ADMIN_TEXT = "🛠 <b>Админ-панель</b>\nВыберите действие:"


class UploadStates(StatesGroup):
    waiting_file = State()
    waiting_photo = State()    # необязательная обложка
    waiting_title = State()


class SettingsStates(StatesGroup):
    waiting_channel = State()


# ---------- Вспомогательные функции ----------
async def safe_edit(message: Message, text: str, kb=None) -> None:
    """edit_text, игнорирующий ошибку «message is not modified»."""
    try:
        await message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def build_links(bot: Bot, code: str) -> tuple[str, str]:
    me = await bot.me()
    return (f"https://t.me/{me.username}?start={code}",
            f"tg://resolve?domain={me.username}&start={code}")


def extract_file(message: Message) -> tuple[str, str, str | None] | None:
    """Возвращает (тип, file_id, имя файла). animation проверяем раньше document!"""
    if message.animation:
        return "animation", message.animation.file_id, message.animation.file_name
    if message.document:
        return "document", message.document.file_id, message.document.file_name
    if message.photo:
        return "photo", message.photo[-1].file_id, None
    if message.video:
        return "video", message.video.file_id, message.video.file_name
    if message.audio:
        return "audio", message.audio.file_id, message.audio.title or message.audio.file_name
    if message.voice:
        return "voice", message.voice.file_id, None
    return None


def pick_thumb(photos):
    """Размер фото, подходящий для thumbnail: ≤320 px, самый большой из таких."""
    fit = [p for p in photos if max(p.width, p.height) <= 320]
    return max(fit, key=lambda p: p.width * p.height) if fit else photos[0]


async def ask_title(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(UploadStates.waiting_title)
    cover = "🖼 Обложка: добавлена" if data.get("photo_file_id") else "🖼 Обложка: без неё"
    await message.answer(
        f"{cover}\n\nВведите название публикации или отправьте /skip, "
        f"чтобы использовать:\n<code>{escape(data['default_title'])}</code>",
        reply_markup=cancel_kb(),
    )


def short(text: str, n: int = 40) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


async def render_list(db: Database, page: int):
    total = await db.count_publications()
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    if total == 0:
        return "📋 Публикаций пока нет.", back_menu_kb()
    items = await db.list_publications(page * PAGE_SIZE, PAGE_SIZE)
    lines = [f"📋 <b>Публикации</b> (стр. {page + 1}/{pages})\n"]
    for p in items:
        lines.append(
            f"<b>#{p['id']}</b> | {escape(short(p['title']))} | "
            f"👁 {p['views']} | 👤 {p['uniques']} | {p['created_at'][:10]}"
        )
    return "\n".join(lines), list_kb(items, page, pages)


# ---------- Меню / отмена ----------
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_TEXT, reply_markup=admin_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:menu")
async def cb_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(call.message, ADMIN_TEXT, admin_menu())
    await call.answer()


@router.callback_query(F.data == "adm:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(call.message, "Действие отменено.\n\n" + ADMIN_TEXT, admin_menu())
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


# ---------- Список ----------
@router.message(Command("list"))
async def cmd_list(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    text, kb = await render_list(db, 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("adm:list:"))
async def cb_list(call: CallbackQuery, db: Database) -> None:
    page = int(call.data.split(":")[2])
    text, kb = await render_list(db, page)
    await safe_edit(call.message, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("pub:link:"))
async def cb_pub_link(call: CallbackQuery, db: Database, bot: Bot) -> None:
    pub = await db.get_by_id(int(call.data.split(":")[2]))
    if not pub:
        await call.answer("Публикация не найдена", show_alert=True)
        return
    link, deep = await build_links(bot, pub["code"])
    await call.message.answer(
        f"🔗 <b>#{pub['id']}</b> {escape(pub['title'])}\n\n"
        f"Ссылка:\n<code>{link}</code>\n\nDeep-link:\n<code>{deep}</code>",
        reply_markup=created_kb(link, pub["title"]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pub:stat:"))
async def cb_pub_stat(call: CallbackQuery, db: Database) -> None:
    _, _, pub_id, page = call.data.split(":")
    pub = await db.get_by_id(int(pub_id))
    if not pub:
        await call.answer("Публикация не найдена", show_alert=True)
        return
    repeats = pub["views"] - pub["uniques"]
    await safe_edit(
        call.message,
        f"📊 <b>#{pub['id']}</b> {escape(pub['title'])}\n\n"
        f"Тип: {pub['file_type']}\nКод: <code>{pub['code']}</code>\n"
        f"Создано (UTC): {pub['created_at']}\n\n"
        f"👁 Переходов: <b>{pub['views']}</b>\n"
        f"👤 Уникальных: <b>{pub['uniques']}</b>\n"
        f"🔁 Повторных: <b>{repeats}</b>",
        pub_stat_kb(int(page)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pub:del:"))
async def cb_pub_del(call: CallbackQuery, db: Database) -> None:
    _, _, pub_id, page = call.data.split(":")
    pub = await db.get_by_id(int(pub_id))
    if not pub:
        await call.answer("Публикация не найдена", show_alert=True)
        return
    await safe_edit(
        call.message,
        f"🗑 Удалить публикацию <b>#{pub['id']}</b> «{escape(pub['title'])}»?\n"
        "Ссылка перестанет работать, статистика будет удалена.",
        confirm_delete_kb(pub["id"], int(page)),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pub:delyes:"))
async def cb_pub_delyes(call: CallbackQuery, db: Database) -> None:
    _, _, pub_id, page = call.data.split(":")
    ok = await db.delete_publication(int(pub_id))
    await call.answer("Удалено ✅" if ok else "Уже удалена", show_alert=False)
    text, kb = await render_list(db, int(page))
    await safe_edit(call.message, text, kb)


# ---------- Статистика ----------
@router.callback_query(F.data == "adm:stats")
async def cb_stats(call: CallbackQuery, db: Database) -> None:
    t = await db.totals()
    top = await db.top_publications(30)
    lines = [
        "📊 <b>Статистика</b>\n",
        f"Публикаций: <b>{t['publications']}</b>",
        f"Всего переходов: <b>{t['views']}</b>",
        f"Уникальных пользователей: <b>{t['users']}</b>",
    ]
    if top:
        lines.append("\n<b>По публикациям</b> (переходы / уникальные):")
        for p in top:
            lines.append(f"#{p['id']} {escape(short(p['title'], 30))} — {p['views']} / {p['uniques']}")
        if t["publications"] > len(top):
            lines.append(f"… и ещё {t['publications'] - len(top)}")
    await safe_edit(call.message, "\n".join(lines), back_menu_kb())
    await call.answer()


# ---------- Настройки ----------
async def render_settings(db: Database, config: Config):
    s = await load_sub_settings(db, config)
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Проверка подписки: <b>{'включена ✅' if s.enabled else 'выключена ❌'}</b>\n"
        f"Канал: <code>{s.channel_id or '—'}</code>\n"
        f"Ссылка: {escape(s.channel_url) if s.channel_url else '—'}"
    )
    return text, settings_kb(s.enabled)


@router.callback_query(F.data == "adm:settings")
async def cb_settings(call: CallbackQuery, db: Database, config: Config, state: FSMContext) -> None:
    await state.clear()
    text, kb = await render_settings(db, config)
    await safe_edit(call.message, text, kb)
    await call.answer()


@router.callback_query(F.data == "set:toggle")
async def cb_toggle(call: CallbackQuery, db: Database, config: Config) -> None:
    s = await load_sub_settings(db, config)
    await db.set_setting("check_subscription", "0" if s.enabled else "1")
    text, kb = await render_settings(db, config)
    await safe_edit(call.message, text, kb)
    await call.answer("Сохранено")


@router.callback_query(F.data == "set:channel")
async def cb_channel(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_channel)
    await safe_edit(
        call.message,
        "Отправьте @username канала или его числовой ID (-100…).\n"
        "Бот должен быть администратором этого канала.",
        cancel_kb(),
    )
    await call.answer()


@router.message(SettingsStates.waiting_channel, F.text)
async def on_channel(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    chat_ref = parse_channel_id(message.text)
    try:
        chat = await bot.get_chat(chat_ref)
    except TelegramAPIError as e:
        await message.answer(f"❌ Канал не найден: {escape(str(e))}\nПопробуйте ещё раз или /cancel.")
        return

    warn = ""
    try:
        me = await bot.me()
        bm = await bot.get_chat_member(chat.id, me.id)
        if bm.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            warn = "\n⚠️ Бот не администратор канала — проверка подписки не будет работать."
    except TelegramAPIError:
        warn = "\n⚠️ Не удалось проверить права бота в канале."

    url = f"https://t.me/{chat.username}" if chat.username else chat.invite_link
    if not url:
        try:
            url = await bot.export_chat_invite_link(chat.id)
        except TelegramAPIError:
            url = None
    await db.set_setting("channel_id", str(chat.id))
    if url:
        await db.set_setting("channel_url", url)
    else:
        warn += "\n⚠️ Не удалось получить ссылку на канал — останется прежняя."
    await state.clear()
    await message.answer(f"✅ Канал сохранён: <b>{escape(chat.title or str(chat.id))}</b>{warn}",
                         reply_markup=admin_menu())


# ---------- Загрузка файла ----------
@router.callback_query(F.data == "adm:upload")
async def cb_upload(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UploadStates.waiting_file)
    await safe_edit(
        call.message,
        "📤 Пришлите файл (документ, фото, видео, аудио, голосовое или GIF).\n"
        "Файл не скачивается — сохраняется только его file_id.",
        cancel_kb(),
    )
    await call.answer()


MEDIA = F.document | F.photo | F.video | F.audio | F.voice | F.animation


# Админ может просто прислать файл — загрузка начнётся и без кнопки
@router.message(StateFilter(None, UploadStates.waiting_file), MEDIA)
async def on_file(message: Message, state: FSMContext) -> None:
    file_type, file_id, name = extract_file(message)
    default = (name or f"Публикация от {datetime.now():%d.%m.%Y %H:%M}")[:200]
    await state.update_data(file_id=file_id, file_type=file_type,
                            default_title=default, photo_file_id=None)
    await state.set_state(UploadStates.waiting_photo)
    await message.answer(
        f"✅ Файл принят (<b>{file_type}</b>).\n\n"
        "🖼 Пришлите <b>фото-обложку</b> (отправьте как фото, не как файл) "
        "или нажмите «Пропустить».",
        reply_markup=skip_photo_kb(),
    )


@router.message(UploadStates.waiting_file)
async def on_file_wrong(message: Message) -> None:
    await message.answer("Пришлите файл (не текст) или нажмите «Отмена» / /cancel.")


@router.message(UploadStates.waiting_photo, F.photo)
async def on_cover(message: Message, state: FSMContext) -> None:
    await state.update_data(photo_file_id=pick_thumb(message.photo).file_id)
    await ask_title(message, state)


@router.callback_query(UploadStates.waiting_photo, F.data == "adm:skipphoto")
async def on_skip_cover(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photo_file_id=None)   # в БД запишется NULL
    await call.answer("Обложка пропущена")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await ask_title(call.message, state)


@router.message(UploadStates.waiting_photo)
async def on_cover_wrong(message: Message) -> None:
    await message.answer("Пришлите обложку <b>как фото</b> или нажмите «⏭ Пропустить».",
                         reply_markup=skip_photo_kb())


@router.message(UploadStates.waiting_title, F.text)
async def on_title(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    data = await state.get_data()
    text = message.text.strip()
    if text.lower().split("@")[0] == "/skip":
        title = data["default_title"]
    elif text.startswith("/"):
        await message.answer("Название не должно начинаться с «/». Введите название или /skip.")
        return
    else:
        title = text[:200]

    pub_id, code = await db.create_publication(
        data["file_id"], data["file_type"], title, data.get("photo_file_id")
    )
    await state.clear()
    link, deep = await build_links(bot, code)
    logger.info("Создана публикация #%s (%s) код=%s", pub_id, data["file_type"], code)
    await message.answer(
        f"✅ Публикация <b>#{pub_id}</b> создана: {escape(title)}\n\n"
        f"🔗 Реферальная ссылка:\n<code>{link}</code>\n\n"
        f"📎 Deep-link:\n<code>{deep}</code>",
        reply_markup=created_kb(link, title),
    )


@router.message(UploadStates.waiting_title)
async def on_title_wrong(message: Message) -> None:
    await message.answer("Введите название текстом или /skip.")
