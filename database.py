"""Работа с SQLite через aiosqlite."""
import asyncio
import logging
import secrets
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  file_id TEXT NOT NULL,
  file_type TEXT NOT NULL,
  photo_file_id TEXT,
  title TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  views INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS publication_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  publication_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(publication_id, user_id),
  FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

# Выборка публикации вместе со счётчиком уникальных пользователей
PUB_SELECT = (
    "SELECT p.*, "
    "(SELECT COUNT(*) FROM publication_users u WHERE u.publication_id = p.id) AS uniques "
    "FROM publications p"
)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()  # сериализуем записи

    async def connect(self) -> None:
        Path(self.path).resolve().parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")  # нужно для ON DELETE CASCADE
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        # Миграция старых баз: колонка обложки
        async with self._conn.execute("PRAGMA table_info(publications)") as cur:
            cols = {row["name"] for row in await cur.fetchall()}
        if "photo_file_id" not in cols:
            await self._conn.execute("ALTER TABLE publications ADD COLUMN photo_file_id TEXT")
            logger.info("Миграция: добавлена колонка photo_file_id")
        await self._conn.commit()
        logger.info("База данных подключена: %s", self.path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "База не подключена"
        return self._conn

    # ---------- Настройки ----------
    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        async with self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            await self.conn.commit()

    # ---------- Публикации ----------
    async def create_publication(self, file_id: str, file_type: str, title: str,
                                 photo_file_id: str | None = None) -> tuple[int, str]:
        """Создаёт публикацию с уникальным кодом. Возвращает (id, code)."""
        async with self._lock:
            for _ in range(10):
                code = secrets.token_urlsafe(8)
                try:
                    cur = await self.conn.execute(
                        "INSERT INTO publications(code, file_id, file_type, photo_file_id, title) "
                        "VALUES(?, ?, ?, ?, ?)",
                        (code, file_id, file_type, photo_file_id, title),
                    )
                    await self.conn.commit()
                    return cur.lastrowid, code
                except aiosqlite.IntegrityError:
                    await self.conn.rollback()  # коллизия кода — пробуем снова
        raise RuntimeError("Не удалось сгенерировать уникальный код")

    async def get_by_code(self, code: str) -> dict | None:
        async with self.conn.execute(PUB_SELECT + " WHERE p.code = ?", (code,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_id(self, pub_id: int) -> dict | None:
        async with self.conn.execute(PUB_SELECT + " WHERE p.id = ?", (pub_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def count_publications(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) AS c FROM publications") as cur:
            return (await cur.fetchone())["c"]

    async def list_publications(self, offset: int, limit: int) -> list[dict]:
        async with self.conn.execute(
            PUB_SELECT + " ORDER BY p.id DESC LIMIT ? OFFSET ?", (limit, offset)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def delete_publication(self, pub_id: int) -> bool:
        async with self._lock:
            cur = await self.conn.execute("DELETE FROM publications WHERE id = ?", (pub_id,))
            await self.conn.commit()
            return cur.rowcount > 0

    # ---------- Статистика ----------
    async def register_view(self, pub_id: int, user_id: int) -> bool:
        """Фиксирует переход. Возвращает True, если пользователь по этой публикации новый."""
        async with self._lock:
            try:
                cur = await self.conn.execute(
                    "INSERT OR IGNORE INTO publication_users(publication_id, user_id) VALUES(?, ?)",
                    (pub_id, user_id),
                )
                is_new = cur.rowcount == 1
                await self.conn.execute(
                    "UPDATE publications SET views = views + 1 WHERE id = ?", (pub_id,)
                )
                await self.conn.commit()
                return is_new
            except aiosqlite.IntegrityError:  # публикацию успели удалить
                await self.conn.rollback()
                return False

    async def totals(self) -> dict:
        async with self.conn.execute(
            "SELECT COUNT(*) AS pubs, COALESCE(SUM(views), 0) AS views FROM publications"
        ) as cur:
            row = await cur.fetchone()
        async with self.conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS users FROM publication_users"
        ) as cur:
            users = (await cur.fetchone())["users"]
        return {"publications": row["pubs"], "views": row["views"], "users": users}

    async def top_publications(self, limit: int = 30) -> list[dict]:
        async with self.conn.execute(
            PUB_SELECT + " ORDER BY p.views DESC, p.id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
