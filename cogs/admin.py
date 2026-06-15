"""
Spark Bot - Admin Cog
Handles: /spark setup, weekly auto-pairing with APScheduler
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
import random
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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


class Admin(commands.Cog):
    """Admin and scheduling commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.scheduler = AsyncIOScheduler()

    async def cog_load(self):
        """Initialize scheduler when cog loads"""
        logger.info("Admin cog loading...")
        
        # Start scheduler
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("APScheduler started")

        # Add jobs for auto-pairing
        await self.schedule_daily_pairings()

    async def cog_unload(self):
        """Clean up scheduler when cog unloads"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler shut down")

    async def schedule_daily_pairings(self):
        """Schedule daily auto-pairing job for all guilds"""
        try:
            # Get all guilds the bot is in
            for guild in self.bot.guilds:
                guild_id = str(guild.id)

                # Get server config
                config = await self.db.get_server_config(guild_id)

                if not config:
                    # Skip if no config set up
                    continue

                # Parse schedule
                hour = config.get('pairing_hour', 9)
                day = config.get('pairing_day', 'monday')

                # Schedule job
                job_id = f"daily_pair_{guild_id}"

                # Remove existing job if it exists
                try:
                    self.scheduler.remove_job(job_id)
                except:
                    pass

                # Add new job
                self.scheduler.add_job(
                    self.run_daily_pairing,
                    'cron',
                    day_of_week=self.day_to_cron(day),
                    hour=hour,
                    minute=0,
                    id=job_id,
                    args=[guild_id]
                )

                logger.info(f"Scheduled daily pairing for guild {guild_id} at {day} {hour}:00")

        except Exception as e:
            logger.error(f"Error scheduling daily pairings: {e}")

    def day_to_cron(self, day: str) -> str:
        """Convert day name to cron format"""
        days = {
            'monday': 'mon',
            'tuesday': 'tue',
            'wednesday': 'wed',
            'thursday': 'thu',
            'friday': 'fri',
            'saturday': 'sat',
            'sunday': 'sun'
        }
        return days.get(day.lower(), 'mon')

    def calculate_match_score(self, interests1: list, interests2: list) -> float:
        """Calculate match score between two users"""
        if not interests1 or not interests2:
            return 0.0

        shared = len(set(interests1) & set(interests2))
        max_possible = max(len(interests1), len(interests2))

        if max_possible == 0:
            return 0.0

        return (shared / max_possible) * 100

    async def run_daily_pairing(self, guild_id: str):
        """Run daily pairing algorithm"""
        try:
            logger.info(f"Running daily pairing for guild {guild_id}")

            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                logger.error(f"Guild {guild_id} not found")
                return

            # Get config
            config = await self.db.get_server_config(guild_id)
            if not config or not config.get('pairing_channel_id'):
                logger.warning(f"No pairing channel configured for guild {guild_id}")
                return

            # Get all opt-in members
            members = await self.db.get_guild_members(guild_id, opt_in_only=True)

            if len(members) < 2:
                logger.warning(f"Not enough members for pairing in guild {guild_id}")
                return

            # Sort by activity (you could enhance this)
            # For now, just take top 100 most active or all if less
            members = members[:100]

            # Build match candidates
            pairings_to_make = []
            used_members = set()

            # Greedy matching algorithm
            for i, user1 in enumerate(members):
                if user1['user_id'] in used_members:
                    continue

                best_match = None
                best_score = -1

                for user2 in members[i+1:]:
                    if user2['user_id'] in used_members:
                        continue

                    # Check recent pairing history
                    recent = await self.db.get_recent_pairings(
                        user1['user_id'],
                        user2['user_id'],
                        days=28
                    )

                    if recent:
                        continue

                    # Calculate score
                    interests1 = json.loads(user1['interests'] or '[]')
                    interests2 = json.loads(user2['interests'] or '[]')
                    score = self.calculate_match_score(interests1, interests2)

                    if score > best_score:
                        best_score = score
                        best_match = user2

                if best_match and best_score > 0:
                    pairings_to_make.append((user1, best_match, best_score))
                    used_members.add(user1['user_id'])
                    used_members.add(best_match['user_id'])

            # Execute pairings
            matched_count = 0

            for user1, user2, score in pairings_to_make:
                try:
                    # Create pairing record
                    pairing_id = await self.db.create_pairing(
                        guild_id,
                        user1['user_id'],
                        user2['user_id'],
                        score
                    )

                    if pairing_id:
                        # Update match counts
                        await self.db.increment_match_count(user1['user_id'])
                        await self.db.increment_match_count(user2['user_id'])

                        # Send DMs
                        await self.send_pairing_dm(user1, user2, score)

                        matched_count += 1

                except Exception as e:
                    logger.error(f"Error in pairing {user1['user_id']} and {user2['user_id']}: {e}")

            # Send unmatched consolation messages
            unmatched = [m for m in members if m['user_id'] not in used_members]
            for member in unmatched:
                try:
                    user_obj = await self.bot.fetch_user(int(member['user_id']))
                    embed = discord.Embed(
                        title="⚡ No Match This Week",
                        description="Don't worry! Use `/spark match` anytime to find your person.",
                        color=COLORS['info'],
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="⚡ Spark Bot")
                    await user_obj.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error sending consolation message: {e}")

            # Announce in pairing channel
            try:
                channel = guild.get_channel(int(config['pairing_channel_id']))
                if channel:
                    announce_embed = discord.Embed(
                        title="🎉 Weekly Pairing Complete!",
                        description=f"This week, **{matched_count}** members were matched!",
                        color=COLORS['success'],
                        timestamp=discord.utils.utcnow()
                    )
                    announce_embed.add_field(
                        name="👥 Unmatched Members",
                        value=f"{len(unmatched)} members - use `/spark match` anytime",
                        inline=False
                    )
                    announce_embed.set_footer(text="⚡ Spark Bot")
                    await channel.send(embed=announce_embed)
            except Exception as e:
                logger.error(f"Error announcing pairings: {e}")

            logger.info(f"Daily pairing complete for guild {guild_id}: {matched_count} matches")

        except Exception as e:
            logger.error(f"Error in run_daily_pairing: {e}")

    async def send_pairing_dm(self, user1: dict, user2: dict, score: float):
        """Send pairing DMs to both users"""
        try:
            interests1 = json.loads(user1['interests'] or '[]')
            interests2 = json.loads(user2['interests'] or '[]')
            shared_interests = list(set(interests1) & set(interests2))

            ice_breaker = random.choice(ICE_BREAKERS)

            # Get Discord user objects
            try:
                disc_user1 = await self.bot.fetch_user(int(user1['user_id']))
                disc_user2 = await self.bot.fetch_user(int(user2['user_id']))
            except discord.NotFound:
                logger.error("One or both users not found for DM")
                return

            # Embed for user1
            embed1 = discord.Embed(
                title="⚡ Weekly Spark Match!",
                description=f"Meet {user2['display_name']}!",
                color=COLORS['success'],
                timestamp=discord.utils.utcnow()
            )
            embed1.add_field(name="👤 Bio", value=user2['bio'] or "No bio set", inline=False)
            embed1.add_field(
                name="🎮 Shared Interests",
                value=", ".join(shared_interests[:3]) if shared_interests else "Check out their profile!",
                inline=False
            )
            embed1.add_field(name="💡 Compatibility", value=f"{score:.1f}%", inline=True)
            embed1.add_field(name="❄️ Ice-breaker", value=ice_breaker, inline=False)
            embed1.set_footer(text="⚡ Spark Bot")

            # Embed for user2
            embed2 = discord.Embed(
                title="⚡ Weekly Spark Match!",
                description=f"Meet {user1['display_name']}!",
                color=COLORS['success'],
                timestamp=discord.utils.utcnow()
            )
            embed2.add_field(name="👤 Bio", value=user1['bio'] or "No bio set", inline=False)
            embed2.add_field(
                name="🎮 Shared Interests",
                value=", ".join(shared_interests[:3]) if shared_interests else "Check out their profile!",
                inline=False
            )
            embed2.add_field(name="💡 Compatibility", value=f"{score:.1f}%", inline=True)
            embed2.add_field(name="❄️ Ice-breaker", value=ice_breaker, inline=False)
            embed2.set_footer(text="⚡ Spark Bot")

            await disc_user1.send(embed=embed1)
            await disc_user2.send(embed=embed2)

        except Exception as e:
            logger.error(f"Error sending pairing DM: {e}")

    @app_commands.command(name="setup", description="Set up Spark for your server (admin only)")
    @app_commands.describe(
        channel="Announcement channel for pairing updates",
        admin_role="Role required to use admin commands"
    )
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel, admin_role: discord.Role):
        """Set up server configuration"""
        try:
            # Check if user is admin
            if not interaction.user.guild_permissions.administrator:
                embed = discord.Embed(
                    title="❌ Admin Required",
                    description="Only server administrators can run this command.",
                    color=COLORS['error'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            guild_id = str(interaction.guild.id)

            # Set server config
            success = await self.db.set_server_config(
                guild_id,
                pairing_channel_id=str(channel.id),
                pairing_day='monday',
                pairing_hour=9,
                admin_role_id=str(admin_role.id)
            )

            if success:
                # Re-schedule jobs
                await self.schedule_daily_pairings()

                embed = discord.Embed(
                    title="✅ Spark Configured!",
                    description=f"Server setup complete for {interaction.guild.name}",
                    color=COLORS['success'],
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="📢 Announcement Channel", value=channel.mention, inline=True)
                embed.add_field(name="🔐 Admin Role", value=admin_role.mention, inline=True)
                embed.add_field(
                    name="📅 Pairing Schedule",
                    value="Every Monday at 9:00 AM GMT+5:30",
                    inline=False
                )
                embed.add_field(
                    name="🚀 Next Steps",
                    value="1. Users run `/spark interests`\n2. Users run `/spark match` to start connecting\n3. Weekly auto-pairing happens every Monday!",
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
            logger.error(f"Error in setup command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load cog"""
    cog = Admin(bot)
    await bot.add_cog(cog)
    
    # Run cog_load
    await cog.cog_load()
    
    logger.info("Admin cog loaded")
