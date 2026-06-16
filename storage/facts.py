"""
storage/facts.py — WALL-E AI global facts store
Capped at 100 most recent facts, auto-pruned on insert.
Created by K.Astra and its members.
"""

from storage.db import connection, execute
from core.logger import get_logger

log = get_logger("storage.facts")


def remember_fact(fact: str) -> None:
    """Insert a fact and prune to the 100 most recent."""
    with connection() as conn:
        execute(conn, "INSERT INTO facts (fact) VALUES (?)", (fact,))
        execute(
            conn,
            "DELETE FROM facts WHERE id NOT IN "
            "(SELECT id FROM facts ORDER BY created_at DESC LIMIT 100)",
        )


def get_recent_facts(limit: int = 10) -> list[str]:
    with connection() as conn:
        rows = execute(
            conn,
            "SELECT fact FROM facts ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r["fact"] for r in reversed(rows)]
