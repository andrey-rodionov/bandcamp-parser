# Windows 10/11 Installation

## Requirements

- Python 3.9+

No browser or driver installation needed - the bot talks to Bandcamp over
plain HTTP.

## Step 1: Install Python

1. Download Python from [python.org](https://www.python.org/downloads/)
2. **Important:** check ✅ **"Add Python to PATH"**
3. Verify:
   ```cmd
   python --version
   ```

## Step 2: Prepare Project

Open Command Prompt (`Win + R` → `cmd`)

```cmd
cd "C:\path\to\project"

python -m venv venv
venv\Scripts\activate

python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

## Step 3: Create Telegram Bot

1. [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy token
3. [@userinfobot](https://t.me/userinfobot) → get Chat ID

## Step 4: Configure .env

Copy the example file:
```cmd
copy .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

**No quotes!**

## Step 5: Configure config.yaml

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

max_release_age_days: 30

parser:
  request_delay: 1.5
```

## Step 6: Run

```cmd
# Test (one-time)
python run_once.py

# With schedule
python run.py
```

## ⚠️ First Run

**On the first run**, the bot will send **all current releases** — many
messages!

**After that** — only new releases.

### Tip:
1. Start with 2-3 tags
2. After first run, add more tags

## Reconfiguring after launch

Once running, you can add/remove tags and blacklist entries and change the
schedule directly from Telegram instead of editing files - send `/help` to
the bot's chat for the full command list.

## Troubleshooting

### "ModuleNotFoundError"

```cmd
venv\Scripts\activate
pip install -r requirements.txt
```

### A tag returns no releases

Check the tag's spelling against the Bandcamp website - an unrecognized tag
just comes back with zero results, not an error.

## Auto-start

### Using NSSM

1. Download [NSSM](https://nssm.cc/download)
2. Install:
   ```cmd
   nssm install BandcampBot "C:\path\venv\Scripts\python.exe" "C:\path\run.py"
   ```
3. Management:
   ```cmd
   nssm start BandcampBot
   nssm stop BandcampBot
   ```

## Logs

- `bandcamp_bot.log` — file, rotated daily, 4 weeks kept
- Console — real-time
