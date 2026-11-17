"""Клавиатуры админ-панели. Все callback_data короткие (< 64 байт)."""
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup as M


def _b(text: str, data: str) -> B:
    return B(text=text, callback_data=data)


def admin_menu() -> M:
    return M(inline_keyboard=[
        [_b("📤 Загрузить файл", "adm:upload")],
        [_b("📋 Список публикаций", "adm:list:0")],
        [_b("📊 Статистика", "adm:stats")],
        [_b("⚙️ Настройки", "adm:settings")],
    ])


def cancel_kb() -> M:
    return M(inline_keyboard=[[_b("❌ Отмена", "adm:cancel")]])


def back_menu_kb() -> M:
    return M(inline_keyboard=[[_b("🛠 В меню", "adm:menu")]])


def created_kb(link: str, title: str) -> M:
    share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(title, safe='')}"
    return M(inline_keyboard=[
        [B(text="📤 Поделиться", url=share)],
        [_b("📋 Список", "adm:list:0"), _b("🛠 Меню", "adm:menu")],
    ])


def list_kb(items: list[dict], page: int, pages: int) -> M:
    rows = []
    for p in items:
        i = p["id"]
        rows.append([
            _b(f"🔗 #{i}", f"pub:link:{i}"),
            _b(f"📊 #{i}", f"pub:stat:{i}:{page}"),
            _b(f"🗑 #{i}", f"pub:del:{i}:{page}"),
        ])
    nav = []
    if page > 0:
        nav.append(_b("⬅️", f"adm:list:{page - 1}"))
    nav.append(_b(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        nav.append(_b("➡️", f"adm:list:{page + 1}"))
    rows.append(nav)
    rows.append([_b("🛠 В меню", "adm:menu")])
    return M(inline_keyboard=rows)


def confirm_delete_kb(pub_id: int, page: int) -> M:
    return M(inline_keyboard=[[
        _b("✅ Да, удалить", f"pub:delyes:{pub_id}:{page}"),
        _b("❌ Нет", f"adm:list:{page}"),
    ]])


def pub_stat_kb(page: int) -> M:
    return M(inline_keyboard=[[_b("⬅️ К списку", f"adm:list:{page}")]])


def settings_kb(enabled: bool) -> M:
    toggle = "🔕 Выключить проверку подписки" if enabled else "🔔 Включить проверку подписки"
    return M(inline_keyboard=[
        [_b(toggle, "set:toggle")],
        [_b("📢 Сменить канал", "set:channel")],
        [_b("🛠 В меню", "adm:menu")],
    ])


def skip_photo_kb() -> M:
    return M(inline_keyboard=[
        [_b("⏭ Пропустить", "adm:skipphoto")],
        [_b("❌ Отмена", "adm:cancel")],
    ])
