"""
migrate_users.py — One-time migration from allowed_users.json to SQLite DB.

Run once on the Termux server:
    python telegram_bot/scripts/migrate_users.py
"""

import asyncio
import json
import os
import shutil
import sys

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database

JSON_FILE = "allowed_users.json"
BACKUP_FILE = "allowed_users.json.bak"


async def migrate():
    print("🚀 Starting migration from JSON to SQLite...")

    # 1. Initialize the DB (creates tables if they don't exist)
    await database.init_db()

    # 2. Load existing JSON
    if not os.path.exists(JSON_FILE):
        print(f"⚠️  '{JSON_FILE}' not found. Nothing to migrate.")
        return

    with open(JSON_FILE, "r") as f:
        try:
            user_ids = json.load(f)
        except json.JSONDecodeError:
            print("❌ Failed to parse JSON file. Aborting.")
            return

    if not isinstance(user_ids, list):
        print("❌ JSON format is not a list. Aborting.")
        return

    print(f"📋 Found {len(user_ids)} user(s) in JSON file.")

    # 3. Insert each user into the DB
    migrated = 0
    for uid in user_ids:
        try:
            await database.allow_user(int(uid))
            print(f"   ✅ Migrated user: {uid}")
            migrated += 1
        except Exception as e:
            print(f"   ❌ Failed for {uid}: {e}")

    print(f"\n✅ Migration complete. {migrated}/{len(user_ids)} users migrated.")

    # 4. Backup the original JSON
    shutil.copy(JSON_FILE, BACKUP_FILE)
    print(f"💾 Original JSON backed up as '{BACKUP_FILE}'.")
    print("\nYou can safely delete 'allowed_users.json' after verifying the DB.")


if __name__ == "__main__":
    asyncio.run(migrate())
