"""Клавиатуры для обычных пользователей."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import texts


def main_menu(channel_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    url = texts.CHANNEL_LINK or channel_url
    if url:
        rows.append([InlineKeyboardButton(text=texts.BTN_CHANNEL, url=url)])
    rows.append([InlineKeyboardButton(text=texts.BTN_BUY, url=texts.WILDCLIENT_URL)])
    rows.append([InlineKeyboardButton(text=texts.BTN_ABOUT, callback_data="about")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscribe_kb(channel_url: str | None, code: str | None) -> InlineKeyboardMarkup:
    rows = []
    if channel_url:
        rows.append([InlineKeyboardButton(text=texts.BTN_SUBSCRIBE, url=channel_url)])
    # callback_data: «chk:<код>» (до 64 байт; «-» если кода нет)
    rows.append([InlineKeyboardButton(text=texts.BTN_CHECK, callback_data=f"chk:{code or '-'}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
