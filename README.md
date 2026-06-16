# ⚡ Spark Bot 2.1

> **Social matchmaking for Discord servers** — connecting members who share interests so they actually talk to each other.

Spark uses interest-based matchmaking, automated daily pairings, streaks, leaderboards, and private group channels to make your Discord server feel alive and magnetic.

---

## ✨ Features

- 🎯 **Smart Matching** — Interest overlap scoring (shared / max) × 100
- 🤝 **Daily Auto-Pairings** — Runs every day at 9 AM IST, no repeats within 4 weeks
- 👥 **Group Channels** — Temporary private channels for 3-5 members, auto-deleted after 72 hours
- 🔥 **Streak System** — Rate matches 4+ stars to build your streak, shown on the leaderboard
- 🏆 **Leaderboard** — Top 10 most-connected members
- 🎉 **Milestones** — Special DMs at 5, 10, and 25 matches
- 💬 **Ice-Breaker Questions** — Randomly selected prompts to start the conversation
- 📊 **Server Stats** — Trending interests, total pairings, average match score

---

## Matching (How it works)
- Interest-based — if both users have interests set, scored by overlap percentage
Gender-based — if no interests, pairs Male ↔ Female detected from roles, nickname, and global name

**Gender detection scans 600+ keywords** across roles (double weighted), display names, and Discord bios — covering pronouns, titles, slang, anime archetypes, mythology, emoji symbols, and more.

## Daily auto-pair 
- runs every day at 9:00 AM IST; consolation DM sent to anyone unmatched

## Match announcements
- When /spark match runs, the configured channel receives an embed that @mentions both matched users by name, shows the compatibility score or match mode, and lists any shared interests. The daily auto-pair summary lists every pair as @User1 × @User2 so the whole server can see who connected.

## DM delivery
- DMs are sent to both the requester and their partner. User resolution uses the guild member cache first (always populated with Intents.all()), falling back to the bot's user cache and finally an API fetch — so partner DMs are never silently dropped.

---

## Member registration
- On startup (on_ready), Spark loops through every guild via fetch_members(limit=None) and upserts all non-bot members into spark.db. This means the full member pool is available for gender-based matching immediately after a restart — no one needs to run a command first.
New members are registered automatically the moment they join via on_member_join.

---

## 🚀 Setup

### 1. Create a Discord Application & Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → name it `Spark`
3. Go to **Bot** tab → click **Add Bot**
4. Under **Token**, click **Reset Token** and copy it → paste into Replit Secrets
5. Under **Privileged Gateway Intents**, enable:
   - **Presence Intent**
   - **Server Members Intent**
   - **Message Content Intent**
6. Click **Save Changes**

### 2. Invite the Bot to Your Server

Use this URL (replace `YOUR_CLIENT_ID` with your application's Client ID from the **General Information** tab):

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=8&scope=bot%20applications.commands
```

**Required permissions:**
- Send Messages
- Embed Links
- Read Message History
- Manage Channels (for `/spark group` private channels)
- Use Slash Commands
- Add Reactions

> Using `permissions=8` (Administrator) is the easiest during setup. Tighten permissions in production.

### 3. 🛠 Local Development

```bash
# Clone the project
git clone https://github.com/DMONINK/Spark-Discord-Bot.git
cd spark-bot  # Now navigate into the cloned folder

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in your token
cp .env.example .env
# Edit .env and add your DISCORD_TOKEN

# Run the bot
python main.py
```

Slash commands may take up to **1 hour** to propagate globally. For instant sync during development, use guild-specific sync (see advanced config below).

---

## ⏰ Configuring the Pairing Schedule

Daily auto-pairings run at **9:00 AM IST (GMT+5:30)** by default.

To change the schedule, edit `cogs/matching.py`:

```python
self.scheduler.add_job(
    self._auto_pair_all_guilds,
    CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),  # ← Edit here
    id="daily_auto_pair",
    replace_existing=True,
)
```

Valid timezone strings follow [IANA tz database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) format (e.g. `America/New_York`, `Europe/London`, `UTC`).

---

## ⚙️ First-Time Server Configuration

After inviting the bot, an admin must run:

```
/spark setup channel:#your-pairing-channel admin_role:@YourAdminRole
```

This stores the announcement channel and admin role. A welcome message is posted in the channel.

---

## 📋 All Slash Commands

### 👤 Profile

| Command | Description |
|---------|-------------|
| `/spark profile` | View your Spark profile card |
| `/spark interests` | Set your interests (pick up to 6 from 18 categories) |
| `/spark bio [text]` | Set a short bio (max 150 chars) |
| `/spark opt [in/out]` | Toggle weekly pairing participation |
| `/spark history` | View your last 5 pairings with dates and scores |

### 🤝 Matching

| Command | Description |
|---------|-------------|
| `/spark match` | Find your best match right now (24-hour cooldown) |
| `/spark group` | Create a group of 3-5 members with shared interests |
| `/spark rate [1-5]` | Rate your latest match experience (4+ builds your streak) |

### 📊 Social

| Command | Description |
|---------|-------------|
| `/spark leaderboard` | Top 10 most-connected members with streaks |
| `/spark stats` | Server-wide stats: members, pairings, trending interests |
| `/spark help` | Full command reference |

### ⚙️ Admin

| Command | Description |
|---------|-------------|
| `/spark setup [channel] [admin_role]` | Configure the bot (requires Administrator) |
| `/spark admin_stats` | Detailed admin view with full interest breakdown |
| `/spark force_pair` | Manually trigger the auto-pairing job right now |

---

## 🎯 Interest Categories

Users pick up to 6 from these 18 categories:

Gaming · Anime · Music · Art · Coding · Movies · Books · Fitness · Cooking · Photography · Travel · Science · Sports · Fashion · Finance · Pets · Writing · Design

---

## 🔥 Streak System

- Rate a match **4 or 5 stars** → streak increments by 1
- Rate **1-3 stars** → streak resets to 0
- Streak is shown on your profile (`🔥 × N`) and the leaderboard
- Consecutive high-rated weeks = longer streak

---

## 🏗 Project Structure

```
spark-bot/
├── main.py          ← Entry point; bot class, startup, cog loading
├── keep_alive.py    ← Flask server for Replit/UptimeRobot
├── database.py      ← All async SQLite helpers (aiosqlite)
├── requirements.txt ← Pinned dependencies
├── .env.example     ← Environment variable template
├── spark.db         ← Created automatically on first run
└── cogs/
    ├── profile.py   ← /profile, /interests, /bio, /opt, /history
    ├── matching.py  ← /match, /group, /rate + APScheduler job
    ├── social.py    ← /leaderboard, /stats, /help
    └── admin.py     ← /setup, /admin_stats, /force_pair
```

---

## 📄 License

MIT — use freely, attribution appreciated.

---

