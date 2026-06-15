"""
Spark Bot - Matching Cog
Handles: /spark match, /spark group, /spark history, /spark rate
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from database import Database

logger = logging.getLogger(__name__)

# Color palette
COLORS = {
    'info': 0x7289DA,      # Discord blurple
    'success': 0x43B581,   # Green
    'warning': 0xFAA61A,   # Yellow
    'error': 0xF04747      # Red
}

# Ice-breaker questions
ICE_BREAKERS = [
    "What's the last thing you got genuinely excited about?",
    "If you could master any skill overnight, what would it be?",
    "What's your most controversial opinion about your shared interests?",
    "What's something you're working on right now?",
    "What's the best thing you've discovered in the last month?",
    "Would you rather A or B related to your shared interests?",
    "What's your hot take that nobody agrees with?",
    "What's something you used to love but grew out of?",
    "What are you currently obsessed with?",
    "What's a skill or hobby you wish more people knew about you?"
]

# Cooldown tracking (in-memory for this session)
MATCH_COOLDOWNS = {}


class Matching(commands.Cog):
    """Matching and pairing commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    def calculate_match_score(self, interests1: List[str], interests2: List[str]) -> float:
        """
        Calculate match score between two users.
        Score = (shared_interests / max_possible) * 100
        """
        if not interests1 or not interests2:
            return 0.0

        shared = len(set(interests1) & set(interests2))
        max_possible = max(len(interests1), len(interests2))

        if max_possible == 0:
            return 0.0

        return (shared / max_possible) * 100

    async def find_best_match(self, user_id: str, guild_id: str) -> Optional[Tuple[Dict, float]]:
        """Find the best match for a user"""
        try:
            user = await self.db.get_member(user_id)
            if not user:
                return None

            user_interests = json.loads(user['interests'] or '[]')
            if not user_interests:
                return None

            # Get all guild members except the user
            guild_members = await self.db.get_guild_members(guild_id)
            candidates = [m for m in guild_members if m['user_id'] != user_id and m['opt_in']]

            best_match = None
            best_score = -1

            for candidate in candidates:
                # Skip if recently paired
                recent = await self.db.get_recent_pairings(user_id, candidate['user_id'], days=28)
                if recent:
                    continue

                candidate_interests = json.loads(candidate['interests'] or '[]')
                score = self.calculate_match_score(user_interests, candidate_interests)

                if score > best_score:
                    best_score = score
                    best_match = candidate

            if best_match and best_score > 0:
                return (best_match, best_score)

            return None

        except Exception as e:
            logger.error(f"Error finding best match: {e}")
            return None

    async def send_match_dm(self, user1: Dict, user2: Dict, shared_interests: List[str], score: float):
        """Send match introduction DM to both users"""
        try:
            ice_breaker = random.choice(ICE_BREAKERS)

            # Get Discord user objects
            try:
                disc_user1 = await self.bot.fetch_user(int(user1['user_id']))
                disc_user2 = await self.bot.fetch_user(int(user2['user_id']))
            except discord.NotFound:
                logger.error("One or both users not found")
                return False

            # Embed for user1
            embed1 = discord.Embed(
                title="⚡ You've been matched!",
                description=f"Meet {user2['display_name']}!",
                color=COLORS['success'],
                timestamp=discord.utils.utcnow()
            )
            embed1.add_field(name="👤 Bio", value=user2['bio'] or "No bio set", inline=False)
            embed1.add_field(name="🎮 Shared Interests", value=", ".join(shared_interests[:3]), inline=False)
            embed1.add_field(
                name="💡 Compatibility",
                value=f"{score:.1f}%",
                inline=True
            )
            embed1.add_field(name="❄️ Ice-breaker", value=ice_breaker, inline=False)
            embed1.set_footer(text="⚡ Spark Bot")

            # Embed for user2
            embed2 = discord.Embed(
                title="⚡ You've been matched!",
                description=f"Meet {user1['display_name']}!",
                color=COLORS['success'],
                timestamp=discord.utils.utcnow()
            )
            embed2.add_field(name="👤 Bio", value=user1['bio'] or "No bio set", inline=False)
            embed2.add_field(name="🎮 Shared Interests", value=", ".join(shared_interests[:3]), inline=False)
            embed2.add_field(
                name="💡 Compatibility",
                value=f"{score:.1f}%",
                inline=True
            )
            embed2.add_field(name="❄️ Ice-breaker", value=ice_breaker, inline=False)
            embed2.set_footer(text="⚡ Spark Bot")

            await disc_user1.send(embed=embed1)
            await disc_user2.send(embed=embed2)

            return True

        except Exception as e:
            logger.error(f"Error sending match DM: {e}")
            return False

    @app_commands.command(name="match", description="Find your next Spark connection")
    async def match(self, interaction: discord.Interaction):
        """Find and create a match for user"""
        try:
            await interaction.response.defer(ephemeral=True)

            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)

            # Ensure member exists
            await self.db.add_member(user_id, guild_id, interaction.user.display_name)

            # Check cooldown
            cooldown_key = f"{guild_id}:{user_id}"
            if cooldown_key in MATCH_COOLDOWNS:
                cooldown_time = MATCH_COOLDOWNS[cooldown_key]
                if datetime.now() < cooldown_time:
                    remaining = (cooldown_time - datetime.now()).total_seconds() / 60
                    await interaction.followup.send(
                        f"⏳ You've already matched today! Try again in {remaining:.0f} minutes.",
                        ephemeral=True
                    )
                    return

            # Get user profile
            user = await self.db.get_member(user_id)
            if not user:
                await interaction.followup.send("❌ Could not find your profile!", ephemeral=True)
                return

            user_interests = json.loads(user['interests'] or '[]')
            if not user_interests:
                embed = discord.Embed(
                    title="🎯 Set Your Interests First!",
                    description="Use `/spark interests` to select what you love, then try matching again.",
                    color=COLORS['warning'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Find best match
            match_result = await self.find_best_match(user_id, guild_id)

            if not match_result:
                embed = discord.Embed(
                    title="🔍 No Compatible Matches Found",
                    description="Try setting more interests, or check back later when more members join!",
                    color=COLORS['info'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            match_user, match_score = match_result

            # Calculate shared interests
            shared_interests = list(set(user_interests) & set(json.loads(match_user['interests'] or '[]')))

            # Create pairing record
            pairing_id = await self.db.create_pairing(guild_id, user_id, match_user['user_id'], match_score)

            if not pairing_id:
                await interaction.followup.send(
                    "❌ Something sparked out — try again!",
                    ephemeral=True
                )
                return

            # Update match counts
            await self.db.increment_match_count(user_id)
            await self.db.increment_match_count(match_user['user_id'])

            # Send DMs
            await self.send_match_dm(user, match_user, shared_interests, match_score)

            # Set cooldown
            MATCH_COOLDOWNS[cooldown_key] = datetime.now() + timedelta(hours=24)

            # Send success embed
            embed = discord.Embed(
                title="⚡ Match Found!",
                description=f"You've been connected with {match_user['display_name']}!",
                color=COLORS['success'],
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="💡 Compatibility", value=f"{match_score:.1f}%", inline=True)
            embed.add_field(name="🎮 Shared Interests", value=", ".join(shared_interests), inline=True)
            embed.set_footer(text="⚡ Spark Bot")

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Announce in pairing channel
            config = await self.db.get_server_config(guild_id)
            if config and config['pairing_channel_id']:
                try:
                    channel = self.bot.get_channel(int(config['pairing_channel_id']))
                    if channel:
                        announce_embed = discord.Embed(
                            description="⚡ Two members just connected! Use `/spark match` to find your person.",
                            color=COLORS['info'],
                            timestamp=discord.utils.utcnow()
                        )
                        await channel.send(embed=announce_embed)
                except Exception as e:
                    logger.error(f"Error announcing match: {e}")

        except Exception as e:
            logger.error(f"Error in match command: {e}")
            await interaction.followup.send(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="group", description="Create a group with 3-5 people who share interests")
    async def group(self, interaction: discord.Interaction):
        """Create a group with shared interests"""
        try:
            await interaction.response.defer(ephemeral=True)

            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)

            # Ensure member exists
            await self.db.add_member(user_id, guild_id, interaction.user.display_name)

            # Get all guild members
            guild_members = await self.db.get_guild_members(guild_id, opt_in_only=True)

            if len(guild_members) < 3:
                await interaction.followup.send(
                    "❌ Not enough members in this server for a group!",
                    ephemeral=True
                )
                return

            # Find best group
            best_group = None
            best_score = -1

            for i, member1 in enumerate(guild_members):
                for member2 in guild_members[i+1:]:
                    interests1 = json.loads(member1['interests'] or '[]')
                    interests2 = json.loads(member2['interests'] or '[]')
                    shared = set(interests1) & set(interests2)

                    if len(shared) > 0:
                        # Find third member with overlap
                        for member3 in guild_members:
                            if member3['user_id'] not in [member1['user_id'], member2['user_id']]:
                                interests3 = json.loads(member3['interests'] or '[]')
                                shared_all = shared & set(interests3)

                                score = len(shared_all)
                                if score > best_score:
                                    best_score = score
                                    best_group = (member1, member2, member3, list(shared_all))

            if not best_group:
                await interaction.followup.send(
                    "❌ Could not find a compatible group at this time!",
                    ephemeral=True
                )
                return

            member1, member2, member3, shared_interests = best_group

            # Create private channel
            guild = interaction.guild
            everyone_role = guild.default_role

            overwrites = {
                everyone_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            try:
                user1_obj = await self.bot.fetch_user(int(member1['user_id']))
                user2_obj = await self.bot.fetch_user(int(member2['user_id']))
                user3_obj = await self.bot.fetch_user(int(member3['user_id']))

                overwrites[user1_obj] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                overwrites[user2_obj] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                overwrites[user3_obj] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            except discord.NotFound:
                pass

            channel_name = f"spark-group-{shared_interests[0].lower()[:10]}"
            group_channel = await guild.create_text_channel(
                channel_name,
                overwrites=overwrites,
                reason="Spark group creation"
            )

            # Store group in database
            member_ids = [member1['user_id'], member2['user_id'], member3['user_id']]
            group_id = await self.db.create_group(guild_id, member_ids, shared_interests)

            # Send welcome message to group
            welcome_embed = discord.Embed(
                title="⚡ Welcome to Your Spark Group!",
                description=f"You've been connected with {member2['display_name']} and {member3['display_name']}!",
                color=COLORS['success'],
                timestamp=discord.utils.utcnow()
            )
            welcome_embed.add_field(
                name="🎮 Shared Interests",
                value=", ".join(shared_interests),
                inline=False
            )
            welcome_embed.add_field(
                name="⏱️ Channel Duration",
                value="This channel will auto-delete in 72 hours",
                inline=False
            )
            welcome_embed.set_footer(text="⚡ Spark Bot")

            await group_channel.send(embed=welcome_embed)

            # Notify requestor
            await interaction.followup.send(
                f"✅ Group created! {group_channel.mention}",
                ephemeral=True
            )

            # Schedule channel deletion after 72 hours
            await self.schedule_channel_deletion(group_channel, 72 * 3600)

        except Exception as e:
            logger.error(f"Error in group command: {e}")
            await interaction.followup.send(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    async def schedule_channel_deletion(self, channel: discord.TextChannel, delay_seconds: int):
        """Schedule channel deletion after delay"""
        import asyncio
        await asyncio.sleep(delay_seconds)
        try:
            await channel.delete(reason="Spark group auto-delete after 72 hours")
        except Exception as e:
            logger.error(f"Error deleting channel: {e}")

    @app_commands.command(name="history", description="View your last 5 pairings")
    async def history(self, interaction: discord.Interaction):
        """Show user's pairing history"""
        try:
            user_id = str(interaction.user.id)

            pairings = await self.db.get_user_pairings(user_id, limit=5)

            if not pairings:
                embed = discord.Embed(
                    title="📜 No Pairings Yet",
                    description="Use `/spark match` to find your first connection!",
                    color=COLORS['info'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            embed = discord.Embed(
                title="📜 Your Pairing History",
                color=COLORS['info'],
                timestamp=discord.utils.utcnow()
            )

            for idx, pairing in enumerate(pairings, 1):
                other_id = pairing['user2_id'] if pairing['user1_id'] == user_id else pairing['user1_id']
                other_user = await self.db.get_member(other_id)

                pairing_date = pairing['paired_at'][:10] if pairing['paired_at'] else "Unknown"
                score = pairing['match_score'] or 0

                field_value = f"**Match Score:** {score:.1f}%\n**Date:** {pairing_date}"
                embed.add_field(
                    name=f"{idx}. {other_user['display_name'] if other_user else 'Unknown'}",
                    value=field_value,
                    inline=False
                )

            embed.set_footer(text="⚡ Spark Bot")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in history command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="rate", description="Rate your match experience (1-5 stars)")
    @app_commands.describe(stars="Rating from 1 to 5")
    async def rate(self, interaction: discord.Interaction, stars: int):
        """Rate a pairing"""
        try:
            if stars < 1 or stars > 5:
                await interaction.response.send_message(
                    "⚠️ Please rate between 1 and 5 stars!",
                    ephemeral=True
                )
                return

            user_id = str(interaction.user.id)

            # Get user's latest pairing
            pairings = await self.db.get_user_pairings(user_id, limit=1)

            if not pairings:
                await interaction.response.send_message(
                    "❌ You don't have a pairing to rate yet!",
                    ephemeral=True
                )
                return

            pairing = pairings[0]
            pairing_id = pairing['id']

            # Rate pairing
            success = await self.db.rate_pairing(pairing_id, user_id, stars)

            if success:
                star_str = "⭐" * stars
                embed = discord.Embed(
                    title="✅ Rating Submitted",
                    description=f"You rated this match: {star_str}",
                    color=COLORS['success'],
                    timestamp=discord.utils.utcnow()
                )

                if stars >= 4:
                    embed.add_field(
                        name="🔥 Streak Increased!",
                        value="Keep finding great matches!",
                        inline=False
                    )

                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    "❌ Something sparked out — try again!",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in rate command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load cog"""
    await bot.add_cog(Matching(bot))
    logger.info("Matching cog loaded")
