"""
database.py
Async SQLite database layer for Spark Bot using aiosqlite.
Handles all schema creation and provides reusable query helpers.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

DB_PATH = "spark.db"
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """
    Create all tables if they do not already exist.
    Called once from bot's setup_hook() at startup.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id       TEXT PRIMARY KEY,
                guild_id      TEXT NOT NULL,
                display_name  TEXT,
                interests     TEXT DEFAULT '[]',
                bio           TEXT DEFAULT '',
                opt_in        INTEGER DEFAULT 1,
                joined_at     TEXT,
                total_matches INTEGER DEFAULT 0,
                streak        INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pairings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT NOT NULL,
                user1_id     TEXT NOT NULL,
                user2_id     TEXT NOT NULL,
                paired_at    TEXT NOT NULL,
                user1_rated  INTEGER DEFAULT 0,
                user2_rated  INTEGER DEFAULT 0,
                match_score  REAL DEFAULT 0.0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                member_ids  TEXT DEFAULT '[]',
                interests   TEXT DEFAULT '[]',
                created_at  TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS server_config (
                guild_id          TEXT PRIMARY KEY,
                pairing_channel_id TEXT,
                pairing_day       TEXT DEFAULT 'monday',
                pairing_hour      INTEGER DEFAULT 9,
                admin_role_id     TEXT
            )
        """)

        await db.commit()
    log.info("Database initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Member helpers
# ---------------------------------------------------------------------------

async def upsert_member(
    user_id: str,
    guild_id: str,
    display_name: str,
) -> None:
    """
    Insert a new member row or update the display_name if one already exists.
    Does NOT overwrite interests / bio / opt_in on update.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO members (user_id, guild_id, display_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET display_name = excluded.display_name
        """, (user_id, guild_id, display_name, now))
        await db.commit()


async def get_member(user_id: str) -> Optional[dict]:
    """Return a member row as a dict, or None if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM members WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_member_interests(user_id: str, interests: list[str]) -> None:
    """Persist a new interests list for the given user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE members SET interests = ? WHERE user_id = ?",
            (json.dumps(interests), user_id),
        )
        await db.commit()


async def update_member_bio(user_id: str, bio: str) -> None:
    """Persist a new bio for the given user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE members SET bio = ? WHERE user_id = ?",
            (bio, user_id),
        )
        await db.commit()


async def update_member_opt(user_id: str, opt_in: bool) -> None:
    """Set the opt_in flag for a member."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE members SET opt_in = ? WHERE user_id = ?",
            (1 if opt_in else 0, user_id),
        )
        await db.commit()


async def increment_total_matches(user_id: str) -> None:
    """Increment the total_matches counter by 1."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE members SET total_matches = total_matches + 1 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def update_streak(user_id: str, increment: bool) -> None:
    """
    Increment streak by 1 if increment=True, otherwise reset to 0.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if increment:
            await db.execute(
                "UPDATE members SET streak = streak + 1 WHERE user_id = ?",
                (user_id,),
            )
        else:
            await db.execute(
                "UPDATE members SET streak = 0 WHERE user_id = ?",
                (user_id,),
            )
        await db.commit()


async def get_all_opted_in_members(guild_id: str) -> list[dict]:
    """Return all opted-in members for a guild, ordered by total_matches desc."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM members
            WHERE guild_id = ? AND opt_in = 1
            ORDER BY total_matches DESC
            """,
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_leaderboard(guild_id: str, limit: int = 10) -> list[dict]:
    """Return top N members by total_matches for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM members
            WHERE guild_id = ?
            ORDER BY total_matches DESC
            LIMIT ?
            """,
            (guild_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pairing helpers
# ---------------------------------------------------------------------------

async def log_pairing(
    guild_id: str,
    user1_id: str,
    user2_id: str,
    match_score: float,
) -> int:
    """
    Insert a new pairing record and return the new row id.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO pairings (guild_id, user1_id, user2_id, paired_at, match_score)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, user1_id, user2_id, now, match_score),
        )
        await db.commit()
        return cursor.lastrowid


async def get_recent_pairs(guild_id: str, weeks: int = 4) -> set[frozenset]:
    """
    Return a set of frozensets of (user1_id, user2_id) pairs
    that occurred within the last `weeks` weeks.
    """
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT user1_id, user2_id FROM pairings
            WHERE guild_id = ? AND paired_at >= ?
            """,
            (guild_id, cutoff),
        ) as cursor:
            rows = await cursor.fetchall()
            return {frozenset({r["user1_id"], r["user2_id"]}) for r in rows}


async def get_user_pairings(user_id: str, limit: int = 5) -> list[dict]:
    """Return the last N pairings for a user across all guilds."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM pairings
            WHERE user1_id = ? OR user2_id = ?
            ORDER BY paired_at DESC
            LIMIT ?
            """,
            (user_id, user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_pairing_by_id(pairing_id: int) -> Optional[dict]:
    """Return a pairing row by primary key."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pairings WHERE id = ?", (pairing_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def mark_pairing_rated(pairing_id: int, user_id: str, rating: int) -> bool:
    """
    Mark user1 or user2 as having rated a pairing.
    Returns True if the row was updated, False if already rated.
    """
    pairing = await get_pairing_by_id(pairing_id)
    if not pairing:
        return False

    if pairing["user1_id"] == user_id and not pairing["user1_rated"]:
        col = "user1_rated"
    elif pairing["user2_id"] == user_id and not pairing["user2_rated"]:
        col = "user2_rated"
    else:
        return False

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE pairings SET {col} = ? WHERE id = ?",
            (rating, pairing_id),
        )
        await db.commit()
    return True


async def get_latest_pairing_for_user(user_id: str) -> Optional[dict]:
    """Return the most recent pairing record for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM pairings
            WHERE user1_id = ? OR user2_id = ?
            ORDER BY paired_at DESC
            LIMIT 1
            """,
            (user_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------

async def log_group(
    guild_id: str,
    member_ids: list[str],
    interests: list[str],
) -> int:
    """Insert a new group record and return the new row id."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO groups (guild_id, member_ids, interests, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, json.dumps(member_ids), json.dumps(interests), now),
        )
        await db.commit()
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# Server config helpers
# ---------------------------------------------------------------------------

async def get_server_config(guild_id: str) -> Optional[dict]:
    """Return the server_config row for a guild, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM server_config WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_server_config(
    guild_id: str,
    pairing_channel_id: Optional[str] = None,
    pairing_day: Optional[str] = None,
    pairing_hour: Optional[int] = None,
    admin_role_id: Optional[str] = None,
) -> None:
    """
    Insert or update server_config for a guild.
    Only non-None values overwrite existing columns.
    """
    existing = await get_server_config(guild_id)
    if existing is None:
        # Fresh insert
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO server_config
                    (guild_id, pairing_channel_id, pairing_day, pairing_hour, admin_role_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    pairing_channel_id,
                    pairing_day or "monday",
                    pairing_hour if pairing_hour is not None else 9,
                    admin_role_id,
                ),
            )
            await db.commit()
    else:
        # Partial update
        updates = {}
        if pairing_channel_id is not None:
            updates["pairing_channel_id"] = pairing_channel_id
        if pairing_day is not None:
            updates["pairing_day"] = pairing_day
        if pairing_hour is not None:
            updates["pairing_hour"] = pairing_hour
        if admin_role_id is not None:
            updates["admin_role_id"] = admin_role_id
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [guild_id]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE server_config SET {set_clause} WHERE guild_id = ?",
                values,
            )
            await db.commit()


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

async def get_server_stats(guild_id: str) -> dict:
    """
    Return aggregated stats for a guild:
    total_members, total_pairings, avg_match_score, most_popular_interest.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM members WHERE guild_id = ?", (guild_id,)
        ) as c:
            row = await c.fetchone()
            total_members = row["cnt"]

        async with db.execute(
            """
            SELECT COUNT(*) as cnt, AVG(match_score) as avg_score
            FROM pairings WHERE guild_id = ?
            """,
            (guild_id,),
        ) as c:
            row = await c.fetchone()
            total_pairings = row["cnt"]
            avg_score = round(row["avg_score"] or 0.0, 1)

        # Tally interest popularity from members table
        async with db.execute(
            "SELECT interests FROM members WHERE guild_id = ?", (guild_id,)
        ) as c:
            rows = await c.fetchall()

        tally: dict[str, int] = {}
        for r in rows:
            for interest in json.loads(r["interests"] or "[]"):
                tally[interest] = tally.get(interest, 0) + 1

        most_popular = max(tally, key=tally.get) if tally else "N/A"

        return {
            "total_members": total_members,
            "total_pairings": total_pairings,
            "avg_match_score": avg_score,
            "most_popular_interest": most_popular,
            "interest_tally": tally,
        }
