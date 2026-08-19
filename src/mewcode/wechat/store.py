from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import WechatDesktopEvent


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

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["WechatStateStore"]
