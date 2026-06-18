"""
add_memories.py — Populates local SQLite database with memory/facts about Sahil and Niket.
Created by K.Astra and its members.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from storage.people import remember_person
from storage.db import init_db

def main():
    print("Initializing database...")
    init_db()
    
    print("Adding Sahil's details...")
    remember_person("Sahil", "Sahil is the software engineer of WALL-E AI")
    remember_person("Sahil", "sahil is its software ingeneer")
    
    print("Adding Niket's details...")
    remember_person("Niket", "Niket is the hardware engineer of WALL-E AI")
    remember_person("Niket", "Niket is its hardware engineer")
    
    print("Success! Memories successfully added to database.")

if __name__ == "__main__":
    main()
