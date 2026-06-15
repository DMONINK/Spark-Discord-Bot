"""
Spark Bot - Database Module
Handles all async SQLite operations
"""

import aiosqlite
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = "spark.db"


class Database:
    """Async SQLite database handler for Spark Bot"""

    async def initialize(self):
        """Initialize database and create tables if they don't exist"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    user_id TEXT PRIMARY KEY,
                    guild_id TEXT,
                    display_name TEXT,
                    interests TEXT,
                    bio TEXT,
                    opt_in INTEGER DEFAULT 1,
                    joined_at TEXT,
                    total_matches INTEGER DEFAULT 0,
                    streak INTEGER DEFAULT 0
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS pairings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user1_id TEXT,
                    user2_id TEXT,
                    paired_at TEXT,
                    user1_rated INTEGER DEFAULT 0,
                    user2_rated INTEGER DEFAULT 0,
                    match_score REAL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    member_ids TEXT,
                    interests TEXT,
                    created_at TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS server_config (
                    guild_id TEXT PRIMARY KEY,
                    pairing_channel_id TEXT,
                    pairing_day TEXT DEFAULT 'monday',
                    pairing_hour INTEGER DEFAULT 9,
                    admin_role_id TEXT
                )
            """)

            await db.commit()
            logger.info("Database tables initialized")

    async def add_member(self, user_id: str, guild_id: str, display_name: str) -> bool:
        """Add a new member to the database"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO members 
                    (user_id, guild_id, display_name, interests, joined_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, guild_id, display_name, json.dumps([]), datetime.now().isoformat())
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding member: {e}")
            return False

    async def get_member(self, user_id: str) -> Optional[Dict]:
        """Get member profile"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM members WHERE user_id = ?",
                    (user_id,)
                )
                row = await cursor.fetchone()
                if row:
                    return dict(row)
            return None
        except Exception as e:
            logger.error(f"Error getting member: {e}")
            return None

    async def update_interests(self, user_id: str, interests: List[str]) -> bool:
        """Update member's interests"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE members SET interests = ? WHERE user_id = ?",
                    (json.dumps(interests), user_id)
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating interests: {e}")
            return False

    async def update_bio(self, user_id: str, bio: str) -> bool:
        """Update member's bio"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE members SET bio = ? WHERE user_id = ?",
                    (bio, user_id)
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating bio: {e}")
            return False

    async def set_opt_in(self, user_id: str, opt_in: bool) -> bool:
        """Set member's opt-in status for weekly pairings"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE members SET opt_in = ? WHERE user_id = ?",
                    (1 if opt_in else 0, user_id)
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting opt-in: {e}")
            return False

    async def create_pairing(self, guild_id: str, user1_id: str, user2_id: str, match_score: float) -> Optional[int]:
        """Create a pairing record"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO pairings (guild_id, user1_id, user2_id, paired_at, match_score)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (guild_id, user1_id, user2_id, datetime.now().isoformat(), match_score)
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating pairing: {e}")
            return None

    async def rate_pairing(self, pairing_id: int, user_id: str, rating: int) -> bool:
        """Rate a pairing"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Get pairing info first
                cursor = await db.execute(
                    "SELECT user1_id, user2_id FROM pairings WHERE id = ?",
                    (pairing_id,)
                )
                row = await cursor.fetchone()
                if not row:
                    return False

                user1_id, user2_id = row
                
                if user_id == user1_id:
                    await db.execute(
                        "UPDATE pairings SET user1_rated = ? WHERE id = ?",
                        (rating, pairing_id)
                    )
                elif user_id == user2_id:
                    await db.execute(
                        "UPDATE pairings SET user2_rated = ? WHERE id = ?",
                        (rating, pairing_id)
                    )
                else:
                    return False

                # Update streak if rating >= 4
                if rating >= 4:
                    member = await self.get_member(user_id)
                    if member:
                        new_streak = (member['streak'] or 0) + 1
                        await db.execute(
                            "UPDATE members SET streak = ? WHERE user_id = ?",
                            (new_streak, user_id)
                        )

                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error rating pairing: {e}")
            return False

    async def increment_match_count(self, user_id: str) -> bool:
        """Increment member's total match count"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                member = await self.get_member(user_id)
                if member:
                    new_count = (member['total_matches'] or 0) + 1
                    await db.execute(
                        "UPDATE members SET total_matches = ? WHERE user_id = ?",
                        (new_count, user_id)
                    )
                    await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error incrementing match count: {e}")
            return False

    async def get_user_pairings(self, user_id: str, limit: int = 5) -> List[Dict]:
        """Get user's recent pairings"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM pairings 
                    WHERE user1_id = ? OR user2_id = ?
                    ORDER BY paired_at DESC
                    LIMIT ?
                    """,
                    (user_id, user_id, limit)
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting user pairings: {e}")
            return []

    async def get_top_members(self, guild_id: str, limit: int = 10) -> List[Dict]:
        """Get top members by match count"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT user_id, display_name, total_matches, streak 
                    FROM members 
                    WHERE guild_id = ?
                    ORDER BY total_matches DESC, streak DESC
                    LIMIT ?
                    """,
                    (guild_id, limit)
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting top members: {e}")
            return []

    async def get_guild_members(self, guild_id: str, opt_in_only: bool = False) -> List[Dict]:
        """Get all members in a guild"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                if opt_in_only:
                    cursor = await db.execute(
                        "SELECT * FROM members WHERE guild_id = ? AND opt_in = 1",
                        (guild_id,)
                    )
                else:
                    cursor = await db.execute(
                        "SELECT * FROM members WHERE guild_id = ?",
                        (guild_id,)
                    )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting guild members: {e}")
            return []

    async def get_recent_pairings(self, user1_id: str, user2_id: str, days: int = 28) -> List[Dict]:
        """Check if two users were paired recently"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM pairings 
                    WHERE ((user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?))
                    AND paired_at > ?
                    """,
                    (user1_id, user2_id, user2_id, user1_id, cutoff_date)
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error checking recent pairings: {e}")
            return []

    async def get_guild_stats(self, guild_id: str) -> Dict:
        """Get server-wide statistics"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                
                # Total members
                cursor = await db.execute(
                    "SELECT COUNT(*) as count FROM members WHERE guild_id = ?",
                    (guild_id,)
                )
                member_count = (await cursor.fetchone())['count']

                # Total pairings
                cursor = await db.execute(
                    "SELECT COUNT(*) as count FROM pairings WHERE guild_id = ?",
                    (guild_id,)
                )
                pairing_count = (await cursor.fetchone())['count']

                # Average match score
                cursor = await db.execute(
                    "SELECT AVG(match_score) as avg FROM pairings WHERE guild_id = ?",
                    (guild_id,)
                )
                avg_score = (await cursor.fetchone())['avg'] or 0

                # Most popular interest
                members = await self.get_guild_members(guild_id)
                interest_counts = {}
                for member in members:
                    interests = json.loads(member['interests'] or '[]')
                    for interest in interests:
                        interest_counts[interest] = interest_counts.get(interest, 0) + 1

                most_popular = max(interest_counts.items(), key=lambda x: x[1])[0] if interest_counts else "None"

                return {
                    'total_members': member_count,
                    'total_pairings': pairing_count,
                    'avg_match_score': round(avg_score, 2),
                    'most_popular_interest': most_popular
                }
        except Exception as e:
            logger.error(f"Error getting guild stats: {e}")
            return {
                'total_members': 0,
                'total_pairings': 0,
                'avg_match_score': 0,
                'most_popular_interest': 'None'
            }

    async def set_server_config(self, guild_id: str, pairing_channel_id: str = None, 
                               pairing_day: str = None, pairing_hour: int = None, 
                               admin_role_id: str = None) -> bool:
        """Set server configuration"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Check if config exists
                cursor = await db.execute(
                    "SELECT * FROM server_config WHERE guild_id = ?",
                    (guild_id,)
                )
                exists = await cursor.fetchone()

                if exists:
                    # Update existing config
                    updates = []
                    params = []
                    if pairing_channel_id is not None:
                        updates.append("pairing_channel_id = ?")
                        params.append(pairing_channel_id)
                    if pairing_day is not None:
                        updates.append("pairing_day = ?")
                        params.append(pairing_day)
                    if pairing_hour is not None:
                        updates.append("pairing_hour = ?")
                        params.append(pairing_hour)
                    if admin_role_id is not None:
                        updates.append("admin_role_id = ?")
                        params.append(admin_role_id)
                    
                    if updates:
                        params.append(guild_id)
                        query = f"UPDATE server_config SET {', '.join(updates)} WHERE guild_id = ?"
                        await db.execute(query, params)
                else:
                    # Insert new config
                    await db.execute(
                        """
                        INSERT INTO server_config 
                        (guild_id, pairing_channel_id, pairing_day, pairing_hour, admin_role_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (guild_id, pairing_channel_id, pairing_day or 'monday', pairing_hour or 9, admin_role_id)
                    )

                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting server config: {e}")
            return False

    async def get_server_config(self, guild_id: str) -> Optional[Dict]:
        """Get server configuration"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM server_config WHERE guild_id = ?",
                    (guild_id,)
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting server config: {e}")
            return None

    async def create_group(self, guild_id: str, member_ids: List[str], interests: List[str]) -> Optional[int]:
        """Create a group"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO groups (guild_id, member_ids, interests, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (guild_id, json.dumps(member_ids), json.dumps(interests), datetime.now().isoformat())
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating group: {e}")
            return None

    async def get_group(self, group_id: int) -> Optional[Dict]:
        """Get group details"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM groups WHERE id = ?",
                    (group_id,)
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting group: {e}")
            return None
