# Server Requirements

## Current Configuration

- **Tags:** 18 main + 3 blacklist
- **Schedule:** every hour from 07:00 to 01:00 (19 runs/day)

## Minimum Requirements

| Parameter | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 1 vCPU | 2 vCPU |
| **RAM** | 512 MB | 1 GB |
| **Disk** | 2 GB | 10 GB SSD |
| **Network** | 1 Mbps | 5 Mbps |

### Memory Distribution

- Python: ~100 MB
- Chrome headless: ~300 MB
- SQLite: ~50 MB
- System: ~200 MB

## Recommended Configuration

```
CPU: 2 vCPU
RAM: 1 GB
Disk: 10 GB SSD
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
    python3-venv \
    chromium-browser \
    chromium-chromedriver

# Project
cd /opt
git clone <repo> bandcamp-bot
cd bandcamp-bot

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
nano .env
nano config.yaml
```

## systemd

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
3. After DB is populated, add remaining tags
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

## Log Rotation

Create `/etc/logrotate.d/bandcamp-bot`:

```
/opt/bandcamp-bot/bandcamp_bot.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

## VPS Providers

| Provider | Plan | Price |
|----------|------|-------|
| Hetzner | CX11 | €4/mo |
| DigitalOcean | Basic | $6/mo |
| Linode | Nanode | $5/mo |
| Vultr | Cloud | $6/mo |

## Scaling

For 50+ tags:
- RAM: 2 GB
- CPU: 2-4 vCPU
- Consider PostgreSQL
