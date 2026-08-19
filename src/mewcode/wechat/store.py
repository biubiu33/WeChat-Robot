from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from .models import WechatDesktopEvent


@dataclass(frozen=True)
class CachedLocation:
    key: str
    value_json: str
    updated_at: float


@dataclass(frozen=True)
class CachedWebSearch:
    key: str
    query: str
    result_json: str
    fetched_at: float


@dataclass(frozen=True)
class CachedWebPage:
    key: str
    url: str
    title: str
    content: str
    fetched_at: float


class WechatStateStore:
    def __init__(self, root: Path) -> None:
        state_dir = root.resolve() / ".mewcode"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "wechat.sqlite3"
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                observed_at REAL NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bindings (
                conversation_name TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS location_cache (
                cache_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS web_search_cache (
                cache_key TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                result_json TEXT NOT NULL,
                fetched_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS web_page_cache (
                cache_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                fetched_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tavily_monthly_usage (
                month_key TEXT PRIMARY KEY,
                credits INTEGER NOT NULL CHECK (credits >= 0)
            );
            """
        )
        self._connection.commit()

    def record_event_once(self, event: WechatDesktopEvent) -> bool:
        with self._lock:
            try:
                self._connection.execute(
                    "INSERT INTO events(event_id, fingerprint, observed_at) "
                    "VALUES (?, ?, ?)",
                    (event.event_id, event.fingerprint, event.observed_at),
                )
                self._connection.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def mark_processed(self, event_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE events SET processed = 1 WHERE event_id = ?", (event_id,)
            )
            self._connection.commit()

    def is_processed(self, event_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT processed FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return bool(row and row[0])

    def get_session_id(self, conversation_name: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT session_id FROM bindings WHERE conversation_name = ?",
                (conversation_name,),
            ).fetchone()
        return str(row[0]) if row else None

    def bind_session(self, conversation_name: str, session_id: str) -> None:
        if not conversation_name or not session_id:
            raise ValueError("conversation_name 和 session_id 不能为空")
        with self._lock:
            row = self._connection.execute(
                "SELECT session_id FROM bindings WHERE conversation_name = ?",
                (conversation_name,),
            ).fetchone()
            if row is not None:
                if row[0] != session_id:
                    raise ValueError(f"好友 {conversation_name} 已绑定其他 Session")
                return
            self._connection.execute(
                "INSERT INTO bindings(conversation_name, session_id) VALUES (?, ?)",
                (conversation_name, session_id),
            )
            self._connection.commit()

    def get_location(self, cache_key: str) -> CachedLocation | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value_json, updated_at FROM location_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return CachedLocation(cache_key, str(row[0]), float(row[1])) if row else None

    def put_location(self, record: CachedLocation) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO location_cache(cache_key, value_json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET "
                "value_json = excluded.value_json, updated_at = excluded.updated_at",
                (record.key, record.value_json, record.updated_at),
            )
            self._connection.commit()

    def get_web_search(self, cache_key: str) -> CachedWebSearch | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT query, result_json, fetched_at FROM web_search_cache "
                "WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return (
            CachedWebSearch(cache_key, str(row[0]), str(row[1]), float(row[2]))
            if row
            else None
        )

    def put_web_search(self, record: CachedWebSearch) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO web_search_cache(cache_key, query, result_json, fetched_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET "
                "query = excluded.query, result_json = excluded.result_json, "
                "fetched_at = excluded.fetched_at",
                (record.key, record.query, record.result_json, record.fetched_at),
            )
            self._connection.commit()

    def get_web_page(self, cache_key: str) -> CachedWebPage | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT url, title, content, fetched_at FROM web_page_cache "
                "WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return (
            CachedWebPage(
                cache_key, str(row[0]), str(row[1]), str(row[2]), float(row[3])
            )
            if row
            else None
        )

    def put_web_page(self, record: CachedWebPage) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO web_page_cache(cache_key, url, title, content, fetched_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET "
                "url = excluded.url, title = excluded.title, "
                "content = excluded.content, fetched_at = excluded.fetched_at",
                (
                    record.key,
                    record.url,
                    record.title,
                    record.content,
                    record.fetched_at,
                ),
            )
            self._connection.commit()

    def reserve_tavily_credit(self, month_key: str, limit: int = 1000) -> bool:
        if not month_key or limit <= 0:
            raise ValueError("month_key 不能为空且 limit 必须为正数")
        with self._lock:
            self._connection.execute(
                "INSERT OR IGNORE INTO tavily_monthly_usage(month_key, credits) "
                "VALUES (?, 0)",
                (month_key,),
            )
            cursor = self._connection.execute(
                "UPDATE tavily_monthly_usage SET credits = credits + 1 "
                "WHERE month_key = ? AND credits < ?",
                (month_key, limit),
            )
            self._connection.commit()
            return cursor.rowcount == 1

    def tavily_credits(self, month_key: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT credits FROM tavily_monthly_usage WHERE month_key = ?",
                (month_key,),
            ).fetchone()
        return int(row[0]) if row else 0

    def prune_info_cache(self, before: float) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM web_search_cache WHERE fetched_at < ?", (before,)
            )
            self._connection.execute(
                "DELETE FROM web_page_cache WHERE fetched_at < ?", (before,)
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = [
    "CachedLocation",
    "CachedWebPage",
    "CachedWebSearch",
    "WechatStateStore",
]
