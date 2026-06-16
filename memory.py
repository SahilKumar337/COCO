"""
memory.py — WALL-E AI backward-compatibility shim
Re-exports from storage.memory for any legacy imports.
New code should import directly from storage.memory.
Created by K.Astra and its members.
"""

from storage.memory import (
    new_session_id,
    save_turn,
    get_recent_history,
    build_memory_context,
    reassign_session_turns,
)
from storage.people import remember_person, migrate_from_json
from storage.facts import remember_fact


def save_session(conversation: list, person_name: str = "Unknown", session_id: str = None):
    """
    Backward-compatible: save a full conversation session.
    Individual turns are now saved in real-time via save_turn().
    """
    if not session_id:
        session_id = new_session_id()
    for turn in conversation:
        save_turn(
            user_id=1,
            person_name=person_name,
            role=turn["role"],
            content=turn["content"],
            session_id=session_id,
        )


__all__ = [
    "build_memory_context",
    "remember_person",
    "remember_fact",
    "save_session",
    "save_turn",
    "new_session_id",
    "migrate_from_json",
    "reassign_session_turns",
]
