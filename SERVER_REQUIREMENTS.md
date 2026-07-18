# Server Requirements

## Current Configuration

- **Tags:** 17 main + 3 blacklist
- **Schedule:** every hour from 08:00 to 00:00 UTC (17 runs/day)

## Minimum Requirements

Since the bot fetches releases via a plain HTTP API call instead of driving
a headless browser, its footprint is small.

| Parameter | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 1 vCPU | 1 vCPU |
| **RAM** | 256 MB | 512 MB |
| **Disk** | 1 GB | 5 GB SSD |
| **Network** | 512 Kbps | 1 Mbps |

### Memory Distribution

- Python process (parsing + Telegram bot + admin bot + scheduler): ~40-60 MB
- SQLite: ~30-50 MB
- System: ~150 MB

## Recommended Configuration

```
CPU: 1 vCPU
RAM: 512 MB
Disk: 5 GB SSD
OS: Ubuntu 22.04 LTS
```

## Installation on Ubuntu/Debian

```bash
# Update
sudo apt-get update && sudo apt-get upgrade -y

# Dependencies
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv

# Project
cd /opt
git clone https://github.com/andrey-rodionov/bandcamp-parser.git bandcamp-bot
cd bandcamp-bot

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp .env.example .env
nano .env
nano config.yaml
```

## systemd

A ready-to-use unit file is included at `bandcamp-bot.service` in the
repository - adjust `WorkingDirectory`/paths as needed and copy it to
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

```bash
sudo systemctl daemon-reload
sudo systemctl enable bandcamp-bot
sudo systemctl start bandcamp-bot
```

## ⚠️ First Run on Server

**On the first run**, all current releases will be sent!

### Recommendations:

1. Start with 2-3 tags in `config.yaml`
2. Run `python run_once.py`
3. After DB is populated, add remaining tags (directly in `config.yaml`, or
   via `/tags_add` in Telegram once the service is running)
4. Start the service

## Monitoring

```bash
# Status
sudo systemctl status bandcamp-bot

# Logs
sudo journalctl -u bandcamp-bot -f

# Resources
htop

# Database
sqlite3 /opt/bandcamp-bot/bandcamp_releases.db "SELECT COUNT(*) FROM releases;"
```

You can also check `/status` in Telegram for DB stats, disk usage, and the
last successful run time without shelling in.

## Log Rotation

Handled in-process (daily rotation, 4 weeks retained) - no `logrotate`
configuration needed.

## Database Cleanup

The database prunes itself two ways, both configurable in `config.yaml`:
- `cleanup_days` — delete records older than N days (disabled by default)
- `disk_usage_threshold_percent` / `disk_usage_target_percent` — once disk
  usage crosses the threshold, delete the oldest records (regardless of age)
  until usage drops back down, then reclaim the space with `VACUUM`

## VPS Providers

| Provider | Plan | Price |
|----------|------|-------|
| Hetzner | CX11 | €4/mo |
| DigitalOcean | Basic | $6/mo |
| Linode | Nanode | $5/mo |
| Vultr | Cloud | $6/mo |

## Scaling

For 50+ tags:
- RAM: 1 GB
- CPU: 2 vCPU
- Consider PostgreSQL
