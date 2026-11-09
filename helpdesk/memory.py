"""User memory: a small SQLite store keyed by user_id (separate from conversation checkpoints).

Conversation memory  -> LangGraph checkpointer, keyed by thread_id (one conversation).
User memory (this)   -> keyed by user_id, shared by all of that user's threads.
"""
import sqlite3
from pathlib import Path

from .common import storage_dir


class UserMemory:
    def __init__(self, path=None):
        self.path = Path(path) if path else storage_dir() / "user_memory.sqlite"
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS user_memory ("
            "user_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "PRIMARY KEY (user_id, key))"
        )
        self.conn.commit()

    def save(self, user_id: str, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO user_memory (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, value),
        )
        self.conn.commit()

    def load(self, user_id: str) -> dict:
        rows = self.conn.execute(
            "SELECT key, value FROM user_memory WHERE user_id = ?", (user_id,)
        ).fetchall()
        return dict(rows)

    def close(self) -> None:
        self.conn.close()
