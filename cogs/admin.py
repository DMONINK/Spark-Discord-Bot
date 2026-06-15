"""
cogs/admin.py
Admin-only commands for Spark Bot:
  /spark setup       – configure channel and admin role
  /spark admin_stats – detailed admin view of server stats
  /spark force_pair  – manually trigger the auto-pairing job
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database as db

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
COLOR_INFO    = 0x7289DA
COLOR_SUCCESS = 0x43B581
COLOR_WARN    = 0xFAA61A
COLOR_ERROR   = 0xF04747
FOOTER_TEXT   = "⚡ Spark Bot"


def _spark_embed(title: str, description: str, color: int = COLOR_INFO) -> discord.Embed:
    """Factory for a standardised Spark embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _is_admin(interaction: discord.Interaction) -> bool:
    """
    Return True if the caller has Administrator permission OR
    holds the configured admin role for this guild.
    """
    if interaction.user.guild_permissions.administrator:
        return True
    # Will be checked async against DB if needed; basic check suffices here
    return False


async def _is_spark_admin(interaction: discord.Interaction) -> bool:
    """
    Async check: True if user has Administrator perm OR holds the
    configured admin_role_id for the guild.
    """
    if interaction.user.guild_permissions.administrator:
        return True
    config = await db.get_server_config(str(interaction.guild_id))
    if config and config.get("admin_role_id"):
        role = interaction.guild.get_role(int(config["admin_role_id"]))
        if role and role in interaction.user.roles:
            return True
    return False


# ── Cog ───────────────────────────────────────────────────────────────────────

class AdminCog(commands.Cog, name="Admin"):
    """Admin configuration and management commands for Spark Bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("AdminCog loaded.")

    # /spark setup ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="setup",
        description="[Admin] Configure Spark Bot for this server.",
    )
    @app_commands.describe(
        channel="The channel where pairing announcements will be posted",
        admin_role="The role that can manage Spark Bot settings",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        admin_role: discord.Role,
    ) -> None:
        """
        Admin-only setup command. Stores the pairing announcement channel
        and the admin role in server_config.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            # Permission check
            if not await _is_spark_admin(interaction):
                await interaction.followup.send(
                    embed=_spark_embed(
                        "🔒 Access Denied",
                        "You need **Administrator** permission or the Spark admin role to run this command.",
                        color=COLOR_ERROR,
                    ),
                    ephemeral=True,
                )
                return

            await db.upsert_server_config(
                guild_id=str(interaction.guild_id),
                pairing_channel_id=str(channel.id),
                admin_role_id=str(admin_role.id),
            )

            # Verify bot can send in that channel
            bot_member = interaction.guild.get_member(self.bot.user.id)
            perms = channel.permissions_for(bot_member)
            warning = ""
            if not perms.send_messages or not perms.embed_links:
                warning = (
                    "\n\n⚠️ **Warning:** I may not have permission to send embeds in "
                    f"{channel.mention}. Please check my channel permissions."
                )

            embed = _spark_embed(
                "✅ Spark Bot Configured!",
                f"**Pairing Channel:** {channel.mention}\n"
                f"**Admin Role:** {admin_role.mention}\n\n"
                f"Daily pairings will be announced in {channel.mention} at **9:00 AM IST**.\n"
                f"Use `/spark help` to see all available commands.{warning}",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Send a welcome message to the pairing channel
            try:
                welcome = _spark_embed(
                    "⚡ Spark Bot is Ready!",
                    "This is now the official Spark pairing channel! 🎉\n\n"
                    "Members can use `/spark interests` to set their interests "
                    "and `/spark match` to start connecting.\n"
                    "Daily pairings run at **9:00 AM IST** automatically.",
                    color=COLOR_SUCCESS,
                )
                await channel.send(embed=welcome)
            except discord.Forbidden:
                log.warning("Cannot post welcome in channel %s.", channel.id)

            log.info(
                "Guild %s configured: channel=%s, admin_role=%s",
                interaction.guild_id, channel.id, admin_role.id,
            )
        except Exception as exc:
            log.exception("Error in /spark setup for guild %s: %s", interaction.guild_id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark admin_stats ───────────────────────────────────────────────────────

    @app_commands.command(
        name="admin_stats",
        description="[Admin] View detailed server stats.",
    )
    async def admin_stats(self, interaction: discord.Interaction) -> None:
        """
        Admin-only command. Displays detailed statistics about the Spark
        installation on this server.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            if not await _is_spark_admin(interaction):
                await interaction.followup.send(
                    embed=_spark_embed(
                        "🔒 Access Denied",
                        "You need **Administrator** permission or the Spark admin role.",
                        color=COLOR_ERROR,
                    ),
                    ephemeral=True,
                )
                return

            data = await db.get_server_stats(str(interaction.guild_id))
            config = await db.get_server_config(str(interaction.guild_id))

            channel_mention = "Not configured"
            if config and config.get("pairing_channel_id"):
                ch = interaction.guild.get_channel(int(config["pairing_channel_id"]))
                channel_mention = ch.mention if ch else f"ID {config['pairing_channel_id']}"

            admin_role_name = "Not configured"
            if config and config.get("admin_role_id"):
                role = interaction.guild.get_role(int(config["admin_role_id"]))
                admin_role_name = role.mention if role else f"ID {config['admin_role_id']}"

            embed = _spark_embed(
                "🔧 Spark Admin Stats",
                f"Detailed overview for **{interaction.guild.name}**",
                color=COLOR_INFO,
            )

            embed.add_field(name="⚙️ Pairing Channel", value=channel_mention, inline=True)
            embed.add_field(name="🔑 Admin Role", value=admin_role_name, inline=True)
            embed.add_field(name="⏰ Pairing Schedule", value="Daily at 9:00 AM IST", inline=True)

            embed.add_field(name="👥 Registered Members", value=str(data["total_members"]), inline=True)
            embed.add_field(name="🤝 Total Pairings", value=str(data["total_pairings"]), inline=True)
            embed.add_field(name="💯 Avg Match Score", value=f"{data['avg_match_score']}%", inline=True)
            embed.add_field(name="🔥 Top Interest", value=data["most_popular_interest"], inline=True)

            # Full interest tally
            tally: dict[str, int] = data.get("interest_tally", {})
            if tally:
                sorted_interests = sorted(tally.items(), key=lambda x: x[1], reverse=True)
                tally_lines = "\n".join(
                    f"`{count:>3}` {interest}" for interest, count in sorted_interests
                )
                embed.add_field(name="📊 All Interests", value=tally_lines[:1024], inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /spark admin_stats for guild %s: %s", interaction.guild_id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark force_pair ────────────────────────────────────────────────────────

    @app_commands.command(
        name="force_pair",
        description="[Admin] Manually trigger the auto-pairing job right now.",
    )
    async def force_pair(self, interaction: discord.Interaction) -> None:
        """
        Admin-only command. Immediately runs the auto-pairing algorithm
        for this guild without waiting for the scheduled time.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            if not await _is_spark_admin(interaction):
                await interaction.followup.send(
                    embed=_spark_embed(
                        "🔒 Access Denied",
                        "You need **Administrator** permission or the Spark admin role.",
                        color=COLOR_ERROR,
                    ),
                    ephemeral=True,
                )
                return

            config = await db.get_server_config(str(interaction.guild_id))
            if not config or not config.get("pairing_channel_id"):
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚙️ Setup Required",
                        "Please run `/spark setup` before triggering pairings.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                embed=_spark_embed(
                    "⚡ Pairing Job Started",
                    "Running auto-pairing now… check the pairing channel shortly!",
                    color=COLOR_INFO,
                ),
                ephemeral=True,
            )

            # Access the matching cog's method
            matching_cog = self.bot.cogs.get("Matching")
            if matching_cog:
                await matching_cog._auto_pair_guild(interaction.guild)
            else:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚠️ Error",
                        "Matching cog is not loaded. Please restart the bot.",
                        color=COLOR_ERROR,
                    ),
                    ephemeral=True,
                )
                return

            log.info("Admin %s triggered manual pairing for guild %s.", interaction.user.id, interaction.guild_id)
        except Exception as exc:
            log.exception("Error in /spark force_pair for guild %s: %s", interaction.guild_id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Register the AdminCog with the bot."""
    await bot.add_cog(AdminCog(bot))
