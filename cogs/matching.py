"""
cogs/matching.py
Core matching engine for Spark Bot:
  /spark match  – on-demand best match
  /spark group  – group of 3-5 with shared interests + private channel
  /spark rate   – rate a pairing 1-5 stars
  Auto-pairing  – daily APScheduler job at 9 AM IST (GMT+5:30)

Matching priority (applied to EVERY match command):
  1. If both users have interests → interest overlap score
  2. If no interests → gender-based matching (Male ↔ Female only)
     Gender detected from: server roles → Discord bio → display name
"""

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Literal, Optional

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

# ── Gender keyword tables ─────────────────────────────────────────────────────
# Any role name, bio substring, or display name keyword that maps to a gender.
# Matching is case-insensitive and whole-word where possible.

_MALE_KEYWORDS: set[str] = {
    # Basic
    "male", "man", "men", "boy", "guy", "guys", "gentleman", "gentlemen",
    "sir", "mister", "mr",
    # Pronouns
    "he", "him", "he/him", "he • him", "♂",
    # Titles / nobility
    "lord", "duke", "emperor", "baron", "nobleman", "sire", "monsieur",
    "king", "prince", "sultan", "tsar", "pharaoh",
    # Casual / slang
    "boi", "hubby", "bear", "bro", "lad", "fella", "chap", "bloke",
    "fellow", "broski", "dude", "homie", "himbo", "sigma", "chad",
    "gigachad", "rizzler", "broccoli head", "fortnite boy", "grill master",
    "monke", "npc male", "xy", "testosterone", "beard",
    # Fantasy / archetype
    "warrior", "knight", "hunter", "wizard", "gladiator", "samurai",
    "paladin", "hero", "senpai", "oni", "demon king", "dragon lord",
    "mage", "swordsman", "husbando", "zeus", "apollo", "odin", "thor",
    "hades", "ares", "king arthur",
    # Animal
    "stallion", "buck", "rooster", "drake", "ram", "bull", "peacock",
    "lion", "wolf", "tiger",
    # Space / sci-fi
    "astronaut", "commander", "pilot", "cyborg", "spartan",
    "galaxy king", "starboy", "solar king",
    # Nature / abstract
    "sun", "fire", "gold", "day", "coffee", "rose", "angel",
    "chaos", "storm", "sword", "hawk", "dragon", "thunder",
    # Emoji / symbol
    "🗿", "👑", "🦁", "🔥", "🌞", "⚔️", "🐺", "💙", "🍺",
    "m", "xy gang", "boys™", "lads", "stags", "wolves", "spartans",
    "swordsmen", "heroes", "alphas", "princes", "lords",
    # Mixed slang
    "king", "daddy", "based", "goofy ahh boy",
}

_FEMALE_KEYWORDS: set[str] = {
    # Basic
    "female", "woman", "women", "girl", "girls", "lady", "ladies",
    "madam", "miss", "ms", "mrs",
    # Pronouns
    "she", "her", "she/her", "she • her", "♀",
    # Titles / nobility
    "duchess", "empress", "baroness", "noblewoman", "dame", "madame",
    "queen", "princess", "sultana", "tsarina", "cleopatra",
    # Casual / slang
    "gurl", "wifey", "kitty", "bunny", "sis", "lass", "gal",
    "dudette", "bestie", "bimbo", "diva", "stacy", "gigastacy",
    "rizz queen", "alpha queen", "sephora kid", "starbucks girl",
    "kitchen queen", "monkette", "npc female", "xx", "estrogen", "makeup",
    # Fantasy / archetype
    "valkyrie", "maiden", "huntress", "witch", "sorceress", "heroine",
    "kouhai", "kitsune", "demon queen", "dragon lady", "swordmaiden",
    "waifu", "hera", "artemis", "freya", "sif", "persephone", "athena",
    "guinevere",
    # Animal
    "mare", "doe", "hen", "duck", "ewe", "cow", "peahen",
    "lioness", "vixen", "tigress",
    # Space / sci-fi
    "navigator", "android", "galaxy queen", "stargirl", "lunar queen",
    # Nature / abstract
    "moon", "ice", "silver", "night", "tea", "ocean", "sky", "thorn",
    "devil", "order", "calm", "shield", "dove", "phoenix", "lightning",
    # Emoji / symbol
    "🎀", "🦋", "❄️", "🌙", "🪄", "🦊", "🩷", "🍷",
    "f", "xx gang", "girls™", "lassies", "does", "foxes", "valkyries",
    "maidens", "heroines", "divas", "princesses", "ladies",
    # Mixed slang
    "queen", "mommy", "barbie", "slay", "slay girl", "sigma queen",
    "boss lady",
}


def _detect_gender(member: discord.Member) -> Literal["male", "female", "unknown"]:
    """
    Detect the gender of a Discord guild member by scanning:
      1. All role names
      2. The member's Discord bio (about me / global_name fallback)
      3. The member's display name / nickname

    Returns 'male', 'female', or 'unknown'.
    A simple vote system: whichever gender gets more keyword hits wins.
    Ties or zero hits → 'unknown'.
    """
    male_hits = 0
    female_hits = 0

    def _scan(text: str) -> None:
        nonlocal male_hits, female_hits
        if not text:
            return
        lowered = text.lower()
        # Check each keyword as a word/phrase within the text
        for kw in _MALE_KEYWORDS:
            pattern = r'(?<!\w)' + re.escape(kw.lower()) + r'(?!\w)'
            if re.search(pattern, lowered):
                male_hits += 1
        for kw in _FEMALE_KEYWORDS:
            pattern = r'(?<!\w)' + re.escape(kw.lower()) + r'(?!\w)'
            if re.search(pattern, lowered):
                female_hits += 1

    # 1. Scan all role names (weighted x2 — roles are explicit labels)
    for role in member.roles:
        _scan(role.name)
        _scan(role.name)  # double weight

    # 2. Scan display name / nickname
    _scan(member.display_name)
    if member.nick:
        _scan(member.nick)

    # 3. Scan global name (Discord display name set by user)
    if hasattr(member, "global_name") and member.global_name:
        _scan(member.global_name)

    log.debug(
        "Gender detection for %s: male_hits=%d female_hits=%d",
        member.id, male_hits, female_hits,
    )

    if male_hits > female_hits:
        return "male"
    if female_hits > male_hits:
        return "female"
    return "unknown"


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── Interest-based scoring ────────────────────────────────────────────────────

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


def _has_interests(member: dict) -> bool:
    """Return True if the member has at least one interest set."""
    return bool(json.loads(member.get("interests") or "[]"))


# ── Gender-based pairing helpers ──────────────────────────────────────────────

def _split_by_gender(
    members: list[dict],
    guild: discord.Guild,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Split DB member dicts into (males, females, unknowns)
    by resolving each to a discord.Member and running gender detection.
    """
    males: list[dict] = []
    females: list[dict] = []
    unknowns: list[dict] = []

    for m in members:
        guild_member = guild.get_member(int(m["user_id"]))
        if guild_member is None:
            unknowns.append(m)
            continue
        gender = _detect_gender(guild_member)
        if gender == "male":
            males.append(m)
        elif gender == "female":
            females.append(m)
        else:
            unknowns.append(m)

    return males, females, unknowns


def _gender_greedy_pairing(
    males: list[dict],
    females: list[dict],
    recent_pairs: set[frozenset],
) -> list[tuple[dict, dict, float, list[str]]]:
    """
    Pair males with females only.
    Since there are no interests, score = 50.0 (random baseline).
    Greedy: shuffle both lists, zip them, skip recent pairs.
    Returns list of (male_member, female_member, score, shared_interests=[]).
    """
    random.shuffle(males)
    random.shuffle(females)

    assigned: set[str] = set()
    results: list[tuple[dict, dict, float, list[str]]] = []

    for m in males:
        if m["user_id"] in assigned:
            continue
        for f in females:
            if f["user_id"] in assigned:
                continue
            pair_key = frozenset({m["user_id"], f["user_id"]})
            if pair_key in recent_pairs:
                continue
            assigned.add(m["user_id"])
            assigned.add(f["user_id"])
            results.append((m, f, 50.0, []))
            break

    return results


def _gender_find_best_match(
    target: dict,
    target_gender: Literal["male", "female", "unknown"],
    candidates: list[dict],
    guild: discord.Guild,
    recent_pairs: set[frozenset],
) -> Optional[tuple[dict, float, list[str]]]:
    """
    Find the best opposite-gender candidate for target.
    If target gender is unknown, skip gender-based matching.
    Returns (candidate, score, []) or None.
    """
    if target_gender == "unknown":
        return None

    opposite = "female" if target_gender == "male" else "male"

    for cand in candidates:
        if cand["user_id"] == target["user_id"]:
            continue
        pair_key = frozenset({target["user_id"], cand["user_id"]})
        if pair_key in recent_pairs:
            continue
        guild_member = guild.get_member(int(cand["user_id"]))
        if guild_member is None:
            continue
        if _detect_gender(guild_member) == opposite:
            return cand, 50.0, []

    return None


# ── Interest-based pairing helpers ────────────────────────────────────────────

def _run_greedy_pairing(
    members: list[dict],
    recent_pairs: set[frozenset],
) -> list[tuple[dict, dict, float, list[str]]]:
    """
    Greedy interest-based pairing:
    1. Score all possible pairs by interest overlap.
    2. Sort descending.
    3. Assign each user to at most one pair.
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


def _find_best_interest_match(
    target: dict,
    candidates: list[dict],
    recent_pairs: set[frozenset],
) -> Optional[tuple[dict, float, list[str]]]:
    """
    Find the single best interest-based candidate for target.
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

    for size in range(size_min, size_max + 1):
        for combo in combinations(members, size):
            sets = [set(json.loads(m["interests"] or "[]")) for m in combo]
            shared = set.intersection(*sets)
            if not shared:
                continue
            avg_len = sum(len(s) for s in sets) / len(sets)
            score = len(shared) / avg_len * 100 if avg_len else 0
            if score > best_score:
                best_score = score
                best_group = list(combo)
                best_shared = sorted(shared)

    if not best_group:
        return None
    return best_group, best_shared


# ── DM sender ─────────────────────────────────────────────────────────────────

async def _send_match_dm(
    bot: commands.Bot,
    user_a: dict,
    user_b: dict,
    score: float,
    shared: list[str],
    pairing_id: int,
    match_mode: str = "interests",  # "interests" | "gender" | "random"
    guild: Optional[discord.Guild] = None,
) -> None:
    """
    DM both users an introduction embed.
    match_mode controls the description copy shown in the embed.
    Also sends first-match celebration and milestone DMs.

    guild is preferred for member resolution because guild.get_member()
    is always populated when Intents.members is enabled, while
    bot.get_user() only covers users the bot has seen in DMs or other
    cached guilds -- meaning the partner's DM could silently be dropped.
    """
    icebreaker = random.choice(ICEBREAKERS)

    if shared:
        shared_tags = " ".join(
            f"{INTEREST_EMOJIS.get(i, '⭐')} **{i}**" for i in shared
        )
        basis_line = f"🎯 **Shared Interests:** {shared_tags}"
    elif match_mode == "gender":
        basis_line = "💫 **Matched by:** Opposite vibes — get to know each other!"
    else:
        basis_line = "🌐 **Matched by:** Community discovery — say hello!"

    async def _resolve(uid: int) -> Optional[discord.User]:
        """Guild member cache -> bot cache -> API fetch (in that order)."""
        if guild:
            member = guild.get_member(uid)
            if member:
                return member
        cached = bot.get_user(uid)
        if cached:
            return cached
        try:
            return await bot.fetch_user(uid)
        except (discord.NotFound, discord.HTTPException):
            return None

    for primary, other in [(user_a, user_b), (user_b, user_a)]:
        discord_user = await _resolve(int(primary["user_id"]))
        if discord_user is None:
            log.warning(
                "Could not resolve Discord user %s -- DM skipped (pairing %d).",
                primary["user_id"], pairing_id,
            )
            continue

        other_discord = await _resolve(int(other["user_id"]))
        other_name = other_discord.display_name if other_discord else other["display_name"]
        other_bio = other["bio"] or "_No bio set yet._"

        score_display = f"`{score:.1f}%`" if match_mode == "interests" else "`✨ New Connection`"

        embed = _spark_embed(
            f"⚡ You've been Sparked with {other_name}!",
            f"**Compatibility:** {score_display}\n\n**About them:**\n> {other_bio}",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="🔗 Match Basis", value=basis_line, inline=False)
        embed.add_field(name="💬 Ice-Breaker", value=f"_{icebreaker}_", inline=False)
        embed.add_field(
            name="⭐ Rate Your Experience",
            value=f"After chatting, use `/spark rate` to rate this match!\n_(Pairing ID: {pairing_id})_",
            inline=False,
        )

        try:
            await discord_user.send(embed=embed)
            log.info("Sent match DM to user %s (pairing %d, mode=%s)", primary["user_id"], pairing_id, match_mode)
        except discord.Forbidden:
            log.warning("Cannot DM user %s — DMs disabled.", primary["user_id"])

        # First-match celebration
        if primary["total_matches"] == 0:
            try:
                await asyncio.sleep(0.3)
                celebrate = _spark_embed(
                    "🎉 First Spark Connection!",
                    "You just made your **first Spark connection**! "
                    "The community is better with you in it. Keep connecting! 🔥",
                    color=COLOR_SUCCESS,
                )
                await discord_user.send(embed=celebrate)
            except discord.Forbidden:
                pass

        # Milestone DMs
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

    # ── Core match resolver ───────────────────────────────────────────────────

    async def _resolve_match(
        self,
        target: dict,
        candidates: list[dict],
        guild: discord.Guild,
        recent_pairs: set[frozenset],
    ) -> Optional[tuple[dict, float, list[str], str]]:
        """
        Unified match resolver used by all match commands.

        Priority:
          1. If target has interests → interest-based best match
          2. Else → gender-based Male ↔ Female match
          3. If gender unknown or no opposite found → return None

        Returns (partner_dict, score, shared_interests, match_mode) or None.
        """
        # ── Path 1: interest-based ────────────────────────────────────────────
        if _has_interests(target):
            interest_candidates = [c for c in candidates if _has_interests(c)]
            result = _find_best_interest_match(target, interest_candidates, recent_pairs)
            if result:
                partner, score, shared = result
                return partner, score, shared, "interests"

        # ── Path 2: gender-based ──────────────────────────────────────────────
        guild_member = guild.get_member(int(target["user_id"]))
        if guild_member is None:
            return None

        target_gender = _detect_gender(guild_member)
        log.info(
            "Gender-based fallback for user %s → detected gender: %s",
            target["user_id"], target_gender,
        )

        result = _gender_find_best_match(target, target_gender, candidates, guild, recent_pairs)
        if result:
            partner, score, shared = result
            return partner, score, shared, "gender"

        return None

    # ── Auto-pairing job ──────────────────────────────────────────────────────

    async def _auto_pair_all_guilds(self) -> None:
        """Daily auto-pairing job: runs for every configured guild."""
        log.info("Auto-pairing job triggered.")
        for guild in self.bot.guilds:
            try:
                await self._auto_pair_guild(guild)
            except Exception as exc:
                log.exception("Auto-pairing failed for guild %s: %s", guild.id, exc)

    async def _auto_pair_guild(self, guild: discord.Guild) -> None:
        """
        Run the full pairing algorithm for a single guild.

        Strategy:
          - Members WITH interests → interest greedy pairing first
          - Remaining unmatched members (no interests) → gender greedy pairing
          - Still unmatched → consolation DM
        """
        config = await db.get_server_config(str(guild.id))
        if not config or not config.get("pairing_channel_id"):
            log.info("Guild %s has no pairing channel configured — skipping.", guild.id)
            return

        all_members = await db.get_all_opted_in_members(str(guild.id))
        if len(all_members) < 2:
            log.info("Guild %s has fewer than 2 opted-in members — skipping.", guild.id)
            return

        recent_pairs = await db.get_recent_pairs(str(guild.id), weeks=4)
        matched_ids: set[str] = set()
        matched_count = 0
        _paired_ids: list[tuple[str, str]] = []  # for channel summary

        # ── Phase 1: interest-based pairing ───────────────────────────────────
        interest_members = [m for m in all_members if _has_interests(m)]
        if len(interest_members) >= 2:
            pairs = _run_greedy_pairing(interest_members, recent_pairs)
            for m1, m2, score, shared in pairs:
                pairing_id = await db.log_pairing(str(guild.id), m1["user_id"], m2["user_id"], score)
                await _send_match_dm(self.bot, m1, m2, score, shared, pairing_id, match_mode="interests", guild=guild)
                await db.increment_total_matches(m1["user_id"])
                await db.increment_total_matches(m2["user_id"])
                matched_ids.add(m1["user_id"])
                matched_ids.add(m2["user_id"])
                _paired_ids.append((m1["user_id"], m2["user_id"]))
                matched_count += 1
                await asyncio.sleep(0.5)

        # ── Phase 2: gender-based pairing for unmatched members ───────────────
        unmatched = [m for m in all_members if m["user_id"] not in matched_ids]
        if len(unmatched) >= 2:
            males, females, unknowns = _split_by_gender(unmatched, guild)
            log.info(
                "Guild %s gender split: males=%d females=%d unknowns=%d",
                guild.id, len(males), len(females), len(unknowns),
            )
            gender_pairs = _gender_greedy_pairing(males, females, recent_pairs)
            for m1, m2, score, shared in gender_pairs:
                pairing_id = await db.log_pairing(str(guild.id), m1["user_id"], m2["user_id"], score)
                await _send_match_dm(self.bot, m1, m2, score, shared, pairing_id, match_mode="gender", guild=guild)
                await db.increment_total_matches(m1["user_id"])
                await db.increment_total_matches(m2["user_id"])
                matched_ids.add(m1["user_id"])
                matched_ids.add(m2["user_id"])
                _paired_ids.append((m1["user_id"], m2["user_id"]))
                matched_count += 1
                await asyncio.sleep(0.5)

        # ── Consolation DMs ───────────────────────────────────────────────────
        still_unmatched = [m for m in all_members if m["user_id"] not in matched_ids]
        for m in still_unmatched:
            discord_user = self.bot.get_user(int(m["user_id"]))
            if discord_user:
                try:
                    consolation = _spark_embed(
                        "😔 No Match Today",
                        "We couldn't find a fresh match for you today.\n"
                        "Try `/spark match` to find your person on demand, "
                        "or set your interests with `/spark interests`! 🔥",
                        color=COLOR_WARN,
                    )
                    await discord_user.send(embed=consolation)
                except discord.Forbidden:
                    pass

        # ── Summary in pairing channel ────────────────────────────────────────
        channel = guild.get_channel(int(config["pairing_channel_id"]))
        if channel and isinstance(channel, discord.TextChannel):
            pair_lines = "\n".join(
                f"<@{uid1}> × <@{uid2}>"
                for uid1, uid2 in _paired_ids
            )
            summary = _spark_embed(
                "⚡ Daily Spark Pairings!",
                f"Today **{matched_count * 2} members** were matched into **{matched_count} pairs**! 🎉\n\n"
                f"{pair_lines}\n\n"
                f"Check your DMs for your introduction.\n"
                f"Use `/spark match` to find more connections anytime!",
                color=COLOR_SUCCESS,
            )
            summary.add_field(
                name="💡 Tip",
                value="Set your interests with `/spark interests` for better matches! "
                      "Rate with `/spark rate` to build your streak! 🔥",
                inline=False,
            )
            await channel.send(embed=summary)

        log.info("Guild %s: auto-paired %d pairs.", guild.id, matched_count)

    # /spark match ─────────────────────────────────────────────────────────────

    @app_commands.command(name="match", description="Find your best match right now!")
    async def match(self, interaction: discord.Interaction) -> None:
        """
        On-demand matching. Priority:
          1. Interest-based if both users have interests.
          2. Gender-based (Male ↔ Female) if no interests.
        24-hour cooldown per user.
        """
        await interaction.response.defer(ephemeral=True)
        try:
            user = interaction.user
            guild = interaction.guild
            await db.upsert_member(str(user.id), str(guild.id), user.display_name)

            # Cooldown check
            last_match = _match_cooldowns.get(str(user.id))
            if last_match:
                delta = datetime.now(timezone.utc) - last_match
                if delta < timedelta(hours=MATCH_COOLDOWN_HOURS):
                    remaining = timedelta(hours=MATCH_COOLDOWN_HOURS) - delta
                    hrs, rem = divmod(int(remaining.total_seconds()), 3600)
                    mins = rem // 60
                    await interaction.followup.send(
                        embed=_spark_embed(
                            "⏳ Slow Down, Spark!",
                            f"You already sparked a match recently.\n"
                            f"Next match available in **{hrs}h {mins}m**.",
                            color=COLOR_WARN,
                        ),
                        ephemeral=True,
                    )
                    return

            # Setup check
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

            target = await db.get_member(str(user.id))
            candidates = await db.get_all_opted_in_members(str(guild.id))
            recent_pairs = await db.get_recent_pairs(str(guild.id), weeks=4)

            result = await self._resolve_match(target, candidates, guild, recent_pairs)

            if not result:
                # Explain why no match was found
                guild_member = guild.get_member(user.id)
                gender = _detect_gender(guild_member) if guild_member else "unknown"

                if not _has_interests(target) and gender == "unknown":
                    msg = (
                        "We couldn't detect your gender from your roles or profile, "
                        "and you haven't set interests yet.\n\n"
                        "👉 Add interests with `/spark interests`\n"
                        "👉 Or add a gender role in the server so we can match you!"
                    )
                elif not _has_interests(target):
                    msg = (
                        "No opposite-gender members are available right now.\n\n"
                        "👉 Set interests with `/spark interests` for broader matching!"
                    )
                else:
                    msg = (
                        "No fresh matches available right now.\n"
                        "Try again later or encourage more members to join!"
                    )

                await interaction.followup.send(
                    embed=_spark_embed("😔 No Match Found", msg, color=COLOR_WARN),
                    ephemeral=True,
                )
                return

            partner, score, shared, match_mode = result
            pairing_id = await db.log_pairing(str(guild.id), str(user.id), partner["user_id"], score)
            await db.increment_total_matches(str(user.id))
            await db.increment_total_matches(partner["user_id"])
            _match_cooldowns[str(user.id)] = datetime.now(timezone.utc)

            await _send_match_dm(self.bot, target, partner, score, shared, pairing_id, match_mode, guild=guild)

            partner_discord = self.bot.get_user(int(partner["user_id"]))
            partner_name = partner_discord.display_name if partner_discord else partner["display_name"]
            score_str = f"{score:.1f}%" if match_mode == "interests" else "✨ New Connection"

            confirm = _spark_embed(
                "⚡ Match Found!",
                f"We found you a **{score_str}** match with **{partner_name}**!\n"
                f"Check your DMs for the introduction. 🎉",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=confirm, ephemeral=True)

            # Announcement in the pairing channel — show who was matched
            if config.get("pairing_channel_id"):
                ch = guild.get_channel(int(config["pairing_channel_id"]))
                if ch and isinstance(ch, discord.TextChannel):
                    try:
                        requester_mention = user.mention
                        partner_mention = (
                            f"<@{partner['user_id']}>"
                        )
                        if shared:
                            shared_tags = " ".join(
                                f"{INTEREST_EMOJIS.get(i, '⭐')} **{i}**" for i in shared
                            )
                            basis = f"They share: {shared_tags}"
                        elif match_mode == "gender":
                            basis = "Matched by opposite vibes 💫"
                        else:
                            basis = "Community discovery 🌐"

                        score_str_ch = f"`{score:.1f}%`" if match_mode == "interests" else "`✨ New Connection`"
                        await ch.send(embed=_spark_embed(
                            "⚡ A New Spark Connection!",
                            f"{requester_mention} and {partner_mention} just matched! ({score_str_ch})\n"
                            f"{basis}\n\n"
                            f"Check your DMs for the introduction. Use `/spark match` to find your person! 🔥",
                            color=COLOR_INFO,
                        ))
                    except discord.Forbidden:
                        pass

            log.info(
                "On-demand match: %s <-> %s (score=%.1f, mode=%s, pairing=%d)",
                user.id, partner["user_id"], score, match_mode, pairing_id,
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
        Falls back to random gender-mixed group if no interests exist.
        Creates a temporary private channel that auto-deletes after 72 hours.
        """
        await interaction.response.defer(ephemeral=False)
        try:
            guild = interaction.guild
            user = interaction.user
            await db.upsert_member(str(user.id), str(guild.id), user.display_name)

            config = await db.get_server_config(str(guild.id))
            if not config:
                await interaction.followup.send(
                    embed=_spark_embed("⚙️ Setup Required", "Ask an admin to run `/spark setup` first!", color=COLOR_WARN),
                    ephemeral=True,
                )
                return

            all_members = await db.get_all_opted_in_members(str(guild.id))
            if len(all_members) < 3:
                await interaction.followup.send(
                    embed=_spark_embed(
                        "😔 Not Enough Members",
                        "Need at least **3 opted-in members** to form a group.",
                        color=COLOR_WARN,
                    ),
                    ephemeral=True,
                )
                return

            # Try interest-based group first
            interest_members = [m for m in all_members if _has_interests(m)]
            group_result = None
            group_mode = "interests"

            if len(interest_members) >= 3:
                group_result = _find_best_group(interest_members, size_min=3, size_max=5)

            # Fallback: random selection from all members
            if not group_result:
                group_mode = "random"
                size = min(5, len(all_members))
                random_group = random.sample(all_members, size)
                group_result = (random_group, [])

            group_members, shared_interests = group_result

            # Create private channel
            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
            }
            discord_members = []
            for m in group_members:
                du = guild.get_member(int(m["user_id"]))
                if du:
                    overwrites[du] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    discord_members.append(du)

            shared_label = "-".join(shared_interests[:2]).lower().replace(" ", "") if shared_interests else "spark"
            channel_name = f"spark-group-{shared_label}"

            try:
                private_channel = await guild.create_text_channel(
                    name=channel_name,
                    overwrites=overwrites,
                    reason="Spark group channel (auto-deletes in 72h)",
                    topic=f"Spark group | Auto-deletes in 72 hours",
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=_spark_embed("🔒 Missing Permissions", "I need **Manage Channels** permission.", color=COLOR_ERROR),
                    ephemeral=True,
                )
                return

            mentions = " ".join(m.mention for m in discord_members)
            icebreaker = random.choice(ICEBREAKERS)

            if shared_interests:
                basis = " ".join(f"{INTEREST_EMOJIS.get(i, '⭐')} **{i}**" for i in shared_interests)
                desc = f"You've been grouped because you all share: {basis}"
            else:
                desc = "You've been brought together to discover new connections! 🌐"

            welcome = _spark_embed(
                f"⚡ Welcome to {channel_name}!",
                f"{desc}\n\n**Ice-Breaker:** _{icebreaker}_\n\n"
                f"⏰ This channel **auto-deletes in 72 hours** — make it count!",
                color=COLOR_SUCCESS,
            )
            await private_channel.send(content=mentions, embed=welcome)

            member_ids = [m["user_id"] for m in group_members]
            await db.log_group(str(guild.id), member_ids, shared_interests)

            if config.get("pairing_channel_id"):
                announce_ch = guild.get_channel(int(config["pairing_channel_id"]))
                if announce_ch and isinstance(announce_ch, discord.TextChannel):
                    await announce_ch.send(embed=_spark_embed(
                        "👥 New Spark Group Created!",
                        f"A group of **{len(group_members)} members** just connected!\n"
                        f"Use `/spark group` to start your own!",
                        color=COLOR_INFO,
                    ))

            await interaction.followup.send(
                embed=_spark_embed(
                    "✅ Group Created!",
                    f"Your group channel {private_channel.mention} is ready!\nIt auto-deletes in **72 hours**.",
                    color=COLOR_SUCCESS,
                ),
                ephemeral=True,
            )

            asyncio.create_task(self._delete_channel_after(private_channel, hours=72))
            log.info("Created group channel %s (mode=%s) for guild %s", channel_name, group_mode, guild.id)

        except Exception as exc:
            log.exception("Error in /spark group for user %s: %s", interaction.user.id, exc)
            await interaction.followup.send(
                embed=_spark_embed("⚠️ Error", "Something sparked out — try again!", color=COLOR_ERROR),
                ephemeral=True,
            )

    async def _delete_channel_after(self, channel: discord.TextChannel, hours: int = 72) -> None:
        """Wait then delete the temporary group channel."""
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
        """Rate the most recent pairing. Updates streak if ≥ 4 stars."""
        await interaction.response.defer(ephemeral=True)
        try:
            if stars < 1 or stars > 5:
                await interaction.followup.send(
                    embed=_spark_embed("⚠️ Invalid Rating", "Please rate between **1** and **5** stars.", color=COLOR_WARN),
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
                    embed=_spark_embed("⚠️ Already Rated", "You've already rated this pairing.", color=COLOR_WARN),
                    ephemeral=True,
                )
                return

            if stars >= 4:
                await db.update_streak(str(user.id), increment=True)
                streak_msg = "⬆️ Your streak grew! Keep connecting!"
            else:
                streak_msg = "💡 Rate 4+ stars to build your streak!"

            star_display = "⭐" * stars + "☆" * (5 - stars)
            await interaction.followup.send(
                embed=_spark_embed(
                    "✨ Rating Submitted!",
                    f"You rated your match: **{star_display}**\n\n{streak_msg}",
                    color=COLOR_SUCCESS,
                ),
                ephemeral=True,
            )
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
