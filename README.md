# 🌸 YouTube Telegram Bot 🌸

Welcome to Kawaii TelegramBot, your adorable assistant for downloading audio from YouTube! 😺

## Features

- ✨ Cute and easy-to-use Telegram Bot
- 📥 Downloads audio from YouTube (FLAC/M4A/MP3, auto-picked to fit the size cap)
- ⭐ Built-in payment system: premium subscriptions via **Telegram Stars**, no external
  payment provider needed (`/premium`, `/refund`)
- 📏 Tiered file-size limits: standard users get Telegram's cloud-API cap (50 MB), while
  premium/admin/subscribed users get a much higher cap *if* a local Bot API server is
  configured (see below) -- otherwise everyone gets the same safe default
- 🚦 A bounded, persistent download queue: requests wait their turn instead of
  overwhelming the bot, a full queue is rejected with a clear message instead of piling
  up, and a crash/power-cut never silently "resumes" a half-finished job -- affected
  users are notified instead
- 🛡️ Defense-in-depth security: URL/host allowlisting, per-user flood control, admin-only
  commands, ffmpeg timeouts, idempotent payment handling
- 💌 Sends full metadata (title, artist, duration, thumbnail) with every song
- 🧰 One-command setup script for a plain Linux server, no Docker required

## Getting Started

### Prerequisites

- Python 3.11+
- `ffmpeg` on PATH
- A bot token from [@BotFather](https://t.me/BotFather)

> [!NOTE]
> You will also need Node.js installed, since generating a `po_token` for YouTube is no
> longer optional for `pytubefix`. `requirements.txt` already includes
> `nodejs-wheel-binaries`, which provides this without a system-wide Node.js install.

### Option A: automated setup (recommended)

```bash
git clone https://github.com/JohnKun136NVCP/yt-telegrambot.git
cd yt-telegrambot
./scripts/setup.sh
```

This installs system packages (ffmpeg, build tools) and Python dependencies into a
virtualenv, walks you through writing a `.env` (token, admins, size limits, queue
settings, Stars plans), optionally builds and wires up a **local Telegram Bot API
server** (the only way to go past Telegram cloud API's 50 MB upload cap), and can
install systemd services for both the bot and the local server so they survive reboots
and crash-restart automatically. It's safe to re-run: it asks before overwriting
anything it already created. See `./scripts/setup.sh --help`.

### Option B: manual setup

```bash
git clone https://github.com/JohnKun136NVCP/yt-telegrambot.git
cd yt-telegrambot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env-example .env   # then edit .env -- at minimum, set TOKEN
python3 main.py
```

`.env-example` documents every setting (file-size tiers, queue size/workers,
flood control, Stars subscription plans, local Bot API server). Missing or invalid
required values make the bot refuse to start with a clear error, instead of crashing
confusingly later.

### Going over 50 MB (premium file sizes)

Telegram's cloud Bot API hard-caps uploads/downloads at 50 MB **no matter what the bot
sends** -- this is a Telegram-side limit, not something any bot code can work around.
The only fix is self-hosting
[`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api) and pointing this bot at
it (`BOT_API_BASE_URL`, `BOT_API_LOCAL_MODE=true` in `.env`); `scripts/setup.sh` can
build and configure this for you. Without it, `PREMIUM_MAX_MB` is ignored and everyone
gets `STANDARD_MAX_MB`.

## Bot commands

| Command | Who | What |
|---|---|---|
| `/start`, `/help` | everyone | intro / usage |
| `/subscribe` | everyone | ways to support the project |
| `/myid` | everyone | your Telegram user id |
| `/status` | everyone | current download/queue status |
| `/premium` | everyone | buy/check premium with Telegram Stars |
| `/grant`, `/revoke` | admins | grant/revoke premium for a user |
| `/refund` | admins | refund a user's most recent Stars payment |
| `/stats` | admins | usage stats |

Just send a YouTube link to download its audio.

## Suggestions

Please create a virtual environment and enjoy the cuteness! 🌸💖

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for
details.

## Contributing

Feel free to fork this project, open issues, or submit pull requests. Let's make this
bot even more adorable together! 🥳

## Contact

If you have any questions or need assistance, don't hesitate to reach out. You can
contact me via Telegram or open an issue on GitHub. Happy downloading! 😊
