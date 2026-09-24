# Staff.am Job Parser Bot

A multi-user Telegram bot that watches [staff.am](https://staff.am) job listings and notifies each user about new jobs matching their own personal keyword filters.

## How it works

- **`bot.py`** — long-running Telegram bot. Users register automatically on `/start`, then manage their own filters (add/remove keywords) through inline buttons or commands. Runs as a `systemd` service.
- **`parser.py`** — runs periodically via `cron`. Fetches staff.am job listings for the union of all users' keywords (one request per unique keyword, not per user), then sends each user only the jobs matching their filters that they haven't seen yet.
- **`db.py`** — SQLite storage (`staff_am_bot.db`). Tables: `users`, `filters`, `seen_jobs`. Each user's filters and notification history are fully isolated.
- **`keyboards.py`** — shared inline keyboard layout used by both the bot and the parser (parser re-shows the menu after sending new jobs).
- **`logging_setup.py`** — shared rotating logger. Log files (`parser.log`, `bot.log`) auto-rotate at 10 MB and get gzip-archived into `LogArchive/`.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file:
```
TOKEN=your_telegram_bot_token
```

## Running

**Bot** (keep running permanently, e.g. via systemd):
```bash
python3 bot.py
```

**Parser** (run periodically via cron, e.g. every hour):
```bash
python3 parser.py
```

Example crontab entry:
```
0 * * * * cd /path/to/project && /path/to/.venv/bin/python3 parser.py
```


## Recommended systemd setup

The supplied user units assume the project is located at
`~/Documents/Staff_am_Parser`. If it is elsewhere, edit the paths in
`deploy/systemd/*.service` first.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now staff-am-bot.service staff-am-parser.timer
```

Check configuration and service health:

```bash
.venv/bin/python healthcheck.py
systemctl --user status staff-am-bot.service staff-am-parser.timer
systemctl --user list-timers staff-am-parser.timer
journalctl --user -u staff-am-bot.service -u staff-am-parser.service -f
```

The bot restarts after failures. The parser runs hourly, catches up after
machine downtime, and cannot overlap with another parser process.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite uses temporary SQLite databases and mocked HTTP calls, so it does not
contact staff.am or Telegram. It also runs automatically in GitHub Actions.

## Bot commands

- `/start` — register and show the menu
- `/filters` — show your current filters
- `/add <word>` — add a filter, e.g. `/add QA`
- `/remove <word>` — remove a filter, e.g. `/remove Django`

Inline buttons (Filters / Add / Remove) do the same thing without typing commands.

## Notes

- Each notification includes: job title, company, image, and link.
- New users start with an empty filter list.
- When a filter is added, existing matching jobs become its baseline; notifications start with jobs found on later parser runs.
- `seen_jobs` entries older than 30 days are cleaned up automatically on each parser run.
