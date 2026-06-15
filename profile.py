"""
Spark Bot - Profile Cog
Handles: /spark profile, /spark interests, /spark bio, /spark opt
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
from database import Database

logger = logging.getLogger(__name__)

# Interest categories
INTERESTS = [
    "Gaming", "Anime", "Music", "Art", "Coding", "Movies",
    "Books", "Fitness", "Cooking", "Photography", "Travel",
    "Science", "Sports", "Fashion", "Finance", "Pets",
    "Writing", "Design"
]

# Color palette
COLORS = {
    'info': 0x7289DA,      # Discord blurple
    'success': 0x43B581,   # Green
    'warning': 0xFAA61A,   # Yellow
    'error': 0xF04747      # Red
}


class Profile(commands.Cog):
    """Profile management commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    @app_commands.command(name="profile", description="View your Spark profile")
    async def profile(self, interaction: discord.Interaction):
        """Display user's profile"""
        try:
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)

            # Ensure member exists in database
            await self.db.add_member(user_id, guild_id, interaction.user.display_name)

            member = await self.db.get_member(user_id)
            
            if not member:
                await interaction.response.send_message(
                    "❌ Something sparked out — try again!",
                    ephemeral=True
                )
                return

            # Parse interests
            interests = json.loads(member['interests'] or '[]')
            interests_str = ", ".join(interests) if interests else "None set yet"

            # Create embed
            embed = discord.Embed(
                title=f"⚡ {member['display_name']}'s Profile",
                description=member['bio'] or "No bio set yet",
                color=COLORS['info'],
                timestamp=discord.utils.utcnow()
            )

            embed.add_field(
                name="🎮 Interests",
                value=interests_str,
                inline=False
            )

            embed.add_field(
                name="🔗 Connections",
                value=f"**Total Matches:** {member['total_matches'] or 0}\n**Streak:** 🔥 x {member['streak'] or 0}",
                inline=True
            )

            embed.add_field(
                name="📊 Status",
                value="✅ Opted In" if member['opt_in'] else "❌ Opted Out",
                inline=True
            )

            embed.add_field(
                name="📅 Joined",
                value=member['joined_at'][:10] if member['joined_at'] else "Unknown",
                inline=False
            )

            embed.set_footer(text="⚡ Spark Bot")

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in profile command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="interests", description="Set your interests (max 6)")
    async def interests(self, interaction: discord.Interaction):
        """Let user select interests from dropdown"""
        try:
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)

            # Ensure member exists
            await self.db.add_member(user_id, guild_id, interaction.user.display_name)

            # Create select menu
            select = InterestSelect(self.db, user_id)
            view = discord.ui.View()
            view.add_item(select)

            await interaction.response.send_message(
                "🎮 Pick up to 6 interests that describe you:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in interests command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="bio", description="Set your bio (max 150 characters)")
    @app_commands.describe(text="Your bio text")
    async def bio(self, interaction: discord.Interaction, text: str):
        """Set member's bio"""
        try:
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)

            # Ensure member exists
            await self.db.add_member(user_id, guild_id, interaction.user.display_name)

            # Validate length
            if len(text) > 150:
                await interaction.response.send_message(
                    "⚠️ Bio must be 150 characters or less!",
                    ephemeral=True
                )
                return

            # Update bio
            success = await self.db.update_bio(user_id, text)

            if success:
                embed = discord.Embed(
                    title="✅ Bio Updated",
                    description=f'"{text}"',
                    color=COLORS['success'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    "❌ Something sparked out — try again!",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in bio command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )

    @app_commands.command(name="opt", description="Toggle weekly pairing participation")
    @app_commands.describe(choice="in or out")
    async def opt(self, interaction: discord.Interaction, choice: str):
        """Toggle opt-in status"""
        try:
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)

            # Ensure member exists
            await self.db.add_member(user_id, guild_id, interaction.user.display_name)

            if choice.lower() not in ['in', 'out']:
                await interaction.response.send_message(
                    "⚠️ Please choose 'in' or 'out'",
                    ephemeral=True
                )
                return

            opt_in = choice.lower() == 'in'
            success = await self.db.set_opt_in(user_id, opt_in)

            if success:
                status = "✅ Opted In" if opt_in else "❌ Opted Out"
                embed = discord.Embed(
                    title="📊 Status Updated",
                    description=f"You are now {status} of weekly pairings",
                    color=COLORS['success'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    "❌ Something sparked out — try again!",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in opt command: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )


class InterestSelect(discord.ui.Select):
    """Multi-select dropdown for interests"""

    def __init__(self, db: Database, user_id: str):
        self.db = db
        self.user_id = user_id

        options = [discord.SelectOption(label=interest, value=interest) for interest in INTERESTS]

        super().__init__(
            placeholder="Select up to 6 interests...",
            min_values=0,
            max_values=6,
            options=options,
            custom_id="interest_select"
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle interest selection"""
        try:
            # Update database
            success = await self.db.update_interests(self.user_id, self.values)

            if success:
                interests_str = ", ".join(self.values) if self.values else "None"
                embed = discord.Embed(
                    title="✅ Interests Updated",
                    description=interests_str,
                    color=COLORS['success'],
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="⚡ Spark Bot")
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    "❌ Something sparked out — try again!",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error in interest select callback: {e}")
            await interaction.response.send_message(
                "❌ Something sparked out — try again!",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load cog"""
    await bot.add_cog(Profile(bot))
    logger.info("Profile cog loaded")
