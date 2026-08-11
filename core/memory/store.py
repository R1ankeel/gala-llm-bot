"""SQLite-хранилище: чат, профили, факты."""

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime

from core.memory.profile_safety import is_safe_value
from core.memory.schema import init_schema

logger = logging.getLogger(__name__)

PROFILE_FIELDS = frozenset(
    {"display_name", "real_name", "gender", "gender_source", "age", "job", "city"}
)


@dataclass
class ChatMessage:
    id: int
    username: str
    text: str
    created_at: str
    processed: int


@dataclass
class UserProfile:
    username: str
    updated_at: str
    display_name: str | None = None
    real_name: str | None = None
    gender: str | None = None
    gender_source: str | None = None
    age: int | None = None
    job: str | None = None
    city: str | None = None


@dataclass
class Fact:
    id: int
    username: str
    fact: str
    category: str
    source: str
    created_at: str


def _normalize_fact(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


class MemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        if db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)

    def log_message(self, username: str, text: str, created_at: datetime) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO global_chat (username, text, created_at) VALUES (?, ?, ?)",
                (username, text, created_at.isoformat()),
            )
            self.conn.commit()

    def get_unprocessed_messages(self, limit: int = 200) -> list[ChatMessage]:
        rows = self.conn.execute(
            "SELECT * FROM global_chat WHERE processed = 0 ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        return [ChatMessage(**dict(row)) for row in rows]

    def mark_processed(self, message_ids: list[int]) -> None:
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        with self._lock:
            self.conn.execute(
                f"UPDATE global_chat SET processed = 1 WHERE id IN ({placeholders})",
                message_ids,
            )
            self.conn.commit()

    def count_unprocessed(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM global_chat WHERE processed = 0"
        ).fetchone()
        return int(row["c"])

    def upsert_profile_field(self, username: str, field: str, value) -> None:
        if field not in PROFILE_FIELDS:
            logger.warning("unknown profile field %r, ignoring", field)
            return
        if not is_safe_value(field, value):
            logger.warning("unsafe profile value for %r, ignoring", field)
            return
        if field == "age":
            value = int(value)
        else:
            value = str(value).strip()
        now = datetime.now().isoformat()
        column = field
        with self._lock:
            self.conn.execute(
                f"""
                INSERT INTO user_profile (username, {column}, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    {column} = excluded.{column},
                    updated_at = excluded.updated_at
                """,
                (username, value, now),
            )
            self.conn.commit()

    def get_profile(self, username: str) -> UserProfile | None:
        row = self.conn.execute(
            "SELECT * FROM user_profile WHERE username = ?", (username,)
        ).fetchone()
        return UserProfile(**dict(row)) if row else None

    def add_fact(
        self,
        username: str,
        fact: str,
        category: str = "fact",
        source: str = "observed",
    ) -> bool:
        normalized = _normalize_fact(fact)
        existing = self.conn.execute(
            "SELECT 1 FROM user_facts WHERE username = ? AND fact = ? LIMIT 1",
            (username, normalized),
        ).fetchone()
        if existing is not None:
            return False
        with self._lock:
            self.conn.execute(
                "INSERT INTO user_facts (username, fact, category, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, normalized, category, source, datetime.now().isoformat()),
            )
            self.conn.commit()
        return True

    def get_facts(self, username: str, limit: int | None = None) -> list[Fact]:
        sql = "SELECT * FROM user_facts WHERE username = ? ORDER BY id ASC"
        params = [username]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [Fact(**dict(row)) for row in rows]

    def get_recent_facts(self, username: str, limit: int) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM user_facts WHERE username = ? ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
        return [Fact(**dict(row)) for row in rows]
