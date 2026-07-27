# Bandcamp Parser Bot

A bot for automatic monitoring of new music releases on Bandcamp by
specified tags, sending notifications to Telegram, and managing itself via
Telegram commands.

## Features

- 🔍 **Release discovery** via Bandcamp's own internal discover API — no
  browser automation, no headless Chrome. Tags are matched directly against
  Bandcamp's real tag data, so a release is found regardless of its primary
  genre (e.g. a release tagged "hardcore punk" but filed under "Rock" is
  still caught)
- 🚫 **Tag blacklist** — exclude unwanted genres, checked against a release's
  real tags so it's caught even if found under an unrelated main tag
- 📅 **Release age filter** — skips releases older than a configurable
  number of days instead of sending them as if they just dropped
- 📱 **Telegram notifications** with release info and link
- 🛠️ **Telegram admin commands** — change tags, blacklist, and schedule
  without touching the server
- ⏰ **Flexible scheduling** with jitter — configurable run times plus a
  random delay so runs aren't perfectly predictable
- 🗄️ **SQLite database** for tracking sent releases, with both age-based and
  disk-usage-based cleanup
- 🔄 **Automatic retries** on network failures

## Important: First Run

⚠️ **On the first run**, the bot will add to the database and send to
Telegram **all releases** currently returned for the selected tags. This can
be many messages!

**On subsequent runs**, the bot will only send **new releases** that are not
yet in the database.

### Recommendations for first run:

1. Start with a small number of tags (2-3)
2. After the first run, you can add more tags

## Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

No browser or driver installation needed - the bot talks to Bandcamp over
plain HTTP.

### 2. Create Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` and follow instructions
3. Copy the bot token
4. Get your Chat ID via [@userinfobot](https://t.me/userinfobot)

### 3. Configure .env

Copy the example file and fill in your own values:

```bash
cp .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 4. Configure config.yaml

```yaml
# Schedule (every hour from 08:00 to 00:00 UTC)
schedule:
  times:
    - "08:00"
    - "09:00"
    # ... etc.
  timezone: "UTC"
  jitter_minutes: 8   # random delay added after each run time

# Tags to monitor
tags:
  - "punk"
  - "hardcore"

# Blacklist (releases added to DB but NOT sent)
blacklist_tags:
  - "pop"
  - "electronic"

# Skip releases older than this many days (0 = no limit)
max_release_age_days: 30

# Parser settings
parser:
  request_delay: 1.5         # Delay between requests (sec)
```

### 5. Run

**Continuous scheduled operation:**
```bash
python run.py
```

**One-time run:**
```bash
python run_once.py
```

**Or with Docker** (see [SERVER_REQUIREMENTS.md](SERVER_REQUIREMENTS.md) for
full server setup):
```bash
docker compose up -d --build
```

## Configuration

### Schedule (`schedule`)

| Parameter | Description | Example |
|-----------|-------------|---------|
| `times` | List of run times (HH:MM) | `["08:00", "12:00", "18:00"]` |
| `timezone` | Timezone | `"UTC"` |
| `jitter_minutes` | Random delay (0..N min) added after each run time | `8` |

### Tags (`tags`)

List of Bandcamp tags to monitor:

```yaml
tags:
  - "punk"
  - "hardcore punk"
  - "d-beat"
  - "crust punk"
```

Any tag works here - a Bandcamp top-level genre (`punk`, `metal`,
`electronic`, ...), an official subgenre (`hardcore-punk`, `crust-punk`,
...), or an informal community tag (`d-beat`, `raw-punk`, `uk82`, ...).
Releases are matched against the tag directly, regardless of what genre
Bandcamp filed them under, so a release tagged `"hardcore punk"` but filed
under `"Rock"` is still found.

### Blacklist (`blacklist_tags`)

Tags whose releases should be excluded:

```yaml
blacklist_tags:
  - "happy hardcore"
  - "electronic"
  - "techno"
```

**How it works:**
1. Blacklist tags are parsed first
2. Found releases are added to DB (but not sent)
3. Then main tags are parsed
4. Releases already found in blacklist are skipped
5. A release newly found under a main tag is also checked against its own
   real tag list (see "Fetch real tags" below) - this catches a release
   that genuinely carries a blacklisted tag even if that tag's own search
   never surfaced it (e.g. buried deep in a high-volume feed)

### Release age filter (`max_release_age_days`)

```yaml
max_release_age_days: 30
```

Bandcamp's "new" feed isn't strictly chronological and occasionally
surfaces older catalog items alongside genuinely new ones. A release older
than this many days is still added to the database (so it isn't re-checked
every run) but is not sent to Telegram. Set to `0` to disable - a release's
own future-dated preorder date is never affected by this, only releases
older than the cutoff are held back.

### Parser (`parser`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `request_delay` | Delay between requests (sec) | `1.5` |

### Database (`database`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `db_path` | Path to DB file | `bandcamp_releases.db` |
| `cleanup_days` | Delete records older than N days (`0` = disabled) | `90` |
| `disk_usage_threshold_percent` | Once disk usage hits this %, delete the oldest records regardless of age (`0` = disabled) | `85` |
| `disk_usage_target_percent` | Keep deleting oldest records until usage drops back to this % | `75` |

## Telegram Admin Commands

The bot listens for commands in your own Telegram chat (the one matching
`TELEGRAM_CHAT_ID`) so you can reconfigure it without SSH access. Messages
from any other chat are silently ignored.

| Command | Effect | Restart required? |
|---------|--------|--------------------|
| `/help` | List available commands | — |
| `/tags` | Show current tags | — |
| `/tags_add <tag>` | Add a tag | No — applies next run |
| `/tags_remove <tag>` | Remove a tag | No — applies next run |
| `/blacklist` | Show blacklist | — |
| `/blacklist_add <tag>` | Add to blacklist | No — applies next run |
| `/blacklist_remove <tag>` | Remove from blacklist | No — applies next run |
| `/schedule` | Show current schedule | — |
| `/schedule_set 07:00,10:00,...` | Replace the run times | Yes — bot restarts itself |
| `/schedule_jitter <minutes>` | Set the jitter window | Yes — bot restarts itself |
| `/status` | DB stats, disk usage, last successful run | — |

Changes that need a restart are written to disk first, then the bot restarts
itself (a few seconds under systemd's `Restart=always`) and comes back up
with the new settings applied. Tag/blacklist edits don't need a restart at
all - they're picked up automatically before the next scheduled run.

Admin edits are stored in a separate `config.overrides.yaml` file (created
automatically on first edit, not checked into version control) layered on
top of `config.yaml`, so your original config file is never rewritten or
loses its comments.

## Project Structure

```
.
├── src/
│   ├── __init__.py        # Module exports
│   ├── config.py          # Configuration (dataclasses + overrides layer)
│   ├── database.py        # SQLite operations + cleanup
│   ├── parser.py          # Bandcamp discover-API client (tag-based search)
│   ├── telegram_bot.py    # Telegram notification sending
│   ├── admin_bot.py       # Telegram admin command handling
│   ├── scheduler.py       # Scheduler (APScheduler)
│   └── main.py            # Main BandcampBot class
├── config.yaml             # Settings
├── config.overrides.yaml   # Bot-writable overrides (created automatically, gitignored)
├── .env                    # Secrets (tokens) - copy from .env.example
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image (installs requirements.txt)
├── docker-compose.yml      # Bind-mounts the project dir, runs `python run.py`
├── run.py                  # Run with schedule
├── run_once.py             # One-time run
└── bandcamp_releases.db    # Database (created automatically)
```

## How It Works

1. **Fetch releases** — for each tag, the bot calls Bandcamp's internal
   discover API filtered directly by that tag, across all genres
2. **Combine pages** — the freshest page is always included, plus one
   supplemental page that advances on each call, for broader coverage of a
   tag's back catalog without ever missing newly published releases
3. **Check DB** — skip releases already in the database
4. **Check release age** — a release older than `max_release_age_days` is
   recorded in the DB and skipped here, without fetching its real tags
5. **Fetch real tags** — the new release's own page is fetched to pull its
   full, real tag list for storage and the Telegram message
6. **Check blacklist** — skip (but still record) a release whose real tags
   match a blacklisted tag
7. **Send to Telegram** — formatted message (artist, title, tags, release
   date, location, link, preorder status)
8. **Save to DB** — before attempting to send, so a failed send is retried
   later instead of being lost

## Logging

Logs are written to:
- `bandcamp_bot.log` — rotated daily, 4 weeks retained
- Console — real-time

Format:
```
2026-07-18 12:00:00 - src.parser - INFO - Fetched 48 releases for tag 'punk' via Bandcamp API
2026-07-18 12:00:01 - src.telegram_bot - INFO - Sent: Album Name by Artist
```

## Troubleshooting

### Bot not sending messages

- Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Make sure the bot is added to the chat with send permissions

### A tag returns no releases

- Check tag spelling against the Bandcamp website - an unrecognized tag
  just comes back with zero results, not an error
- Check logs for errors (a failed request logs a warning)

### Tasks not running on schedule

- Check `timezone` in `config.yaml` (or via `/schedule`)
- Time format: `"HH:MM"` (24-hour)
- Make sure the application is running

### Admin commands not responding

- Confirm you're messaging from the same chat as `TELEGRAM_CHAT_ID` -
  commands from any other chat are silently ignored
- Check the logs for `AdminBot` startup errors

## Server Deployment

### systemd (Linux)

A ready-to-use unit file is included at `bandcamp-bot.service` - adjust
`WorkingDirectory`/paths and copy it to
`/etc/systemd/system/bandcamp-bot.service`:

```ini
[Unit]
Description=Bandcamp Parser Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/bandcamp-bot
Environment=PATH=/opt/bandcamp-bot/venv/bin
ExecStart=/opt/bandcamp-bot/venv/bin/python run.py
Restart=always
RestartSec=10
TimeoutStopSec=180

[Install]
WantedBy=multi-user.target
```

Commands:
```bash
sudo systemctl enable bandcamp-bot
sudo systemctl start bandcamp-bot
sudo systemctl status bandcamp-bot
```

## Additional Documentation

- [SETUP.md](SETUP.md) — Quick setup
- [WINDOWS_SETUP.md](WINDOWS_SETUP.md) — Windows installation
- [SERVER_REQUIREMENTS.md](SERVER_REQUIREMENTS.md) — Server requirements

## Technologies

- **Python 3.9+**
- **requests** — HTTP client for Bandcamp's discover API
- **python-telegram-bot** — Telegram messaging and admin commands
- **APScheduler** — task scheduler
- **SQLite** — database

## License

MIT
