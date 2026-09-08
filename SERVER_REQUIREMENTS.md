# Server Requirements

## Current Configuration

- **Tags:** 17 main + 3 blacklist
- **Schedule:** every hour from 00:00 to 16:00 UTC, paused 17:00-23:00 UTC (17 runs/day)

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

## Installation on Ubuntu/Debian (Docker)

Runs in a container instead of a bare venv, so it can share a server with
other apps without their Python dependencies conflicting.

```bash
# Docker Engine + Compose plugin
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker

# Project
cd /opt
git clone https://github.com/andrey-rodionov/bandcamp-parser.git bandcamp-bot
cd bandcamp-bot

# Configuration
cp .env.example .env
nano .env
nano config.yaml

# Build and start
docker compose build
docker compose up -d
```

`docker-compose.yml` bind-mounts the project directory into the container,
so `config.yaml`, `.env`, the SQLite database, and the logs all live on the
host at the same paths as before - only `requirements.txt`'s dependencies
are baked into the image. A code update is a `git pull` (or re-upload) plus
`docker compose up -d --build`; editing `config.yaml`/`.env` just needs
`docker compose restart`. `restart: unless-stopped` in the compose file
keeps it running across reboots the same way `systemd`'s `Restart=always`
did previously.

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
docker compose ps

# Logs
docker compose logs -f

# Resources
docker stats bandcamp-bot

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
