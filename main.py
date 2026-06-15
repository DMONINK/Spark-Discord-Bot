"""
Spark Bot - Social Matchmaking Discord Bot
Main entry point
"""

import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot with all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Store reference to database module
from database import Database

db = Database()


class SparkBot(commands.Bot):
    """Custom bot class with setup hook for database initialization"""

    async def setup_hook(self):
        """Initialize database before bot connects"""
        logger.info("Setting up Spark Bot...")
        await db.initialize()
        logger.info("Database initialized")
        
        # Load all cogs
        cogs_dir = "cogs"
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                cog_name = filename[:-3]
                try:
                    await self.load_extension(f"cogs.{cog_name}")
                    logger.info(f"Loaded cog: {cog_name}")
                except Exception as e:
                    logger.error(f"Failed to load cog {cog_name}: {e}")

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f"Bot logged in as {self.user}")
        print(f"⚡ Spark Bot is online as {self.user}")
        
        # Sync commands with Discord
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

    async def on_error(self, event, *args, **kwargs):
        """Handle errors"""
        logger.error(f"Error in {event}", exc_info=True)


async def main():
    """Start the bot"""
    # Create bot instance
    bot_instance = SparkBot(command_prefix="!", intents=intents)
    
    # Load token from environment
    token = os.environ.get("DISCORD_TOKEN")
    
    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables!")
        print("❌ Please set DISCORD_TOKEN in your .env file or Replit Secrets")
        return
    
    # Start bot
    async with bot_instance:
        await bot_instance.start(token)


if __name__ == "__main__":
    asyncio.run(main())
