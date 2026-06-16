"""
database.py — WALL-E AI backward-compatibility shim
Re-exports everything from the new storage/ package so that any
remaining code that does `from database import ...` continues to work
during the migration window.

DO NOT add new logic here. Implement it in storage/.
Created by K.Astra and its members.
"""

# Connection + schema
from storage.db import (
    get_connection as _connect,
    execute as _execute,
    init_db,
    IS_POSTGRES,
)

# Memory
from storage.memory import (
    new_session_id,
    save_turn,
    reassign_session_turns,
    get_recent_history,
    get_recent_history_by_user as get_recent_history_all,
    get_last_session,
    build_memory_context,
)

# People + faces + users
from storage.people import (
    remember_person,
    get_person,
    get_all_people,
    save_face_encoding,
    load_all_faces,
    get_user_by_email,
    get_user_by_id,
    create_user,
    update_user_settings,
    migrate_from_json,
)

# Facts
from storage.facts import (
    remember_fact,
    get_recent_facts,
)

# Kept for backward compat with old main.py imports
def assign_legacy_conversations(admin_user_id: int):
    from storage.db import connection, execute
    with connection() as conn:
        execute(
            conn,
            "UPDATE conversations SET user_id = ? WHERE user_id IS NULL",
            (admin_user_id,),
        )

__all__ = [
    "init_db", "IS_POSTGRES",
    "new_session_id", "save_turn", "reassign_session_turns",
    "get_recent_history", "get_recent_history_all", "get_last_session",
    "build_memory_context",
    "remember_person", "get_person", "get_all_people",
    "save_face_encoding", "load_all_faces",
    "get_user_by_email", "get_user_by_id", "create_user", "update_user_settings",
    "migrate_from_json", "assign_legacy_conversations",
    "remember_fact", "get_recent_facts",
]
