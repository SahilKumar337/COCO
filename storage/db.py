"""
storage/db.py — WALL-E AI database connection + schema bootstrap
Supports SQLite (local/dev) and PostgreSQL (production/Railway/Render).
Single source of truth for the connection helper and schema init.
Created by K.Astra and its members.
"""

import os
import sqlite3
from contextlib import contextmanager

from core.config import settings
from core.logger import get_logger

log = get_logger("storage.db")

# ── Backend detection ─────────────────────────────────────────────────────────
IS_POSTGRES: bool = settings.is_postgres

if IS_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    log.info("Database backend: PostgreSQL")
else:
    log.info(f"Database backend: SQLite at {settings.db_file}")


# ── Connection ────────────────────────────────────────────────────────────────
def get_connection():
    """Open and return a raw DB connection (caller must close)."""
    if IS_POSTGRES:
        return psycopg2.connect(settings.database_url, cursor_factory=RealDictCursor)
    conn = sqlite3.connect(settings.db_file, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def connection():
    """Context manager that auto-commits and closes the connection."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(conn, query: str, params=None):
    """
    Execute a query handling the ? vs %s placeholder difference between
    SQLite and PostgreSQL transparently.
    """
    if IS_POSTGRES:
        query = query.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(query, params or ())
        return cur
    return conn.execute(query, params or ())


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id          SERIAL PRIMARY KEY,
        email       TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        name        TEXT NOT NULL,
        google_id   TEXT UNIQUE,
        ai_voice    TEXT DEFAULT 'Aoede',
        ai_persona  TEXT DEFAULT 'Professional Executive Assistant',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS people (
        name          TEXT PRIMARY KEY,
        first_met     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen     TIMESTAMP,
        is_creator    BOOLEAN DEFAULT '0',
        face_encoding BYTEA,
        details       TEXT DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS conversations (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER,
        person_name TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        session_id  TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS facts (
        id         SERIAL PRIMARY KEY,
        fact       TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = get_connection()
    schema = _SCHEMA

    if not IS_POSTGRES:
        schema = (
            schema
            .replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            .replace("BYTEA", "BLOB")
            .replace("BOOLEAN DEFAULT '0'", "BOOLEAN DEFAULT 0")
        )

    try:
        if IS_POSTGRES:
            cur = conn.cursor()
            for stmt in schema.split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        else:
            conn.executescript(schema)

        # Safe migrations — ignore errors if columns already exist
        for col_ddl in [
            "ALTER TABLE conversations ADD COLUMN user_id INTEGER",
        ]:
            try:
                if IS_POSTGRES:
                    conn.cursor().execute(
                        col_ddl.replace(
                            "ADD COLUMN", "ADD COLUMN IF NOT EXISTS"
                        )
                    )
                else:
                    conn.execute(col_ddl)
            except Exception:
                pass

        if not IS_POSTGRES:
            for idx in [
                "CREATE INDEX IF NOT EXISTS idx_users_email  ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_conv_user    ON conversations(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_conv_person  ON conversations(person_name)",
                "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_conv_time    ON conversations(created_at)",
            ]:
                conn.execute(idx)

        conn.commit()
        log.info("Database schema initialized.")
    finally:
        conn.close()


# ── Auto-init on import ───────────────────────────────────────────────────────
init_db()
