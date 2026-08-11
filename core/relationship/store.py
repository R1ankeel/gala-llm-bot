"""Хранилище отношений поверх общего sqlite-соединения.

Соединение переиспользуется от MemoryStore (та же БД), новое не
открывается. Логика полностью отдельная от core/memory.
"""

from dataclasses import dataclass
from datetime import datetime

from core.relationship.levels import LEVEL_PROGRESS_CAP, NEUTRAL_LEVEL, clamp_level, level_name
from core.relationship.schema import init_schema

# Масштаб дельты: LLM-оценка в диапазоне -3..3, прогресс — в очках.
# Простое решение: delta * 10 очков.
DELTA_SCALE = 10


@dataclass
class RelationshipState:
    username: str
    level: int
    progress: int
    updated_at: str

    @property
    def name(self) -> str:
        return level_name(self.level)


class RelationshipStore:
    def __init__(self, conn, progress_cap: int = LEVEL_PROGRESS_CAP):
        self.conn = conn
        self.progress_cap = progress_cap
        init_schema(conn)

    def get(self, username: str) -> RelationshipState:
        """Если записи нет — создать со стартовыми значениями и вернуть.
        Не возвращает None никогда."""
        row = self.conn.execute(
            "SELECT username, level, progress, updated_at FROM relationship WHERE username = ?",
            (username,),
        ).fetchone()
        if row is not None:
            return RelationshipState(**dict(row))
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO relationship (username, level, progress, updated_at) VALUES (?, ?, ?, ?)",
            (username, NEUTRAL_LEVEL, 0, now),
        )
        self.conn.commit()
        return RelationshipState(username=username, level=NEUTRAL_LEVEL, progress=0, updated_at=now)

    def apply_delta(self, username: str, delta: int, reason: str) -> RelationshipState:
        """Применяет дельту к текущему состоянию и возвращает новое.

        Правила перехода (все простые, без переноса излишка):
          new_progress = progress + delta * DELTA_SCALE
          new_progress >= cap  -> level = clamp(level - 1), progress = 0
          new_progress < 0     -> level = clamp(level + 1), progress = cap
          иначе               -> progress = new_progress
        При упоре в границу шкалы (level 0 с положительной дельтой,
        level 9 с отрицательной) уровень держится clamp-ом, а прогресс
        фиксируется на cap (для 0) или 0 (для 9) — не растёт бесконечно.
        """
        current = self.get(username)
        new_progress = current.progress + delta * DELTA_SCALE

        level = current.level
        if new_progress >= self.progress_cap:
            if level == 0:
                progress = self.progress_cap  # выше Любви некуда
            else:
                level = clamp_level(level - 1)
                progress = 0
        elif new_progress < 0:
            if level == 9:
                progress = 0  # ниже Ненависти некуда
            else:
                level = clamp_level(level + 1)
                progress = self.progress_cap
        else:
            progress = new_progress

        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE relationship SET level = ?, progress = ?, updated_at = ? WHERE username = ?",
            (level, progress, now, username),
        )
        self.conn.execute(
            "INSERT INTO relationship_log (username, delta, reason, created_at) VALUES (?, ?, ?, ?)",
            (username, delta, reason, now),
        )
        self.conn.commit()
        return RelationshipState(username=username, level=level, progress=progress, updated_at=now)
