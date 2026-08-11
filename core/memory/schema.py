"""DDL для SQLite-хранилища памяти."""

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS global_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        processed INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_profile (
        username TEXT PRIMARY KEY,
        display_name TEXT,
        real_name TEXT,
        gender TEXT,
        gender_source TEXT,
        age INTEGER,
        job TEXT,
        city TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        fact TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'fact',
        source TEXT NOT NULL DEFAULT 'observed',
        created_at TEXT NOT NULL
    )
    """,
]


def init_schema(conn) -> None:
    """Создаёт таблицы, если их ещё нет."""
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()
