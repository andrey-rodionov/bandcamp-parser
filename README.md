# Bandcamp Parser Bot

A bot for automatic monitoring of new music releases on Bandcamp by specified tags and sending notifications to Telegram.

## Features

- 🔍 **Release parsing** from Bandcamp by configurable tags
- 🚫 **Tag blacklist** — exclude unwanted genres
- 📱 **Telegram notifications** with release info and link
- ⏰ **Flexible scheduling** — configurable (hourly by default)
- 🗄️ **SQLite database** for tracking sent releases
- 🌐 **Selenium WebDriver** for dynamic content
- 🔄 **Automatic retries** on network failures

## Important: First Run

⚠️ **On the first run**, the bot will add to the database and send to Telegram **all releases** currently on the pages of selected tags. This can be many messages!

**On subsequent runs**, the bot will only send **new releases** that are not yet in the database.

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

### 2. Install Chrome and ChromeDriver

**macOS:**
```bash
brew install --cask google-chrome
brew install chromedriver
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y chromium-browser chromium-chromedriver
```

**Windows:**
- Install [Google Chrome](https://www.google.com/chrome/)
- ChromeDriver will be installed automatically

### 3. Create Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` and follow instructions
3. Copy the bot token
4. Get your Chat ID via [@userinfobot](https://t.me/userinfobot)

### 4. Configure .env

Create `.env` file in project root:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 5. Configure config.yaml

```yaml
# Schedule (every hour from 07:00 to 01:00)
schedule:
  times:
    - "07:00"
    - "08:00"
    # ... etc.
  timezone: "Europe/Moscow"

# Tags to monitor
tags:
  - "punk"
  - "hardcore"

# Blacklist (releases added to DB but NOT sent)
blacklist_tags:
  - "pop"
  - "electronic"

# Parser settings
parser:
  request_delay: 1.5         # Delay between requests (sec)
```

### 6. Run

**Continuous scheduled operation:**
```bash
python run.py
```

**One-time run:**
```bash
python run_once.py
```

## Configuration

### Schedule (`schedule`)

| Parameter | Description | Example |
|-----------|-------------|---------|
| `times` | List of run times (HH:MM) | `["07:00", "12:00", "18:00"]` |
| `timezone` | Timezone | `"Europe/Moscow"` |

### Tags (`tags`)

List of Bandcamp tags to monitor:

```yaml
tags:
  - "punk"
  - "hardcore punk"
  - "d-beat"
  - "crust punk"
```

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

### Parser (`parser`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `request_delay` | Delay between requests (sec) | `1.5` |

### Database (`database`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `db_path` | Path to DB file | `bandcamp_releases.db` |
| `cleanup_days` | Delete records older than N days | `90` |

## Project Structure

```
.
├── src/
│   ├── __init__.py        # Module exports
│   ├── config.py          # Configuration (dataclasses)
│   ├── database.py        # SQLite operations
│   ├── parser.py          # Bandcamp parser (Selenium)
│   ├── telegram_bot.py    # Telegram messaging
│   ├── scheduler.py       # Scheduler (APScheduler)
│   └── main.py            # Main BandcampBot class
├── config.yaml            # Settings
├── .env                   # Secrets (tokens)
├── requirements.txt       # Python dependencies
├── run.py                 # Run with schedule
├── run_once.py            # One-time run
└── bandcamp_releases.db   # Database (created automatically)
```

## How Parsing Works

1. **Start WebDriver** — headless Chrome is created
2. **Load page** — `bandcamp.com/discover/{tag}?s=new`
3. **Cookie consent** — automatic acceptance
4. **View more results** — click button to load more
5. **Parse HTML** — extract release information
6. **Check DB** — skip already sent releases
7. **Send to Telegram** — formatted message
8. **Save to DB** — prevent duplicates

## Logging

Logs are written to:
- `bandcamp_bot.log` — file
- Console — real-time

Format:
```
2025-01-04 12:00:00 - src.parser - INFO - Found 25 releases for tag 'punk'
2025-01-04 12:00:01 - src.telegram_bot - INFO - Sent: Album Name by Artist
```

## Troubleshooting

### Bot not sending messages

- Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Make sure bot is added to chat with send permissions

### Selenium not starting

- Install Chrome browser
- Check Chrome/ChromeDriver version compatibility
- Linux: install `libnss3 libatk-bridge2.0-0 libxkbcommon0`

### Releases not found

- Check tag correctness on Bandcamp website
- Check logs for errors

### Tasks not running on schedule

- Check timezone in `timezone`
- Time format: `"HH:MM"` (24-hour)
- Make sure application is running

## Server Deployment

### systemd (Linux)

Create `/etc/systemd/system/bandcamp-bot.service`:

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
- **Selenium** — dynamic content parsing
- **BeautifulSoup4** — HTML parsing
- **python-telegram-bot** — Telegram messaging
- **APScheduler** — task scheduler
- **SQLite** — database

## License

MIT
