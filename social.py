"""
Spark Bot - Social Cog
Handles: /spark leaderboard, /spark stats, /spark help
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
from database import Database

logger = logging.getLogger(__name__)

# Color palette
COLORS = {
    'info': 0x7289DA,      # Discord blurple
    'success': 0x43B581,   # Green
    'warning': 0xFAA61A,   # Yellow
    'error': 0xF04747      # Red
}


class Social(commands.Cog):
    """Social and stats commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    @app_commands.command(name="leaderboard", description="View top connected members")
    async def leaderboard(self, interaction: discord.Interaction):
        """Show top members by match count"""
        try:
            guild_id = str(interaction.guild.id)

            top_members = await self.db.get_top_members(guild_id, limit=10)

            if not top_members:
                embed = discord.Embed(
                    title="🏆 Leaderboard",
                    description="No members yet! Use `/spark match` to start connecting.",
                    color=COLORS['info'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            embed = discord.Embed(
                title="🏆 Spark Leaderboard",
                description="Most Connected Members",
                color=COLORS['info'],
                timestamp=discord.utils.utcnow()
            )

            medals = ["🥇", "🥈", "🥉"]

            for idx, member in enumerate(top_members, 1):
                medal = medals[idx - 1] if idx <= 3 else f"{idx}."

                streak_str = f"🔥 x {member['streak']}" if member['streak'] else "No streak"

                field_value = f"**Connections:** {member['total_matches']}\n**Streak:** {streak_str}"

                embed.add_field(
                    name=f"{medal} {member['display_name']}",
                    value=field_value,
                    inline=False
                )

            embed.set_footer(text="⚡ Spark Bot")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in leaderboard command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="stats", description="View server-wide Spark statistics")
    async def stats(self, interaction: discord.Interaction):
        """Show guild statistics"""
        try:
            guild_id = str(interaction.guild.id)

            stats = await self.db.get_guild_stats(guild_id)

            embed = discord.Embed(
                title="📊 Spark Server Stats",
                color=COLORS['info'],
                timestamp=discord.utils.utcnow()
            )

            embed.add_field(
                name="👥 Total Members",
                value=str(stats['total_members']),
                inline=True
            )

            embed.add_field(
                name="🔗 Total Pairings",
                value=str(stats['total_pairings']),
                inline=True
            )

            embed.add_field(
                name="💡 Avg Match Score",
                value=f"{stats['avg_match_score']:.1f}%",
                inline=True
            )

            embed.add_field(
                name="🎮 Most Popular Interest",
                value=stats['most_popular_interest'],
                inline=True
            )

            embed.set_footer(text="⚡ Spark Bot")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="help", description="View all Spark commands")
    async def help(self, interaction: discord.Interaction):
        """Show help embed with all commands"""
        try:
            embed = discord.Embed(
                title="⚡ Spark Bot Commands",
                description="Social matchmaking for your server",
                color=COLORS['info'],
                timestamp=discord.utils.utcnow()
            )

            # Profile Commands
            embed.add_field(
                name="👤 Profile Commands",
                value=(
                    "`/spark profile` - View your profile card\n"
                    "`/spark interests` - Select your interests (max 6)\n"
                    "`/spark bio [text]` - Set your bio (max 150 chars)\n"
                    "`/spark opt [in/out]` - Toggle weekly pairing participation"
                ),
                inline=False
            )

            # Matching Commands
            embed.add_field(
                name="🎯 Matching Commands",
                value=(
                    "`/spark match` - Find your next connection\n"
                    "`/spark group` - Create a group with shared interests\n"
                    "`/spark history` - View your last 5 pairings\n"
                    "`/spark rate [1-5]` - Rate your match experience"
                ),
                inline=False
            )

            # Social Commands
            embed.add_field(
                name="📊 Social Commands",
                value=(
                    "`/spark leaderboard` - Top 10 most connected members\n"
                    "`/spark stats` - Server-wide statistics\n"
                    "`/spark help` - Show this help message"
                ),
                inline=False
            )

            # Admin Commands
            embed.add_field(
                name="⚙️ Admin Commands",
                value=(
                    "`/spark setup [channel] [role]` - Set up announcements (admin only)"
                ),
                inline=False
            )

            embed.add_field(
                name="ℹ️ Getting Started",
                value=(
                    "1. Run `/spark interests` to choose what you love\n"
                    "2. Optionally set `/spark bio` to tell others about yourself\n"
                    "3. Use `/spark match` to find connections\n"
                    "4. Rate matches with `/spark rate` to build your streak!"
                ),
                inline=False
            )

            embed.set_footer(text="⚡ Spark Bot")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load cog"""
    await bot.add_cog(Social(bot))
    logger.info("Social cog loaded")
