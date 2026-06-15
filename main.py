"""
main.py
Entry point for Spark Bot — a social matchmaking Discord bot.
Loads all cogs, initialises the database, syncs slash commands,
and starts the keep-alive Flask server for Replit.
"""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database as db
from keep_alive import keep_alive

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("spark")

# ── Load env ───────────────────────────────────────────────────────────────────
load_dotenv()  # No-op on Replit (uses Secrets), loads .env locally
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    log.critical(
        "DISCORD_TOKEN is not set. "
        "Add it to your .env file (local) or Replit Secrets (cloud)."
    )
    sys.exit(1)

# ── Cog list ───────────────────────────────────────────────────────────────────
COGS = [
    "cogs.profile",
    "cogs.matching",
    "cogs.social",
    "cogs.admin",
]


# ── Bot class ──────────────────────────────────────────────────────────────────

class SparkBot(commands.Bot):
    """
    Main Spark Bot class.
    Uses commands.Bot with all intents enabled.
    Registers slash commands under the 'spark' group.
    """

    def __init__(self) -> None:
        intents = discord.Intents.all()
        super().__init__(
            command_prefix="!",  # Prefix unused; slash commands only
            intents=intents,
            help_command=None,  # Custom /spark help embed
        )

    async def setup_hook(self) -> None:
        """
        Called once when the bot is ready to start.
        Initialises the DB and loads all cogs.
        Slash commands are NOT synced here — see on_ready for explicit sync.
        """
        log.info("Running setup_hook…")
        await db.init_db()
        log.info("Database initialised.")

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as exc:
                log.exception("Failed to load cog %s: %s", cog, exc)

    async def on_ready(self) -> None:
        """
        Fired when the bot has connected and is ready.
        Syncs application (slash) commands globally.
        """
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)

        # Sync slash commands globally (may take up to 1 hour to propagate)
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash command(s) globally.", len(synced))
        except Exception as exc:
            log.exception("Failed to sync slash commands: %s", exc)

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for ⚡ /spark match",
            )
        )
        print(f"\n{'='*50}")
        print(f"  ⚡  Spark Bot is online!")
        print(f"  User : {self.user} ({self.user.id})")
        print(f"  Guilds: {len(self.guilds)}")
        print(f"{'='*50}\n")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Greet the server when the bot is added."""
        log.info("Joined new guild: %s (ID: %s)", guild.name, guild.id)
        # Try to find a suitable welcome channel
        target: discord.TextChannel | None = None
        for channel in guild.text_channels:
            if guild.get_member(self.user.id).guild_permissions.send_messages:
                target = channel
                break
        if target:
            try:
                embed = discord.Embed(
                    title="⚡ Spark Bot has arrived!",
                    description=(
                        "Hello! I'm **Spark**, your server's social matchmaking bot.\n\n"
                        "I connect members who share interests so they actually talk to each other!\n\n"
                        "**Get started:**\n"
                        "1. Ask an admin to run `/spark setup` to configure me.\n"
                        "2. Set your interests with `/spark interests`.\n"
                        "3. Find your match with `/spark match`!\n\n"
                        "Use `/spark help` for the full command list. Let's spark some connections! 🔥"
                    ),
                    color=0x7289DA,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_footer(text="⚡ Spark Bot")
                await target.send(embed=embed)
            except discord.Forbidden:
                pass

    async def on_application_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Global error handler for unhandled slash command errors."""
        log.error(
            "Unhandled error in command %s: %s",
            interaction.command.name if interaction.command else "unknown",
            error,
        )
        err_embed = discord.Embed(
            title="⚠️ Something Sparked Out",
            description="An unexpected error occurred. Please try again later.",
            color=0xF04747,
            timestamp=discord.utils.utcnow(),
        )
        err_embed.set_footer(text="⚡ Spark Bot")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=err_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=err_embed, ephemeral=True)
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    """Start the keep-alive server and then run the bot."""
    keep_alive()  # Launch Flask in background thread
    log.info("Keep-alive server started.")

    bot = SparkBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Spark Bot stopped by user.")
