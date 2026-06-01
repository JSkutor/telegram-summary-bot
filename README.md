# Telegram Summary Bot

Telegram channel digest bot that checks for new messages on a schedule, creates a Gemini-powered Markdown summary every 3 days, and saves the result to an Obsidian vault. It is designed for macOS automation with `launchd`, with retry and state tracking so failed API runs can be picked up later.

## Features

- Fetches Telegram channel messages with Telethon
- Summarizes messages with the Gemini API
- Saves Markdown notes into an Obsidian vault
- Automates scheduled runs with macOS `launchd`
- Tracks the last successful run to avoid gaps after API failures, sleep, or missed schedules
- Keeps API keys and local runtime files out of git

## Project Description

Suggested GitHub description:

```text
Telegram channel digest bot for macOS: periodically checks channels, summarizes messages with Gemini, and saves Markdown digests to Obsidian via iCloud. Automated with launchd and resilient to missed or failed runs.
```

Why this is more accurate than “fetches messages every 3 days”: the app can wake up more frequently, such as every 6 hours, while only producing a digest when the configured digest interval has elapsed. This lets failed API runs retry sooner without changing the 3-day digest cadence.

## Installation

```bash
git clone https://github.com/JSkutor/telegram-summary-bot.git
cd telegram-summary-bot

python3 -m venv venv
./venv/bin/pip install -r requirements.txt

cp config.example.yaml config.yaml
cp .env.example .env
```

## Configuration

Put secrets in `.env`, not directly in `config.yaml`.

```dotenv
TELEGRAM_API_ID=123456
TELEGRAM_API_SECRET=your_telegram_api_hash
GEMINI_API_KEY=your_gemini_api_key
```

Edit `config.yaml` for channels, Obsidian output, digest interval, and retry behavior.

```yaml
telegram:
  channels:
    - "@channel_username"

output:
  obsidian_vault_path: "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/{vault_name}"
```

Get Telegram API credentials from https://my.telegram.org under `API development tools`. Get a Gemini API key from https://aistudio.google.com.

## First Run

Telethon requires one manual login before automation can work. Run this before installing the LaunchAgent:

```bash
./venv/bin/python main.py --dry-run
```

After login, Telethon creates a `tg_summary_session.session` file. This is a private auth session and must not be committed.

## Common Commands

```bash
# Test message fetching only
./venv/bin/python main.py --dry-run

# Run only if the digest interval has elapsed
./venv/bin/python main.py

# Run immediately, ignoring the digest interval
./venv/bin/python main.py --force

# Generate and register the LaunchAgent plist
./venv/bin/python launchd_manager.py install

# Register and request one immediate launchd run
./venv/bin/python launchd_manager.py install --run-now

# Check launchd status
./venv/bin/python launchd_manager.py status

# Unregister the LaunchAgent
./venv/bin/python launchd_manager.py uninstall
```

## launchd Automation

`launchd_manager.py` generates the plist from the current project path, Python virtualenv path, config path, and log path. You do not need to keep a plist template in the repository.

```bash
./venv/bin/python launchd_manager.py install
```

By default, launchd wakes the app every 6 hours. The app then checks its own state and exits immediately if the real digest interval, default 72 hours, has not elapsed. If an API call fails, the next 6-hour launchd check can retry instead of waiting another 3 days.

```bash
# Change the launchd check interval to 3 hours
./venv/bin/python launchd_manager.py install --check-interval-hours 3

# Request one immediate launchd run after registration
./venv/bin/python launchd_manager.py install --run-now
```

Useful management commands:

```bash
./venv/bin/python launchd_manager.py status
./venv/bin/python launchd_manager.py run
./venv/bin/python launchd_manager.py run --force
./venv/bin/python launchd_manager.py logs
./venv/bin/python launchd_manager.py uninstall
```

## Gap Prevention

The bot writes `config.state.json` next to `config.yaml` by default. It stores the last successful run time. On the next run, the bot fetches messages from slightly before that timestamp using `runtime.state_overlap_minutes`, which defaults to 360 minutes.

Gemini requests retry 5 times by default. Retryable errors include `429`, `500`, `502`, `503`, `504`, `UNAVAILABLE`, and `RESOURCE_EXHAUSTED`. If all retries fail, `last_success_utc` is not updated, so the next launchd check retries the same time window.

The digest cadence is controlled in `config.yaml`:

```yaml
runtime:
  digest_interval_hours: 72
  state_overlap_minutes: 360
```

## macOS Sleep

This project does not force your Mac to wake from sleep. The generated plist uses `StartInterval`; it does not use wake-oriented settings such as `WakeToRun` or a persistent `KeepAlive` loop.

If the Mac is asleep when a scheduled launchd interval passes, the job does not run at that exact time. After the Mac wakes, launchd usually gets another opportunity to run the job, but missed intervals are not replayed one by one. This is why the app stores the last successful run time and fetches based on state rather than trusting the wall-clock schedule alone.

## Manual Runs

```bash
# Run only if the configured digest interval has elapsed
./venv/bin/python main.py

# Run immediately
./venv/bin/python main.py --force

# Fetch messages only
./venv/bin/python main.py --dry-run

# Use a custom config or env file
./venv/bin/python main.py --config /path/to/config.yaml --env-file /path/to/.env
```

## Files Not Committed

The following files are local-only and ignored by git:

- `config.yaml`
- `.env`
- `*.session`, `*.session-journal`
- `*.state.json`, `*.lock`
- `venv/`
- `*.plist`
- `.DS_Store`

## Project Structure

```text
telegram-summary-bot/
├── main.py              # Entry point
├── telegram_fetcher.py  # Telegram message collection
├── summarizer.py        # Gemini summarization
├── file_writer.py       # Obsidian Markdown output
├── launchd_manager.py   # launchd install/status/uninstall helper
├── config.example.yaml  # Example configuration
├── .env.example         # Example environment variables
└── requirements.txt
```
