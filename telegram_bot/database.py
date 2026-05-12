"""
database.py — InstaBot v2.0 Persistent Storage Layer
SQLite via aiosqlite.

Tables:
  - users:     Auth, rate limiting, and download counts.
  - analytics: Per-download stats for admin dashboard.
  - cache:     URL-to-file mapping to skip duplicate downloads.
"""

import aiosqlite
import hashlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# DB lives in the same directory as this file (telegram_bot/)
DB_PATH = str(Path(__file__).parent / "bot_data.db")

# ── Config (can be overridden by .env) ────────────────────────────────────────
MAX_DL_PER_HOUR = int(os.getenv("MAX_DL_PER_HOUR", "10"))
ROOT_ADMIN_ID = int(os.getenv("ROOT_ADMIN_ID", "1000808626"))


# ── Schema Setup ──────────────────────────────────────────────────────────────
async def init_db():
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                  INTEGER PRIMARY KEY,
                is_admin            BOOLEAN DEFAULT FALSE,
                is_allowed          BOOLEAN DEFAULT FALSE,
                downloads_this_hour INTEGER DEFAULT 0,
                total_downloads     INTEGER DEFAULT 0,
                last_reset          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_request        TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER,
                platform          TEXT,
                file_size_mb      REAL,
                download_time_sec REAL,
                timestamp         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cache_hit         BOOLEAN DEFAULT FALSE,
                status            TEXT DEFAULT 'success'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key          TEXT PRIMARY KEY,
                file_path    TEXT,
                file_size_mb REAL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Ensure root admin always exists and is allowed
        await db.execute("""
            INSERT OR IGNORE INTO users (id, is_admin, is_allowed)
            VALUES (?, TRUE, TRUE)
        """, (ROOT_ADMIN_ID,))
        await db.commit()
    logger.info(f"Database initialized at {DB_PATH}")


# ── User Auth ─────────────────────────────────────────────────────────────────
async def is_user_allowed(user_id: int) -> bool:
    """Check if a user is authorized to use the bot."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_allowed, is_admin FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            return bool(row[0]) or bool(row[1])


async def allow_user(user_id: int):
    """Grant a user permission to use the bot."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (id, is_allowed) VALUES (?, TRUE)
            ON CONFLICT(id) DO UPDATE SET is_allowed = TRUE
        """, (user_id,))
        await db.commit()


async def revoke_user(user_id: int):
    """Remove a user's permission."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_allowed = FALSE WHERE id = ?", (user_id,)
        )
        await db.commit()


async def get_all_users() -> list[int]:
    """Return all allowed (non-admin) user IDs."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM users WHERE is_allowed = TRUE"
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


# ── Rate Limiting (Atomic + Lazy Reset) ───────────────────────────────────────
async def check_and_increment_rate(user_id: int) -> tuple[bool, int]:
    """
    Atomically check the rate limit and increment the counter.
    Uses lazy reset: if last_reset was over 1 hour ago, counter resets.

    Returns:
        (allowed: bool, current_count: int)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Ensure user row exists
        await db.execute(
            "INSERT OR IGNORE INTO users (id, is_allowed) VALUES (?, FALSE)",
            (user_id,)
        )
        # 2. Fetch current state
        async with db.execute(
            "SELECT downloads_this_hour, last_reset, is_admin FROM users WHERE id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return False, 0

        current_count, last_reset_str, is_admin = row

        # 3. Admin bypass
        if is_admin:
            return True, 0

        # 4. Lazy hourly reset
        try:
            last_reset = datetime.fromisoformat(str(last_reset_str))
        except (ValueError, TypeError):
            last_reset = datetime.now() - timedelta(hours=2)

        if datetime.now() - last_reset >= timedelta(hours=1):
            await db.execute(
                "UPDATE users SET downloads_this_hour = 0, last_reset = ? WHERE id = ?",
                (datetime.now().isoformat(), user_id)
            )
            current_count = 0

        # 5. Atomic increment: only succeeds if under the limit
        async with db.execute("""
            UPDATE users
            SET downloads_this_hour = downloads_this_hour + 1,
                last_request = ?
            WHERE id = ? AND downloads_this_hour < ?
        """, (datetime.now().isoformat(), user_id, MAX_DL_PER_HOUR)) as cursor:
            affected = cursor.rowcount

        await db.commit()

        if affected == 0:
            return False, current_count  # Limit hit

        return True, current_count + 1


# ── Analytics ─────────────────────────────────────────────────────────────────
async def record_download(
    user_id: int,
    platform: str,
    file_size_mb: float,
    download_time_sec: float,
    cache_hit: bool = False,
    status: str = "success"
):
    """Record a completed (or failed) download for analytics."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO analytics (user_id, platform, file_size_mb, download_time_sec, cache_hit, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, platform, file_size_mb, download_time_sec, cache_hit, status))
        # Also bump total_downloads counter
        if status == "success":
            await db.execute(
                "UPDATE users SET total_downloads = total_downloads + 1 WHERE id = ?",
                (user_id,)
            )
        await db.commit()


async def get_analytics_summary() -> dict:
    """Return a summary of stats for the /stats admin command."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Total downloads by platform
        async with db.execute("""
            SELECT platform, COUNT(*) as cnt
            FROM analytics WHERE status = 'success'
            GROUP BY platform ORDER BY cnt DESC
        """) as cursor:
            platform_rows = await cursor.fetchall()

        # Average download time
        async with db.execute(
            "SELECT AVG(download_time_sec) FROM analytics WHERE status = 'success'"
        ) as cursor:
            avg_time_row = await cursor.fetchone()

        # Cache hit rate
        async with db.execute(
            "SELECT COUNT(*) FROM analytics WHERE cache_hit = TRUE AND status = 'success'"
        ) as cursor:
            cache_hits = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM analytics WHERE status = 'success'"
        ) as cursor:
            total_success = (await cursor.fetchone())[0]

        # Top 5 users by total downloads
        async with db.execute("""
            SELECT user_id, COUNT(*) as cnt
            FROM analytics WHERE status = 'success'
            GROUP BY user_id ORDER BY cnt DESC LIMIT 5
        """) as cursor:
            top_users = await cursor.fetchall()

        # Total user count
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE is_allowed = TRUE"
        ) as cursor:
            user_count = (await cursor.fetchone())[0]

    avg_time = avg_time_row[0] if avg_time_row[0] else 0
    cache_rate = (cache_hits / total_success * 100) if total_success > 0 else 0

    return {
        "platform_breakdown": platform_rows,
        "avg_download_time": avg_time,
        "cache_hit_rate": cache_rate,
        "total_downloads": total_success,
        "top_users": top_users,
        "user_count": user_count,
    }


# ── Cache System ──────────────────────────────────────────────────────────────
def make_cache_key(url: str, format_spec: str) -> str:
    """Generate a deterministic SHA256 cache key from URL + format."""
    raw = f"{url.strip()}|{format_spec or 'default'}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_cache(key: str) -> dict | None:
    """Return cached file info if it exists and the file is still on disk."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT file_path, file_size_mb FROM cache WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()

    if row and os.path.exists(row[0]):
        return {"file_path": row[0], "file_size_mb": row[1]}

    # Cache entry stale (file deleted by reaper), clean up
    if row:
        await invalidate_cache(key)
    return None


async def set_cache(key: str, file_path: str, file_size_mb: float):
    """Store a cache entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO cache (key, file_path, file_size_mb, created_at)
            VALUES (?, ?, ?, ?)
        """, (key, file_path, file_size_mb, datetime.now().isoformat()))
        await db.commit()


async def invalidate_cache(key: str):
    """Remove a stale cache entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM cache WHERE key = ?", (key,))
        await db.commit()
