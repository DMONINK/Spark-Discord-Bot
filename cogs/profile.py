"""
cogs/profile.py
Handles all profile-related slash commands for Spark Bot:
  /spark profile   – view own profile card
  /spark interests – pick up to 6 interest categories
  /spark bio       – set a short bio
  /spark opt       – toggle weekly pairing opt-in/out
  /spark history   – view last 5 pairings
"""

import json
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database as db

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
INTERESTS = [
    "Gaming", "Anime", "Music", "Art", "Coding", "Movies",
    "Books", "Fitness", "Cooking", "Photography", "Travel",
    "Science", "Sports", "Fashion", "Finance", "Pets", "Writing", "Design",
]

INTEREST_EMOJIS: dict[str, str] = {
    "Gaming": "🎮", "Anime": "⛩️", "Music": "🎵", "Art": "🎨",
    "Coding": "💻", "Movies": "🎬", "Books": "📚", "Fitness": "💪",
    "Cooking": "🍳", "Photography": "📷", "Travel": "✈️", "Science": "🔬",
    "Sports": "⚽", "Fashion": "👗", "Finance": "💰", "Pets": "🐾",
    "Writing": "✍️", "Design": "🖌️",
}

COLOR_INFO    = 0x7289DA  # Discord blurple
COLOR_SUCCESS = 0x43B581  # green
COLOR_WARN    = 0xFAA61A  # yellow
COLOR_ERROR   = 0xF04747  # red

FOOTER_TEXT = "⚡ Spark Bot"


def _spark_embed(
    title: str,
    description: str,
    color: int = COLOR_INFO,
) -> discord.Embed:
    """Factory for a standardised Spark embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


class InterestSelect(discord.ui.Select):
    """
    A Select menu letting users pick up to 6 interests.
    """

    def __init__(self, current_interests: list[str]) -> None:
        options = [
            discord.SelectOption(
                label=interest,
                value=interest,
                emoji=INTEREST_EMOJIS.get(interest, "⭐"),
                default=interest in current_interests,
            )
            for interest in INTERESTS
        ]
        super().__init__(
            placeholder="Choose up to 6 interests…",
            min_values=1,
            max_values=6,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Save the selected interests to the database."""
        try:
            user = interaction.user
            await db.upsert_member(str(user.id), str(interaction.guild_id), user.display_name)
            await db.update_member_interests(str(user.id), self.values)

            tags = " ".join(
                f"{INTEREST_EMOJIS.get(i, '⭐')} **{i}**" for i in self.values
            )
            embed = _spark_embed(
                "✅ Interests Saved!",
                f"Your interests have been updated:\n\n{tags}",
                color=COLOR_SUCCESS,
            )
            await interaction.response.edit_message(embed=embed, view=None)
            log.info("User %s updated interests: %s", user.id, self.values)
        except Exception as exc:
            log.exception("Error saving interests for user %s: %s", interaction.user.id, exc)
            await interaction.response.send_message(
                embed=_spark_embed(
                    "⚠️ Oops!",
                    "Something sparked out — try again!",
                    color=COLOR_ERROR,
                ),
                ephemeral=True,
            )


class InterestView(discord.ui.View):
    """Wrapper View that holds the InterestSelect menu."""

    def __init__(self, current_interests: list[str]) -> None:
        super().__init__(timeout=120)
        self.add_item(InterestSelect(current_interests))


# ── Cog ───────────────────────────────────────────────────────────────────────

class ProfileCog(commands.Cog, name="Profile"):
    """Profile management commands for Spark Bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("ProfileCog loaded.")

    # /spark profile ───────────────────────────────────────────────────────────

    @app_commands.command(name="profile", description="View your Spark profile card.")
    async def profile(self, interaction: discord.Interaction) -> None:
        """
        Display the caller's profile as a styled embed showing interests,
        bio, total matches, streak, and opt-in status.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            user = interaction.user
            await db.upsert_member(str(user.id), str(interaction.guild_id), user.display_name)
            member = await db.get_member(str(user.id))

            interests: list[str] = json.loads(member["interests"] or "[]")
            bio = member["bio"] or "_No bio set. Use /spark bio to add one!_"
            streak = member["streak"]
            total = member["total_matches"]
            opted = member["opt_in"]

            tags = " ".join(
                f"{INTEREST_EMOJIS.get(i, '⭐')} {i}" for i in interests
            ) or "_None set — use /spark interests!_"

            streak_display = f"🔥 × {streak}" if streak > 0 else "No streak yet"
            opt_display = "✅ Opted In" if opted else "❌ Opted Out"

            embed = _spark_embed(
                f"⚡ {user.display_name}'s Spark Profile",
                bio,
                color=COLOR_INFO,
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="🎯 Interests", value=tags, inline=False)
            embed.add_field(name="🤝 Total Matches", value=str(total), inline=True)
            embed.add_field(name="🔥 Streak", value=streak_display, inline=True)
            embed.add_field(name="📬 Weekly Pairing", value=opt_display, inline=True)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /spark profile for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark interests ─────────────────────────────────────────────────────────

    @app_commands.command(name="interests", description="Set your interests (pick up to 6).")
    async def interests(self, interaction: discord.Interaction) -> None:
        """
        Open a Select Menu showing all 18 interest categories.
        User picks up to 6; selection is saved to the database.
        """
        try:
            user = interaction.user
            await db.upsert_member(str(user.id), str(interaction.guild_id), user.display_name)
            member = await db.get_member(str(user.id))
            current = json.loads(member["interests"] or "[]")

            embed = _spark_embed(
                "🎯 Choose Your Interests",
                "Select up to **6 interests** from the menu below.\nThese are used to find your best matches!",
                color=COLOR_INFO,
            )
            view = InterestView(current)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /spark interests for user %s: %s", interaction.user.id, exc)
            await interaction.response.send_message(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark bio ───────────────────────────────────────────────────────────────

    @app_commands.command(name="bio", description="Set a short bio for your profile (max 150 chars).")
    @app_commands.describe(text="Your bio text (max 150 characters)")
    async def bio(self, interaction: discord.Interaction, text: str) -> None:
        """
        Save a short bio (≤ 150 characters) for the user's profile.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            if len(text) > 150:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚠️ Too Long!",
                        f"Your bio must be **150 characters or fewer**. Yours is {len(text)} characters.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            user = interaction.user
            await db.upsert_member(str(user.id), str(interaction.guild_id), user.display_name)
            await db.update_member_bio(str(user.id), text)

            embed = _spark_embed(
                "✅ Bio Saved!",
                f"Your new bio:\n\n> {text}",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            log.info("User %s updated bio.", user.id)
        except Exception as exc:
            log.exception("Error in /spark bio for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark opt ───────────────────────────────────────────────────────────────

    @app_commands.command(name="opt", description="Toggle your participation in weekly pairings.")
    @app_commands.describe(choice="Choose 'in' to join or 'out' to leave weekly pairings")
    @app_commands.choices(choice=[
        app_commands.Choice(name="in",  value="in"),
        app_commands.Choice(name="out", value="out"),
    ])
    async def opt(self, interaction: discord.Interaction, choice: str) -> None:
        """
        Opt in or out of the automated weekly pairing cycle.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            user = interaction.user
            await db.upsert_member(str(user.id), str(interaction.guild_id), user.display_name)

            opted_in = choice == "in"
            await db.update_member_opt(str(user.id), opted_in)

            if opted_in:
                embed = _spark_embed(
                    "✅ You're In!",
                    "You've **opted in** to weekly pairings. Get ready to make connections! 🔥",
                    color=COLOR_SUCCESS,
                )
            else:
                embed = _spark_embed(
                    "👋 See You Later!",
                    "You've **opted out** of weekly pairings. You can opt back in anytime with `/spark opt in`.",
                    color=COLOR_WARN,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)
            log.info("User %s opted %s.", user.id, choice)
        except Exception as exc:
            log.exception("Error in /spark opt for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark history ───────────────────────────────────────────────────────────

    @app_commands.command(name="history", description="View your last 5 match pairings.")
    async def history(self, interaction: discord.Interaction) -> None:
        """
        Show the last 5 pairings for the calling user with dates and match scores.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            user = interaction.user
            await db.upsert_member(str(user.id), str(interaction.guild_id), user.display_name)
            pairings = await db.get_user_pairings(str(user.id), limit=5)

            if not pairings:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "📜 Match History",
                        "You haven't been paired with anyone yet!\nTry `/spark match` to find your first connection.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            embed = _spark_embed(
                "📜 Your Match History",
                f"Your last {len(pairings)} pairing(s):",
                color=COLOR_INFO,
            )

            for pairing in pairings:
                # Determine the partner
                partner_id = (
                    pairing["user2_id"]
                    if pairing["user1_id"] == str(user.id)
                    else pairing["user1_id"]
                )
                partner = self.bot.get_user(int(partner_id))
                partner_name = partner.display_name if partner else f"User {partner_id}"

                score = round(pairing["match_score"], 1)
                paired_at_str = pairing["paired_at"][:10]  # YYYY-MM-DD

                # Rating status
                if pairing["user1_id"] == str(user.id):
                    rated = pairing["user1_rated"]
                else:
                    rated = pairing["user2_rated"]
                rating_display = f"⭐ {rated}/5" if rated else "Not rated yet"

                embed.add_field(
                    name=f"🤝 {partner_name}",
                    value=f"📅 {paired_at_str} | 💯 {score}% match | {rating_display}",
                    inline=False,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Error in /spark history for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Register the ProfileCog with the bot."""
    await bot.add_cog(ProfileCog(bot))
