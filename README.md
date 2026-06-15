# ⚡ Spark Bot

**Social Matchmaking Discord Bot** — Connect server members who share interests so they actually talk to each other.

Spark uses AI-powered interest matching to create meaningful connections between Discord members. Every interaction feels rewarding with streaks, leaderboards, and monthly milestone celebrations.

---

## 🎯 Features

✨ **Profile System**
- Custom interests (up to 6 from 18 categories)
- Bio profiles (max 150 chars)
- Match history and statistics

🎯 **Matching Engine**
- On-demand matching with `/spark match`
- Weekly auto-pairing (configurable day/time)
- 28-day cooldown to prevent repeat pairs
- Interest-based compatibility scoring

👥 **Group Creation**
- Create 3-5 person groups with shared interests
- Auto-delete channels after 72 hours
- Perfect for organized conversations

📊 **Engagement Mechanics**
- Streak system (1-5 star ratings)
- Leaderboard (top 10 connected members)
- Monthly milestone celebrations (5, 10, 25+ matches)
- Server-wide statistics

⏰ **Automation**
- Daily auto-pairing via APScheduler
- Consolation messages for unmatched members
- Weekly summary announcements

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Discord Server (admin access)
- Discord Developer Account

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and name it "Spark"
3. Go to "Bot" → "Add Bot"
4. Under TOKEN, click "Copy" (save this!)
5. Enable these **Intents**:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
   - ✅ Guilds
   - ✅ Direct Messages

6. Go to "OAuth2" → "URL Generator"
7. Select scopes: `bot`
8. Select permissions:
   - ✅ Send Messages
   - ✅ Embed Links
   - ✅ Read Message History
   - ✅ Mention @everyone
   - ✅ Manage Channels
   - ✅ Create Private Channels
   - ✅ Delete Channels
9. Copy the generated URL and open it to invite bot to your server

### 2. Deploy to Replit (Recommended for Free Hosting)

1. **Fork this Replit** (or create new Python project)
2. **Upload files** to your Replit:
   - `main.py`
   - `keep_alive.py`
   - `database.py`
   - `requirements.txt`
   - `.env.example`
   - `cogs/` folder (all 4 cog files)

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Add Discord Token**:
   - Go to Replit "Secrets" (lock icon)
   - Add key: `DISCORD_TOKEN`
   - Add value: (paste your bot token)

5. **Run the bot**:
   ```bash
   python main.py
   ```

You should see:
```
⚡ Spark Bot is online as Spark#1234
```

### 3. Set Up UptimeRobot (Keep Bot Alive)

Free Replit tier will put bots to sleep after 1 hour. Use UptimeRobot to keep it alive:

1. Go to [UptimeRobot](https://uptimerobot.com/)
2. Sign up for free account
3. Click "Add Monitor"
4. Select "HTTP(s)"
5. **Monitor Name**: `Spark Bot`
6. **URL**: `https://your-replit-url.repl.co/ping`
7. **Monitoring Interval**: 5 minutes
8. Click "Create Monitor"

Your bot will now stay online 24/7!

### 4. Configure Spark in Your Server

1. In Discord, run: `/spark setup [channel] [role]`
   - **[channel]**: Pick the announcement channel (e.g., #announcements)
   - **[role]**: Pick an admin role (e.g., @Moderators)

2. Bot confirms with setup embed

✅ Spark is now ready!

---

## 📋 All Commands

### Profile Commands

**`/spark profile`**
- View your profile card with interests, bio, matches, and streak

**`/spark interests`**
- Select up to 6 interests from 18 categories
- Options: Gaming, Anime, Music, Art, Coding, Movies, Books, Fitness, Cooking, Photography, Travel, Science, Sports, Fashion, Finance, Pets, Writing, Design

**`/spark bio [text]`**
- Set a short bio (max 150 characters)
- Shows on your profile

**`/spark opt [in/out]`**
- Opt in/out of weekly auto-pairing
- You can still use `/spark match` manually

### Matching Commands

**`/spark match`**
- Find your next connection right now
- DMs both users introduction with shared interests
- Ice-breaker question to start conversation
- 24-hour cooldown per user per server

**`/spark group`**
- Create a 3-5 person group with highest interest overlap
- Auto-creates private Discord channel
- Channel auto-deletes after 72 hours

**`/spark history`**
- View your last 5 pairings
- Shows match scores and dates

**`/spark rate [1-5]`**
- Rate your last match 1-5 stars
- Ratings 4+ increase your streak 🔥
- Track pairing satisfaction

### Social Commands

**`/spark leaderboard`**
- Top 10 most-connected members
- Shows total matches and current streak
- 🥇🥈🥉 medals for top 3

**`/spark stats`**
- Server-wide statistics:
  - Total registered members
  - Total pairings made
  - Average match score
  - Most popular interest

**`/spark help`**
- Show all commands with descriptions
- Getting started guide

### Admin Commands

**`/spark setup [channel] [role]`** *(admin only)*
- Configure announcement channel
- Set admin role
- Schedule weekly pairing (default: Monday 9 AM GMT+5:30)

---

## 🎯 How Matching Works

### Interest Matching Algorithm

```
Match Score = (Shared Interests / Max Possible) × 100
```

**Example:**
- User A: Gaming, Anime, Music
- User B: Gaming, Anime, Design

Shared: 2 (Gaming, Anime)
Max Possible: 3
**Score: (2/3) × 100 = 66.7%**

### Daily Auto-Pairing

Every Monday at 9:00 AM (configurable):
1. Fetches 100 most active members (opt-in only)
2. Runs greedy pairing algorithm
3. Skips pairs matched in last 28 days
4. DMs each pair with intro, shared interests, ice-breaker
5. Posts summary in announcement channel
6. Sends consolation messages to unmatched members

### On-Demand Matching

Use `/spark match` anytime to:
- Get instant match with best compatibility
- 24-hour cooldown (prevents spam)
- Logs to pairing history

---

## 🎮 Engagement Features

### Streak System 🔥
- Rate matches 4+ stars to maintain streak
- Streak resets on rating < 4 stars
- Shows on `/spark leaderboard`

### Milestones
Automatic celebrations when you hit:
- 5 matches 🎉
- 10 matches 🏆
- 25 matches ⭐

### First-Match Celebration
New users get special DM after their first pairing

### Weekly Summary
Bot announces in pairing channel:
- How many matches were made
- How many members remain unmatched

---

## 🗄️ Database Schema

**SQLite Database** (`spark.db`)

**members**
- `user_id` - Discord ID
- `guild_id` - Server ID
- `display_name` - Username
- `interests` - JSON array of interests
- `bio` - Short description
- `opt_in` - Participation status
- `joined_at` - Registration date
- `total_matches` - Lifetime connections
- `streak` - Current 🔥 streak

**pairings**
- `id` - Unique pairing ID
- `guild_id` - Server ID
- `user1_id`, `user2_id` - Connected users
- `paired_at` - Timestamp
- `match_score` - Compatibility %
- `user1_rated`, `user2_rated` - Star ratings

**groups**
- `id` - Group ID
- `guild_id` - Server ID
- `member_ids` - JSON array of 3-5 users
- `interests` - Shared interests
- `created_at` - Timestamp

**server_config**
- `guild_id` - Server ID
- `pairing_channel_id` - Announcement channel
- `pairing_day` - Day for auto-pairing
- `pairing_hour` - Hour for auto-pairing
- `admin_role_id` - Required role

---

## 🛠️ Development

### Local Setup

1. Clone repo
2. Create `.env`:
   ```
   DISCORD_TOKEN=your_token_here
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run locally:
   ```bash
   python main.py
   ```

### File Structure

```
spark-bot/
├── main.py              # Bot entry point
├── keep_alive.py        # Flask server (Replit)
├── database.py          # Async SQLite wrapper
├── requirements.txt     # Dependencies
├── .env.example         # Environment template
├── README.md            # This file
└── cogs/
    ├── profile.py       # Profile management
    ├── matching.py      # Matching engine
    ├── social.py        # Leaderboard & stats
    └── admin.py         # Setup & scheduler
```

### Adding New Interests

Edit interest list in `cogs/profile.py`:
```python
INTERESTS = [
    "Gaming", "Anime", "Music", "Art", ...
]
```

### Customizing Pairing Schedule

Edit in `cogs/admin.py` or use future admin command:
```python
pairing_day = 'friday'    # 'monday', 'tuesday', etc.
pairing_hour = 17         # 0-23 (24-hour format)
```

---

## 🐛 Troubleshooting

**Bot not responding?**
- Check Discord token is correct in Secrets
- Verify bot has "Send Messages" permission
- Try restarting bot in Replit

**`/spark match` says "not enough members"?**
- Need at least 2 members with interests set
- Both must have `/spark interests` filled

**Pairing channel missing?**
- Run `/spark setup` again
- Verify bot has "Send Messages" in that channel

**UptimeRobot not working?**
- Copy exact Replit URL from browser (with .repl.co)
- Check URL ends with `/ping`
- Verify monitor is "Up" in UptimeRobot dashboard

---

## 📊 Stats & Metrics

Track these via `/spark stats`:
- 👥 Total members registered
- 🔗 Total pairings made
- 💡 Average match score
- 🎮 Most popular interest

---

## 🔐 Permissions Required

Spark requires these Discord permissions:
- Send Messages
- Embed Links
- Read Message History
- Manage Channels (for group creation/deletion)
- Create Private Channels
- Delete Channels

Grant via OAuth2 URL Generator when inviting.

---

## 📝 License

Spark Bot is open source. Use freely in your Discord servers!

---

## 🙌 Support

For issues or feature requests, open an issue or reach out!

**Made with ⚡ by Spark Team**

---

## 🚀 Future Features

- [ ] Custom interest categories per server
- [ ] Match feedback (why were we paired?)
- [ ] Interest discovery recommendations
- [ ] Pairing notifications (ping notifications)
- [ ] Web dashboard
- [ ] Demographic matching options
- [ ] Activity-based matching improvements

---

Enjoy connecting your Discord community! ⚡
