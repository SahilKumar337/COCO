import sqlite3
import os

DB_FILE = "d:/COCO/coco_memory.db"

def check_db():
    if not os.path.exists(DB_FILE):
        print(f"Database file {DB_FILE} does not exist.")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    
    print("--- TABLES ---")
    res = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for row in res:
        print(row['name'])
        
    print("\n--- PEOPLE ---")
    res = conn.execute("SELECT * FROM people").fetchall()
    for row in res:
        print(dict(row))
        
    print("\n--- RECENT CONVERSATIONS (Last 10) ---")
    res = conn.execute("SELECT * FROM conversations ORDER BY created_at DESC LIMIT 10").fetchall()
    for row in res:
        print(dict(row))
        
    print("\n--- FACTS ---")
    res = conn.execute("SELECT * FROM facts").fetchall()
    for row in res:
        print(dict(row))
        
    conn.close()

if __name__ == "__main__":
    check_db()
