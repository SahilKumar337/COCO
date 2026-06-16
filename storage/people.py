"""
storage/people.py — WALL-E AI people registry
People directory, face encodings, and JSON migration.
Created by K.Astra and its members.
"""

import json
import os
from datetime import datetime

import numpy as np

from storage.db import connection, execute
from core.logger import get_logger

log = get_logger("storage.people")

_NAME_ALIASES: dict[str, str] = {}


def _normalize(name: str | None) -> str:
    if not name:
        return "Unknown"
    return _NAME_ALIASES.get(name, _NAME_ALIASES.get(name.lower(), name))


# ── People CRUD ───────────────────────────────────────────────────────────────
def remember_person(name: str, detail: str) -> None:
    name = _normalize(name)
    now  = datetime.now().isoformat()
    with connection() as conn:
        row = execute(conn, "SELECT details FROM people WHERE name = ?", (name,)).fetchone()
        if row:
            details = json.loads(row["details"])
            if detail not in details:
                details.append(detail)
            execute(
                conn,
                "UPDATE people SET details = ?, last_seen = ? WHERE name = ?",
                (json.dumps(details), now, name),
            )
        else:
            execute(
                conn,
                "INSERT INTO people (name, first_met, last_seen, is_creator, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, now, now, 0, json.dumps([detail])),
            )


def get_person(name: str) -> dict | None:
    name = _normalize(name)
    with connection() as conn:
        row = execute(conn, "SELECT * FROM people WHERE name = ?", (name,)).fetchone()
    if not row:
        return None
    return {
        "name":       row["name"],
        "first_met":  row["first_met"],
        "last_seen":  row["last_seen"],
        "is_creator": bool(row["is_creator"]),
        "details":    json.loads(row["details"]),
    }


def get_all_people() -> list[dict]:
    with connection() as conn:
        rows = execute(
            conn, "SELECT name, details, last_seen FROM people"
        ).fetchall()
    return [
        {
            "name":      r["name"],
            "details":   json.loads(r["details"]),
            "last_seen": r["last_seen"],
        }
        for r in rows
    ]


# ── Face encodings ────────────────────────────────────────────────────────────
def save_face_encoding(name: str, encoding: np.ndarray) -> None:
    name = _normalize(name)
    blob = encoding.tobytes()
    with connection() as conn:
        row = execute(conn, "SELECT name FROM people WHERE name = ?", (name,)).fetchone()
        if row:
            execute(conn, "UPDATE people SET face_encoding = ? WHERE name = ?", (blob, name))
        else:
            remember_person(name, "Face enrolled")
            execute(conn, "UPDATE people SET face_encoding = ? WHERE name = ?", (blob, name))


def load_all_faces() -> dict[str, np.ndarray]:
    with connection() as conn:
        rows = execute(
            conn,
            "SELECT name, face_encoding FROM people WHERE face_encoding IS NOT NULL",
        ).fetchall()
    return {
        r["name"]: np.frombuffer(r["face_encoding"], dtype=np.float64)
        for r in rows
    }


# ── User management ───────────────────────────────────────────────────────────
def get_user_by_email(email: str) -> dict | None:
    with connection() as conn:
        row = execute(conn, "SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with connection() as conn:
        row = execute(conn, "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_user(
    email: str, name: str, password_hash: str = None, google_id: str = None
) -> int:
    from storage.db import IS_POSTGRES
    with connection() as conn:
        cursor = execute(
            conn,
            "INSERT INTO users (email, name, password_hash, google_id) VALUES (?, ?, ?, ?)",
            (email, name, password_hash, google_id),
        )
        return cursor.fetchone()["id"] if IS_POSTGRES else cursor.lastrowid


def update_user_settings(user_id: int, ai_voice: str, ai_persona: str) -> None:
    with connection() as conn:
        execute(
            conn,
            "UPDATE users SET ai_voice = ?, ai_persona = ? WHERE id = ?",
            (ai_voice, ai_persona, user_id),
        )


# ── JSON migration ────────────────────────────────────────────────────────────
def migrate_from_json(json_path: str = "walle_memory.json") -> None:
    """One-time migration from the old JSON memory format to SQLite."""
    if not os.path.exists(json_path):
        log.info("No JSON memory file found — skipping migration.")
        return

    with open(json_path) as f:
        old = json.load(f)

    migrated = 0
    from storage.memory import new_session_id, save_turn
    from storage.facts import remember_fact

    for name, info in old.get("people", {}).items():
        with connection() as conn:
            row = execute(conn, "SELECT name FROM people WHERE name = ?", (name,)).fetchone()
            if not row:
                details = info.get("details", [])
                execute(
                    conn,
                    "INSERT INTO people (name, first_met, last_seen, is_creator, details) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        name,
                        info.get("first_met", datetime.now().isoformat()),
                        info.get("last_seen",  datetime.now().isoformat()),
                        0,
                        json.dumps(details),
                    ),
                )
                migrated += 1

    last = old.get("last_session")
    if last and last.get("turns"):
        session_id = new_session_id()
        person = next(iter(old.get("people", {})), "Unknown")
        for turn in last["turns"]:
            save_turn(1, person, turn["role"], turn["content"], session_id)

    for fact_item in old.get("facts", []):
        remember_fact(fact_item.get("fact", ""))

    backup = json_path + ".migrated"
    os.rename(json_path, backup)
    log.info(f"Migrated {migrated} people from JSON -> DB. Backup -> {backup}")
