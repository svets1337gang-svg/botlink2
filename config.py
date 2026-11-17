"""Конфигурация бота: чтение переменных окружения из .env."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    channel_id: int | str
    channel_url: str
    db_path: str
    check_subscription: bool


def parse_channel_id(raw: str) -> int | str:
    """Приводит ID канала к int (-100...) либо к @username."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw if raw.startswith("@") else f"@{raw}"


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y", "да"}


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    if not token:
        raise RuntimeError("В .env не задан BOT_TOKEN")
    if not admin_raw.lstrip("-").isdigit():
        raise RuntimeError("В .env не задан корректный ADMIN_ID (число)")

    config = Config(
        bot_token=token,
        admin_id=int(admin_raw),
        channel_id=parse_channel_id(os.getenv("CHANNEL_ID", "")),
        channel_url=os.getenv("CHANNEL_URL", "").strip(),
        db_path=os.getenv("DB_PATH", "bot.db").strip() or "bot.db",
        check_subscription=_to_bool(os.getenv("CHECK_SUBSCRIPTION"), False),
    )
    if config.check_subscription and not config.channel_id:
        raise RuntimeError("CHECK_SUBSCRIPTION=true, но CHANNEL_ID не задан в .env")
    return config
