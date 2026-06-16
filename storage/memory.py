"""
storage/memory.py — WALL-E AI conversation memory
Handles session IDs, turn persistence, and memory context building
for the Gemini system prompt.
Created by K.Astra and its members.
"""

import uuid
import json
from datetime import datetime

from storage.db import connection, execute, IS_POSTGRES
from core.logger import get_logger

log = get_logger("storage.memory")

# ── Name normalization ────────────────────────────────────────────────────────
_NAME_ALIASES: dict[str, str] = {}


def _normalize(name: str | None) -> str:
    if not name:
        return "Unknown"
    return _NAME_ALIASES.get(name, _NAME_ALIASES.get(name.lower(), name))


# ── Session ───────────────────────────────────────────────────────────────────
def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Turn persistence ──────────────────────────────────────────────────────────
def save_turn(
    user_id: int,
    person_name: str,
    role: str,
    content: str,
    session_id: str,
) -> None:
    """Persist a single conversation turn."""
    person_name = _normalize(person_name)
    with connection() as conn:
        execute(
            conn,
            "INSERT INTO conversations (user_id, person_name, role, content, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, person_name, role, content, session_id),
        )
        execute(
            conn,
            "UPDATE people SET last_seen = ? WHERE name = ?",
            (datetime.now().isoformat(), person_name),
        )


def reassign_session_turns(old_name: str, new_name: str, session_id: str) -> None:
    """
    Retroactively rename all turns in a session from old_name → new_name.
    Called when WALL-E learns a person's name mid-session.
    """
    old_name = _normalize(old_name)
    new_name = _normalize(new_name)
    if old_name == new_name:
        return
    with connection() as conn:
        res = execute(
            conn,
            "UPDATE conversations SET person_name = ? WHERE person_name = ? AND session_id = ?",
            (new_name, old_name, session_id),
        )
        updated = res.rowcount
    if updated > 0:
        log.info(f"Retroactively renamed {updated} turns: '{old_name}' -> '{new_name}' (session {session_id})")


# ── History queries ───────────────────────────────────────────────────────────
def get_recent_history(person_name: str, limit: int = 20) -> list[dict]:
    person_name = _normalize(person_name)
    with connection() as conn:
        rows = execute(
            conn,
            "SELECT role, content, created_at FROM conversations "
            "WHERE person_name = ? ORDER BY created_at DESC LIMIT ?",
            (person_name, limit),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "time": r["created_at"]}
        for r in reversed(rows)
    ]


def get_recent_history_by_user(user_id: int, limit: int = 20) -> list[dict]:
    """Fetch conversation history scoped to a specific user_id."""
    with connection() as conn:
        rows = execute(
            conn,
            "SELECT role, content, created_at FROM conversations "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "time": r["created_at"]}
        for r in reversed(rows)
    ]


def get_last_session(person_name: str) -> list[dict]:
    person_name = _normalize(person_name)
    with connection() as conn:
        row = execute(
            conn,
            "SELECT session_id FROM conversations "
            "WHERE person_name = ? ORDER BY created_at DESC LIMIT 1",
            (person_name,),
        ).fetchone()
        if not row or not row["session_id"]:
            return []
        rows = execute(
            conn,
            "SELECT role, content FROM conversations "
            "WHERE person_name = ? AND session_id = ? ORDER BY created_at",
            (person_name, row["session_id"]),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── Memory context builder ────────────────────────────────────────────────────
def build_memory_context(user_id: int, person_name: str | None = None) -> str:
    """
    Build the WALL-E AI memory block injected at the top of every system prompt.
    Scoped per user_id to prevent data leakage between users.
    """
    from storage.facts import get_recent_facts
    from storage.people import get_all_people

    person_name = _normalize(person_name) if person_name else "Unknown"
    lines = ["=== WALL-E MEMORY ==="]

    # Global facts
    facts = get_recent_facts(50)
    if facts:
        lines.append("--- CORE FACTS ---")
        for f in facts:
            lines.append(f"• {f}")

    # Known people
    people = get_all_people()
    if people:
        lines.append("--- KNOWN PEOPLE ---")
        for p in people:
            summary = ", ".join(p["details"][:3])
            lines.append(f"• {p['name']}: {summary}")

    # Recent conversation (user-scoped)
    turns = get_recent_history_by_user(user_id, limit=20)
    # Deduplicate
    seen: set[str] = set()
    unique: list[dict] = []
    for t in turns:
        c = t["content"].strip()
        if c and c not in seen:
            unique.append(t)
            seen.add(c)
    unique = unique[-20:]

    if unique:
        lines.append("--- RECENT CONVERSATION ---")
        for turn in unique:
            role = "Human" if turn["role"] == "user" else "WALL-E"
            lines.append(f"  [{role}]: {turn['content']}")

    lines.append("=== END WALL-E MEMORY ===")
    return "\n".join(lines)
