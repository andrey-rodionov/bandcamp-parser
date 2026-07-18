# Quick Setup

## Requirements

- Python 3.9+

No browser or driver installation needed - the bot talks to Bandcamp over
plain HTTP.

## Installation in 5 Minutes

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create Telegram Bot

1. Open [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Copy bot token
4. Get Chat ID via [@userinfobot](https://t.me/userinfobot)

### 3. Create .env

```bash
cp .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

### 4. Configure config.yaml

```yaml
schedule:
  times:
    - "08:00"
    - "12:00"
    - "18:00"
  timezone: "UTC"
  jitter_minutes: 8

tags:
  - "punk"
  - "hardcore"

blacklist_tags:
  - "electronic"
  - "pop"

parser:
  request_delay: 1.5
```

### 5. Run

```bash
# With schedule
python run.py

# One-time
python run_once.py
```

## ⚠️ First Run

**On the first run**, the bot will send **all current releases** from the
selected tags - this can be many messages!

**On subsequent runs** — only new releases not in the database.

### Tips:

1. Start with 2-3 tags
2. After first run, add remaining tags

## Settings

### Schedule

Time format: `"HH:MM"` (24-hour)

```yaml
schedule:
  times:
    - "08:00"
    - "14:00"
    - "22:00"
  timezone: "UTC"
  jitter_minutes: 8  # random delay (minutes) added after each run time
```

### Timezones

- `"UTC"` — Coordinated Universal Time
- `"Europe/Moscow"` — Moscow
- `"Europe/Kiev"` — Kyiv
- `"America/New_York"` — New York

### Tags

```yaml
tags:
  - "punk"
  - "hardcore punk"
  - "d-beat"
  - "crust punk"
```

Tags that aren't one of Bandcamp's own curated genres are automatically
mapped to the closest one (see `GENRE_FALLBACK` in `src/parser.py`, or the
`/genre_list` Telegram command once the bot is running).

### Blacklist

Releases from these tags are added to DB but **not sent**:

```yaml
blacklist_tags:
  - "happy hardcore"
  - "electronic"
  - "techno"
```

## Reconfiguring after launch

Once the bot is running, you can add/remove tags and blacklist entries,
change the schedule, and edit genre mappings directly from Telegram instead
of editing files - send `/help` to the bot's chat for the full command list.

## Verification

After launch:
1. Bot sends a startup message
2. Starts working on schedule
3. Logs in `bandcamp_bot.log`

## Stop

`Ctrl+C`

## Files

| File | Description |
|------|-------------|
| `run.py` | Run with schedule |
| `run_once.py` | One-time run |
| `config.yaml` | Settings |
| `config.overrides.yaml` | Bot-writable overrides from Telegram admin commands (created automatically) |
| `.env` | Tokens (copy from `.env.example`) |
| `bandcamp_bot.log` | Logs (rotated daily, 4 weeks kept) |
| `bandcamp_releases.db` | Database |
