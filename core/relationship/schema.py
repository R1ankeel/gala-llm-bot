"""DDL для отношений. Таблицы живут в той же БД, что и память
(один db_path, один conn — соединение переиспользуется)."""

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS relationship (
        username TEXT PRIMARY KEY,
        level INTEGER NOT NULL DEFAULT 6,     -- NEUTRAL_LEVEL
        progress INTEGER NOT NULL DEFAULT 0,  -- 0..progress_cap внутри уровня
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationship_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT,
        created_at TEXT NOT NULL
    )
    """,
]


def init_schema(conn) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()
