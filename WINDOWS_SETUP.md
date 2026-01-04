# Windows 10/11 Installation

## Requirements

- Python 3.9+
- Google Chrome
- ChromeDriver

## Step 1: Install Python

1. Download Python from [python.org](https://www.python.org/downloads/)
2. **Important:** check ✅ **"Add Python to PATH"**
3. Verify:
   ```cmd
   python --version
   ```

## Step 2: Install Chrome

Download and install [Google Chrome](https://www.google.com/chrome/)

## Step 3: Prepare Project

Open Command Prompt (`Win + R` → `cmd`)

```cmd
cd "C:\path\to\project"

python -m venv venv
venv\Scripts\activate

python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

If Pillow fails:
```cmd
pip install --only-binary :all: Pillow
```

## Step 4: Create Telegram Bot

1. [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy token
3. [@userinfobot](https://t.me/userinfobot) → get Chat ID

## Step 5: Configure .env

Create `.env` file:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

**No quotes!**

## Step 6: Configure config.yaml

```yaml
schedule:
  times:
    - "07:00"
    - "12:00"
    - "18:00"
  timezone: "Europe/Moscow"

tags:
  - "punk"
  - "hardcore"

blacklist_tags:
  - "electronic"

parser:
  request_delay: 1.5
```

## Step 7: Run

```cmd
# Test (one-time)
python run_once.py

# With schedule
python run.py
```

## ⚠️ First Run

**On the first run**, the bot will send **all current releases** — many messages!

**After that** — only new releases.

### Tip:
1. Start with 2-3 tags
2. After first run, add more tags

## Troubleshooting

### "ChromeDriver not found"

```cmd
pip install webdriver-manager
```

### "ModuleNotFoundError"

```cmd
venv\Scripts\activate
pip install -r requirements.txt
```

### "Failed to initialize Selenium"

- Check Chrome version
- Reinstall ChromeDriver
- Disable antivirus

### Pillow installation fails

```cmd
pip install --only-binary :all: Pillow
```

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

- `bandcamp_bot.log` — file
- Console — real-time
