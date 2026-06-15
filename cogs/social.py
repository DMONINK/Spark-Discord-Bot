"""
cogs/social.py
Social and discovery commands for Spark Bot:
  /spark leaderboard – top 10 most-connected members
  /spark stats       – server-wide stats
  /spark help        – all commands overview
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

RANK_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


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


# ── Cog ───────────────────────────────────────────────────────────────────────

class SocialCog(commands.Cog, name="Social"):
    """Social and discovery commands for Spark Bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("SocialCog loaded.")

    # /spark leaderboard ───────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="See the top 10 most-connected members.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        """
        Display a ranked embed of the top 10 members by total_matches.
        Includes rank medal, display name, match count, and streak.
        """
        await interaction.response.defer()
        try:
            top = await db.get_leaderboard(str(interaction.guild_id), limit=10)

            if not top:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "📊 Leaderboard",
                        "No members on the board yet — be the first to `/spark match`!",
                        color=COLOR_WARN,
                    )
                )
                return

            embed = _spark_embed(
                "🏆 Spark Leaderboard — Top Connectors",
                "The most connected members in the server:",
                color=COLOR_INFO,
            )

            lines = []
            for rank, member in enumerate(top, start=1):
                # Try to resolve current display name from Discord
                discord_member = interaction.guild.get_member(int(member["user_id"]))
                name = discord_member.display_name if discord_member else member["display_name"]

                medal = RANK_MEDALS.get(rank, f"`{rank}.`")
                streak_str = f"🔥×{member['streak']}" if member["streak"] > 0 else ""
                lines.append(
                    f"{medal} **{name}** — {member['total_matches']} matches {streak_str}"
                )

            embed.description = "\n".join(lines)
            embed.add_field(
                name="💡 Want to climb the ranks?",
                value="Use `/spark match` to make more connections!",
                inline=False,
            )

            await interaction.followup.send(embed=embed)
            log.info("Leaderboard displayed for guild %s.", interaction.guild_id)
        except Exception as exc:
            log.exception("Error in /spark leaderboard for guild %s: %s", interaction.guild_id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR)
            )

    # /spark stats ─────────────────────────────────────────────────────────────

    @app_commands.command(name="stats", description="View server-wide Spark statistics.")
    async def stats(self, interaction: discord.Interaction) -> None:
        """
        Display an embed with server-wide stats:
        total registered members, total pairings, avg match score,
        most popular interest, and top trending interests.
        """
        await interaction.response.defer()
        try:
            data = await db.get_server_stats(str(interaction.guild_id))

            embed = _spark_embed(
                "📊 Spark Server Stats",
                f"Here's how **{interaction.guild.name}** is connecting!",
                color=COLOR_INFO,
            )

            embed.add_field(
                name="👥 Registered Members",
                value=str(data["total_members"]),
                inline=True,
            )
            embed.add_field(
                name="🤝 Total Pairings",
                value=str(data["total_pairings"]),
                inline=True,
            )
            embed.add_field(
                name="💯 Avg Match Score",
                value=f"{data['avg_match_score']}%",
                inline=True,
            )
            embed.add_field(
                name="🔥 Most Popular Interest",
                value=data["most_popular_interest"],
                inline=True,
            )

            # Trending interests (top 5)
            tally: dict[str, int] = data.get("interest_tally", {})
            if tally:
                top5 = sorted(tally.items(), key=lambda x: x[1], reverse=True)[:5]
                trending = "\n".join(
                    f"`{count}` members — **{interest}**"
                    for interest, count in top5
                )
                embed.add_field(name="📈 Trending Interests", value=trending, inline=False)

            embed.add_field(
                name="💡 Grow the community!",
                value="Invite friends and use `/spark match` to keep the connections flowing.",
                inline=False,
            )

            await interaction.followup.send(embed=embed)
            log.info("Stats displayed for guild %s.", interaction.guild_id)
        except Exception as exc:
            log.exception("Error in /spark stats for guild %s: %s", interaction.guild_id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR)
            )

    # /spark help ──────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="See all Spark commands and what they do.")
    async def help(self, interaction: discord.Interaction) -> None:
        """
        Display a colour-coded embed listing all commands grouped by category.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            embed = _spark_embed(
                "⚡ Spark Bot — Command Guide",
                "Connect with members who share your interests. Here's everything you can do:",
                color=COLOR_INFO,
            )

            embed.add_field(
                name="👤 Profile",
                value=(
                    "`/spark profile` — View your profile card\n"
                    "`/spark interests` — Set your interests (up to 6)\n"
                    "`/spark bio [text]` — Set a short bio (max 150 chars)\n"
                    "`/spark opt [in/out]` — Toggle weekly pairing participation\n"
                    "`/spark history` — View your last 5 pairings"
                ),
                inline=False,
            )

            embed.add_field(
                name="🤝 Matching",
                value=(
                    "`/spark match` — Find your best match right now (24h cooldown)\n"
                    "`/spark group` — Create a group of 3-5 members with shared interests\n"
                    "`/spark rate [1-5]` — Rate your latest match experience"
                ),
                inline=False,
            )

            embed.add_field(
                name="📊 Social",
                value=(
                    "`/spark leaderboard` — Top 10 most-connected members\n"
                    "`/spark stats` — Server-wide connection statistics"
                ),
                inline=False,
            )

            embed.add_field(
                name="⚙️ Admin",
                value=(
                    "`/spark setup [channel] [admin_role]` — Configure the bot (admin only)\n"
                    "`/spark admin_stats` — Detailed admin statistics\n"
                    "`/spark force_pair` — Trigger auto-pairing manually (admin only)"
                ),
                inline=False,
            )

            embed.add_field(
                name="🔥 Streak System",
                value=(
                    "Rate your matches 4+ stars to build a streak!\n"
                    "Streaks show on the leaderboard and your profile."
                ),
                inline=False,
            )

            embed.add_field(
                name="🎁 Interest Categories",
                value=(
                    "Gaming · Anime · Music · Art · Coding · Movies · Books · Fitness · "
                    "Cooking · Photography · Travel · Science · Sports · Fashion · Finance · "
                    "Pets · Writing · Design"
                ),
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /spark help for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Register the SocialCog with the bot."""
    await bot.add_cog(SocialCog(bot))
