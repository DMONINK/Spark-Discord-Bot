"""
cogs/matching.py
Core matching engine for Spark Bot:
  /spark match  – on-demand best match
  /spark group  – group of 3-5 with shared interests + private channel
  /spark rate   – rate a pairing 1-5 stars
  Auto-pairing  – daily APScheduler job at 9 AM IST (GMT+5:30)
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Optional

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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

ICEBREAKERS = [
    "What's the last thing you got genuinely excited about?",
    "If you could master any skill overnight, what would it be?",
    "What's your most controversial opinion about your shared interest?",
    "What's something you're working on right now?",
    "What's the best thing you've discovered in the last month?",
    "Would you rather go deeper into your current hobby or pick up a totally new one?",
    "What's your hot take that nobody agrees with?",
    "What's something you used to love but grew out of?",
    "What are you currently obsessed with?",
    "What's a skill or hobby you wish more people knew about you?",
]

INTEREST_EMOJIS: dict[str, str] = {
    "Gaming": "🎮", "Anime": "⛩️", "Music": "🎵", "Art": "🎨",
    "Coding": "💻", "Movies": "🎬", "Books": "📚", "Fitness": "💪",
    "Cooking": "🍳", "Photography": "📷", "Travel": "✈️", "Science": "🔬",
    "Sports": "⚽", "Fashion": "👗", "Finance": "💰", "Pets": "🐾",
    "Writing": "✍️", "Design": "🖌️",
}

# Cooldown: 24 hours between on-demand /spark match calls per user
_match_cooldowns: dict[str, datetime] = {}
MATCH_COOLDOWN_HOURS = 24


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


# ── Matching algorithm ────────────────────────────────────────────────────────

def _score(interests_a: list[str], interests_b: list[str]) -> float:
    """
    Compute match score as:
      shared / max(len_a, len_b) * 100
    Returns 0.0 if either list is empty.
    """
    if not interests_a or not interests_b:
        return 0.0
    shared = set(interests_a) & set(interests_b)
    return round(len(shared) / max(len(interests_a), len(interests_b)) * 100, 1)


def _run_greedy_pairing(
    members: list[dict],
    recent_pairs: set[frozenset],
) -> list[tuple[dict, dict, float, list[str]]]:
    """
    Greedy pairing algorithm:
    1. Compute all possible (user_a, user_b) scores.
    2. Sort descending by score.
    3. Assign each user to at most one pair.
    4. Skip pairs that appeared in recent_pairs.
    Returns list of (member_a, member_b, score, shared_interests).
    """
    scored: list[tuple[float, dict, dict, list[str]]] = []
    for m1, m2 in combinations(members, 2):
        pair_key = frozenset({m1["user_id"], m2["user_id"]})
        if pair_key in recent_pairs:
            continue
        a_interests: list[str] = json.loads(m1["interests"] or "[]")
        b_interests: list[str] = json.loads(m2["interests"] or "[]")
        score = _score(a_interests, b_interests)
        shared = sorted(set(a_interests) & set(b_interests))
        scored.append((score, m1, m2, shared))

    scored.sort(key=lambda x: x[0], reverse=True)

    assigned: set[str] = set()
    results: list[tuple[dict, dict, float, list[str]]] = []
    for score, m1, m2, shared in scored:
        if m1["user_id"] in assigned or m2["user_id"] in assigned:
            continue
        assigned.add(m1["user_id"])
        assigned.add(m2["user_id"])
        results.append((m1, m2, score, shared))
    return results


def _find_best_match(
    target: dict,
    candidates: list[dict],
    recent_pairs: set[frozenset],
) -> Optional[tuple[dict, float, list[str]]]:
    """
    Find the single best candidate for `target` from the candidates list,
    skipping recent pairs and the target themselves.
    Returns (candidate, score, shared_interests) or None.
    """
    t_interests: list[str] = json.loads(target["interests"] or "[]")
    best: Optional[tuple[float, dict, list[str]]] = None

    for cand in candidates:
        if cand["user_id"] == target["user_id"]:
            continue
        pair_key = frozenset({target["user_id"], cand["user_id"]})
        if pair_key in recent_pairs:
            continue
        c_interests: list[str] = json.loads(cand["interests"] or "[]")
        score = _score(t_interests, c_interests)
        shared = sorted(set(t_interests) & set(c_interests))
        if best is None or score > best[0]:
            best = (score, cand, shared)

    if best is None:
        return None
    return best[1], best[0], best[2]


def _find_best_group(
    members: list[dict],
    size_min: int = 3,
    size_max: int = 5,
) -> Optional[tuple[list[dict], list[str]]]:
    """
    Find the group of 3-5 members with the highest average interest overlap.
    Returns (group_members, shared_interests) or None.
    """
    best_score = -1.0
    best_group: Optional[list[dict]] = None
    best_shared: list[str] = []

    # Try each size, take the best overall
    for size in range(size_min, size_max + 1):
        for combo in combinations(members, size):
            sets = [set(json.loads(m["interests"] or "[]")) for m in combo]
            shared = set.intersection(*sets)
            if not shared:
                continue
            # Score = shared / avg individual interest count
            avg_len = sum(len(s) for s in sets) / len(sets)
            score = len(shared) / avg_len * 100 if avg_len else 0
            if score > best_score:
                best_score = score
                best_group = list(combo)
                best_shared = sorted(shared)

    if not best_group:
        return None
    return best_group, best_shared


async def _send_match_dm(
    bot: commands.Bot,
    user_a: dict,
    user_b: dict,
    score: float,
    shared: list[str],
    pairing_id: int,
) -> None:
    """
    DM both users an introduction embed with:
    - Compatibility %
    - Shared interests
    - Ice-breaker question
    - Pairing ID for /spark rate
    Also celebrates a user's first match.
    """
    icebreaker = random.choice(ICEBREAKERS)
    shared_tags = " ".join(
        f"{INTEREST_EMOJIS.get(i, '⭐')} **{i}**" for i in shared
    ) or "_No exact overlap — discover new things together!_"

    for primary, other in [(user_a, user_b), (user_b, user_a)]:
        discord_user = bot.get_user(int(primary["user_id"]))
        if discord_user is None:
            try:
                discord_user = await bot.fetch_user(int(primary["user_id"]))
            except discord.NotFound:
                continue

        other_discord = bot.get_user(int(other["user_id"]))
        other_name = other_discord.display_name if other_discord else other["display_name"]
        other_bio = other["bio"] or "_No bio set yet._"

        embed = _spark_embed(
            f"⚡ You've been Sparked with {other_name}!",
            f"**Compatibility:** `{score:.1f}%`\n\n**About them:**\n> {other_bio}",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="🎯 Shared Interests", value=shared_tags, inline=False)
        embed.add_field(name="💬 Ice-Breaker Question", value=f"_{icebreaker}_", inline=False)
        embed.add_field(
            name="⭐ Rate Your Experience",
            value=f"After chatting, use `/spark rate` to rate this match!\n_(Pairing ID: {pairing_id})_",
            inline=False,
        )

        try:
            await discord_user.send(embed=embed)
            log.info("Sent match DM to user %s (pairing %d)", primary["user_id"], pairing_id)
        except discord.Forbidden:
            log.warning("Cannot DM user %s — DMs disabled.", primary["user_id"])

        # First-match celebration
        if primary["total_matches"] == 0:
            try:
                await asyncio.sleep(0.5)
                celebrate = _spark_embed(
                    "🎉 First Spark Connection!",
                    "You just made your **first Spark connection**! The community is better with you in it. Keep connecting! 🔥",
                    color=COLOR_SUCCESS,
                )
                await discord_user.send(embed=celebrate)
            except discord.Forbidden:
                pass

        # Monthly milestone DMs
        new_total = primary["total_matches"] + 1
        milestones = {5: "5 connections", 10: "10 connections", 25: "25 connections"}
        if new_total in milestones:
            try:
                milestone_embed = _spark_embed(
                    f"🏆 Milestone: {milestones[new_total]}!",
                    f"You've now made **{milestones[new_total]}** through Spark! "
                    f"You're one of the most connected members in the server. Keep it up! ✨",
                    color=COLOR_SUCCESS,
                )
                await discord_user.send(embed=milestone_embed)
            except discord.Forbidden:
                pass


# ── Cog ───────────────────────────────────────────────────────────────────────

class MatchingCog(commands.Cog, name="Matching"):
    """Matching commands and automated daily pairing job."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    async def cog_load(self) -> None:
        """Set up and start the APScheduler job when the cog loads."""
        # Default: every day at 9:00 AM IST (GMT+5:30)
        self.scheduler.add_job(
            self._auto_pair_all_guilds,
            CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),
            id="daily_auto_pair",
            replace_existing=True,
        )
        self.scheduler.start()
        log.info("MatchingCog loaded. Scheduler started (daily 09:00 IST).")

    def cog_unload(self) -> None:
        """Shutdown scheduler gracefully."""
        self.scheduler.shutdown(wait=False)
        log.info("MatchingCog unloaded. Scheduler stopped.")

    # ── Auto-pairing job ──────────────────────────────────────────────────────

    async def _auto_pair_all_guilds(self) -> None:
        """
        Daily auto-pairing job: runs for every configured guild.
        Fetches opted-in members, runs greedy pairing, DMs pairs,
        posts summary in pairing channel.
        """
        log.info("Auto-pairing job triggered.")
        for guild in self.bot.guilds:
            try:
                await self._auto_pair_guild(guild)
            except Exception as exc:
                log.exception("Auto-pairing failed for guild %s: %s", guild.id, exc)

    async def _auto_pair_guild(self, guild: discord.Guild) -> None:
        """Run the full pairing algorithm for a single guild."""
        config = await db.get_server_config(str(guild.id))
        if not config or not config.get("pairing_channel_id"):
            log.info("Guild %s has no pairing channel configured — skipping.", guild.id)
            return

        members = await db.get_all_opted_in_members(str(guild.id))
        # Filter: must have at least 1 interest
        members = [m for m in json.loads(json.dumps(members))
                   if json.loads(m["interests"] or "[]")]

        if len(members) < 2:
            log.info("Guild %s has fewer than 2 eligible members — skipping.", guild.id)
            return

        recent_pairs = await db.get_recent_pairs(str(guild.id), weeks=4)
        pairs = _run_greedy_pairing(members, recent_pairs)

        matched_count = 0
        member_map = {m["user_id"]: m for m in members}
        matched_ids: set[str] = set()

        for m1, m2, score, shared in pairs:
            pairing_id = await db.log_pairing(str(guild.id), m1["user_id"], m2["user_id"], score)
            await _send_match_dm(self.bot, m1, m2, score, shared, pairing_id)
            await db.increment_total_matches(m1["user_id"])
            await db.increment_total_matches(m2["user_id"])
            matched_ids.add(m1["user_id"])
            matched_ids.add(m2["user_id"])
            matched_count += 1
            await asyncio.sleep(0.5)  # Rate-limit DMs

        # Consolation DM for unmatched members
        unmatched = [m for m in members if m["user_id"] not in matched_ids]
        for m in unmatched:
            discord_user = self.bot.get_user(int(m["user_id"]))
            if discord_user:
                try:
                    consolation = _spark_embed(
                        "😔 No Auto-Match This Week",
                        "We couldn't find a fresh match for you this week, "
                        "but don't worry! Use `/spark match` to find your person on demand. 🔥",
                        color=COLOR_WARN,
                    )
                    await discord_user.send(embed=consolation)
                except discord.Forbidden:
                    pass

        # Post summary in pairing channel
        channel = guild.get_channel(int(config["pairing_channel_id"]))
        if channel and isinstance(channel, discord.TextChannel):
            summary = _spark_embed(
                "⚡ Daily Spark Pairings!",
                f"Today **{matched_count * 2} members** were matched into **{matched_count} pairs**! 🎉\n\n"
                f"Check your DMs for your introduction.\n"
                f"Use `/spark match` to find more connections anytime!",
                color=COLOR_SUCCESS,
            )
            summary.add_field(
                name="💡 Tip",
                value="Rate your match experience with `/spark rate` to build your streak! 🔥",
                inline=False,
            )
            await channel.send(embed=summary)

        log.info("Guild %s: auto-paired %d pairs.", guild.id, matched_count)

    # /spark match ─────────────────────────────────────────────────────────────

    @app_commands.command(name="match", description="Find your best match right now!")
    async def match(self, interaction: discord.Interaction) -> None:
        """
        On-demand matching: find the single best member for the caller
        based on interest overlap. DMs both users. 24-hour cooldown.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            user = interaction.user
            guild = interaction.guild
            await db.upsert_member(str(user.id), str(guild.id), user.display_name)

            # Check cooldown
            last_match = _match_cooldowns.get(str(user.id))
            if last_match:
                delta = datetime.now(timezone.utc) - last_match
                if delta < timedelta(hours=MATCH_COOLDOWN_HOURS):
                    remaining = timedelta(hours=MATCH_COOLDOWN_HOURS) - delta
                    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                    minutes = remainder // 60
                    await interaction.followup.send(
                        embed=_spark_embed(
                            "⏳ Slow Down, Spark!",
                            f"You already sparked a match recently.\n"
                            f"Next match available in **{hours}h {minutes}m**.",
                            color=COLOR_WARN,
                        ),
                        ephemeral=True,
                    )
                    return

            # Check setup
            config = await db.get_server_config(str(guild.id))
            if not config:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚙️ Setup Required",
                        "The bot isn't fully configured yet.\nAsk an admin to run `/spark setup` first!",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            target = await db.get_member(str(user.id))
            t_interests: list[str] = json.loads(target["interests"] or "[]")
            if not t_interests:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "🎯 Set Your Interests First",
                        "You need to set your interests before matching!\nUse `/spark interests` to get started.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            candidates = await db.get_all_opted_in_members(str(guild.id))
            candidates = [c for c in candidates if json.loads(c["interests"] or "[]")]
            recent_pairs = await db.get_recent_pairs(str(guild.id), weeks=4)

            result = _find_best_match(target, candidates, recent_pairs)
            if not result:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "😔 No Matches Found",
                        "We couldn't find a fresh match right now.\n"
                        "Try again later or encourage more members to set their interests!",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            partner, score, shared = result
            pairing_id = await db.log_pairing(str(guild.id), str(user.id), partner["user_id"], score)
            await db.increment_total_matches(str(user.id))
            await db.increment_total_matches(partner["user_id"])

            # Set cooldown
            _match_cooldowns[str(user.id)] = datetime.now(timezone.utc)

            # Send DMs
            await _send_match_dm(self.bot, target, partner, score, shared, pairing_id)

            # Confirm to caller
            partner_discord = self.bot.get_user(int(partner["user_id"]))
            partner_name = partner_discord.display_name if partner_discord else partner["display_name"]
            confirm = _spark_embed(
                "⚡ Match Found!",
                f"We found you a **{score:.1f}% match** with **{partner_name}**!\nCheck your DMs for the introduction. 🎉",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=confirm, ephemeral=True)

            # Subtle announcement in pairing channel
            if config.get("pairing_channel_id"):
                channel = guild.get_channel(int(config["pairing_channel_id"]))
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        announce = _spark_embed(
                            "⚡ Two members just connected!",
                            "Use `/spark match` to find your person! 🔥",
                            color=COLOR_INFO,
                        )
                        await channel.send(embed=announce)
                    except discord.Forbidden:
                        pass

            log.info(
                "On-demand match: %s <-> %s (score=%.1f, pairing=%d)",
                user.id, partner["user_id"], score, pairing_id,
            )
        except Exception as exc:
            log.exception("Error in /spark match for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    # /spark group ─────────────────────────────────────────────────────────────

    @app_commands.command(name="group", description="Create a group of 3-5 members with shared interests.")
    async def group(self, interaction: discord.Interaction) -> None:
        """
        Find the best group of 3-5 opted-in members by interest overlap.
        Create a temporary private text channel that auto-deletes after 72 hours.
        Announce in pairing channel.
        """
        await interaction.response.defer(ephemeral=False)
        try:
            guild = interaction.guild
            user = interaction.user
            await db.upsert_member(str(user.id), str(guild.id), user.display_name)

            config = await db.get_server_config(str(guild.id))
            if not config:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚙️ Setup Required",
                        "Ask an admin to run `/spark setup` first!",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            members = await db.get_all_opted_in_members(str(guild.id))
            members = [m for m in members if json.loads(m["interests"] or "[]")]

            if len(members) < 3:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "😔 Not Enough Members",
                        "Need at least **3 opted-in members with interests** to form a group.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            result = _find_best_group(members, size_min=3, size_max=5)
            if not result:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "😔 No Group Found",
                        "Couldn't find a group with enough shared interests.\n"
                        "Encourage more members to fill in their interests!",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            group_members, shared_interests = result

            # Create private channel with overwrites
            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
            }
            discord_members = []
            for m in group_members:
                du = guild.get_member(int(m["user_id"]))
                if du:
                    overwrites[du] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True
                    )
                    discord_members.append(du)

            shared_label = "-".join(shared_interests[:2]).lower().replace(" ", "") or "spark"
            channel_name = f"spark-group-{shared_label}"

            try:
                private_channel = await guild.create_text_channel(
                    name=channel_name,
                    overwrites=overwrites,
                    reason="Spark group channel (auto-deletes in 72h)",
                    topic=f"Spark group for: {', '.join(shared_interests)} | Auto-deletes in 72 hours",
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "🔒 Missing Permissions",
                        "I need the **Manage Channels** permission to create group channels.",
                        color=COLOR_ERROR,
                    ),
                    ephemeral=True,
                )
                return

            # Welcome message in new channel
            mentions = " ".join(m.mention for m in discord_members)
            shared_tags = " ".join(
                f"{INTEREST_EMOJIS.get(i, '⭐')} **{i}**" for i in shared_interests
            )
            icebreaker = random.choice(ICEBREAKERS)

            welcome = _spark_embed(
                f"⚡ Welcome to {channel_name}!",
                f"You've been grouped because you all share: {shared_tags}\n\n"
                f"**Ice-Breaker:** _{icebreaker}_\n\n"
                f"⏰ This channel **auto-deletes in 72 hours** — make it count!",
                color=COLOR_SUCCESS,
            )
            await private_channel.send(content=mentions, embed=welcome)

            # Log group to DB
            member_ids = [m["user_id"] for m in group_members]
            await db.log_group(str(guild.id), member_ids, shared_interests)

            # Announcement in pairing channel
            if config.get("pairing_channel_id"):
                announce_channel = guild.get_channel(int(config["pairing_channel_id"]))
                if announce_channel and isinstance(announce_channel, discord.TextChannel):
                    announce = _spark_embed(
                        "👥 New Spark Group Created!",
                        f"A group of **{len(group_members)} members** just connected over: {shared_tags}\n\n"
                        f"Use `/spark group` to start your own!",
                        color=COLOR_INFO,
                    )
                    await announce_channel.send(embed=announce)

            confirm = _spark_embed(
                "✅ Group Created!",
                f"Your group channel {private_channel.mention} is ready!\n"
                f"It will **auto-delete in 72 hours**.",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=confirm, ephemeral=True)

            # Schedule auto-deletion
            asyncio.create_task(self._delete_channel_after(private_channel, hours=72))
            log.info("Created group channel %s for guild %s", channel_name, guild.id)

        except Exception as exc:
            log.exception("Error in /spark group for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    async def _delete_channel_after(
        self,
        channel: discord.TextChannel,
        hours: int = 72,
    ) -> None:
        """
        Wait `hours` then attempt to delete the channel.
        Logs a warning if the channel was already deleted.
        """
        await asyncio.sleep(hours * 3600)
        try:
            await channel.delete(reason="Spark group channel expired (72h).")
            log.info("Auto-deleted group channel: %s", channel.name)
        except discord.NotFound:
            log.warning("Group channel %s already deleted.", channel.name)
        except discord.Forbidden:
            log.warning("No permission to delete group channel %s.", channel.name)

    # /spark rate ──────────────────────────────────────────────────────────────

    @app_commands.command(name="rate", description="Rate your last match experience (1-5 stars).")
    @app_commands.describe(stars="Your rating from 1 (poor) to 5 (amazing)")
    async def rate(self, interaction: discord.Interaction, stars: int) -> None:
        """
        Rate the most recent pairing. Updates the streak if ≥ 4 stars.
        Sends a ✨ DM confirmation.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            if stars < 1 or stars > 5:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚠️ Invalid Rating",
                        "Please rate between **1** and **5** stars.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            user = interaction.user
            pairing = await db.get_latest_pairing_for_user(str(user.id))

            if not pairing:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "😔 No Pairing Found",
                        "You don't have any pairings to rate yet.\nUse `/spark match` first!",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            updated = await db.mark_pairing_rated(pairing["id"], str(user.id), stars)
            if not updated:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "⚠️ Already Rated",
                        "You've already rated this pairing. Each match can only be rated once.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            # Update streak
            if stars >= 4:
                await db.update_streak(str(user.id), increment=True)
                streak_msg = "⬆️ Your streak grew! Keep connecting!"
            else:
                streak_msg = "💡 Rate 4+ stars to build your streak!"

            star_display = "⭐" * stars + "☆" * (5 - stars)
            embed = _spark_embed(
                "✨ Rating Submitted!",
                f"You rated your match experience: **{star_display}**\n\n{streak_msg}",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            log.info("User %s rated pairing %d: %d stars.", user.id, pairing["id"], stars)
        except Exception as exc:
            log.exception("Error in /spark rate for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Register the MatchingCog with the bot."""
    await bot.add_cog(MatchingCog(bot))
