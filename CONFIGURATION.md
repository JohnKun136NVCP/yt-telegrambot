# Configuration guide

This document covers every `.env` variable, exactly what `scripts/setup.sh` does
step by step, and how to troubleshoot the most common problems (especially around
building the optional local Bot API server on a small VPS). For a quick start, see
the main [README](README.md).

## `.env` reference

Copy `.env-example` to `.env` (or let `scripts/setup.sh` do it for you) and fill
these in. `.env` is loaded by `main.py` via `python-dotenv` and must never be
committed -- `scripts/setup.sh` writes it with `chmod 600`.

### Required

| Variable | Description |
|---|---|
| `TOKEN` | Bot token from [@BotFather](https://t.me/BotFather). The bot refuses to start without it. |
| `ADMIN_IDS` | Comma-separated Telegram user IDs with admin access (`/grant`, `/revoke`, `/refund`, `/stats`). Get your own id from [@userinfobot](https://t.me/userinfobot). Leave empty for no admins (not recommended). |

### File size tiers

| Variable | Default | Description |
|---|---|---|
| `STANDARD_MAX_MB` | `49.5` | Max file size (MB) for everyone. Telegram's cloud Bot API hard-caps uploads/downloads at 50 MB no matter what the bot sends, so this should normally stay under that. |
| `PREMIUM_MAX_MB` | `1900` | Max file size for premium/admin/subscribed users. Only takes effect once `BOT_API_BASE_URL` points at a self-hosted local Bot API server -- otherwise premium users are silently capped at `STANDARD_MAX_MB` too (see `src/config.py: Config.effective_premium_max_mb()`). |

### Download queue

Bounded and persistent: it survives a restart/crash without losing track of what
was in flight, but it never silently auto-resumes a job after an unclean shutdown --
it only notifies the affected user that their request was lost.

| Variable | Default | Description |
|---|---|---|
| `QUEUE_MAX_SIZE` | `50` | Max requests allowed to sit in the wait queue before new ones are rejected with a "queue is full" message instead of piling up. |
| `QUEUE_WORKERS` | `2` | Concurrent downloads/conversions/uploads. |
| `JOB_TIMEOUT_SECONDS` | `1800` | Hard per-job timeout so one stuck download/ffmpeg call can't occupy a worker forever. |

### Flood control

| Variable | Default | Description |
|---|---|---|
| `MIN_SECONDS_BETWEEN_REQUESTS` | `3` | Minimum seconds a single user must wait between requests. |

### Telegram Stars subscription plans (payments)

| Variable | Default | Description |
|---|---|---|
| `STAR_PLANS` | (bundled defaults) | Format: `code:label:days:stars,code:label:days:stars,...`. Leave empty to use the bundled defaults (1 week / 1 month / 1 year -- see `src/config.py: DEFAULT_PLANS`). 1 Telegram Star is roughly $0.013 USD, a rate Telegram sets, not this bot. |

### Local Telegram Bot API server (optional)

Only needed to go over the 50 MB cloud-API cap. Built and wired up automatically by
`scripts/setup.sh` if you opt in; see [tdlib/telegram-bot-api](https://github.com/tdlib/telegram-bot-api)
to build it by hand instead.

| Variable | Default | Description |
|---|---|---|
| `BOT_API_BASE_URL` | empty | Host[:port] of your local server, e.g. `http://127.0.0.1:8081` -- no `/bot` suffix, no trailing slash. Leave empty to use Telegram's cloud API. |
| `BOT_API_LOCAL_MODE` | `false` | Set `true` once `BOT_API_BASE_URL` is set and the bot runs on the SAME machine (and ideally the same system user) as the local server, so files can be handed over as `file://` paths instead of being re-uploaded over HTTP. |
| `TELEGRAM_API_ID` | empty | `api_id` from [my.telegram.org/apps](https://my.telegram.org/apps). **Not read by the bot** (`src/config.py` never looks at it) -- `scripts/setup.sh` stores it here purely so a re-run doesn't ask for it again, and so it can fill it into the `telegram-bot-api` systemd unit. |
| `TELEGRAM_API_HASH` | empty | `api_hash` from the same page. Same "not read by the bot" caveat as `TELEGRAM_API_ID`. |

## What `scripts/setup.sh` does

The script is interactive by default and safe to re-run: every step asks before
overwriting something it already created, and a value it already has (in `.env`,
or an already-built binary) is never thrown away or re-requested without asking
first. Run `./scripts/setup.sh --help` for the short version, or
`./scripts/setup.sh --non-interactive` to accept every default, skip the local Bot
API server build, and print systemd unit files instead of installing them (useful
in CI).

1. **System packages.** Asks before installing/updating anything (`ffmpeg`,
   `python3`, `cmake`, a C++ compiler and the other build tools) with the distro's
   package manager (`apt`/`dnf`/`pacman`). Installation output is redirected to
   `/tmp/yt-telegrambot-packages.log` instead of flooding the terminal -- only a
   one-line summary is printed live. If the package manager reports orphaned
   packages afterwards, it offers to run `autoremove` (or the pacman/dnf
   equivalent) before moving on. Finally, regardless of whether packages were
   installed, already present, or skipped, it verifies that every tool the bot and
   this script need (`python3 ffmpeg git cmake g++ make gperf`) is actually on
   `PATH`, and warns (asking whether to continue anyway) if anything is still
   missing.
2. **Python virtualenv.** Creates `.venv/` if missing and installs
   `requirements.txt` into it.
3. **`.env`.** If one already exists, asks whether to start it over from scratch
   (backing up the old one first) or keep it. Either way, every value still
   missing or blank afterwards gets prompted for -- a half-filled `.env` from an
   interrupted previous run gets completed instead of silently shipping a blank
   `TOKEN`. `TOKEN` is the only value that loops until it's non-empty.
4. **Runtime directories.** Creates `logs/`, `database/`, `Songs/`, `img/`,
   `thumbimg/` if they don't exist.
5. **Local Telegram Bot API server (optional).** Only runs if you opt in; skip it
   if the 50 MB cloud cap is fine for your users. See the dedicated section below
   for the details -- it's the step most likely to need troubleshooting on a small
   VPS.
6. **systemd units.** Writes `yt-telegrambot.service` and, if the local server was
   built, `telegram-bot-api.service`, then enables and starts them. Both units run
   as the **same system user** on purpose: the bot's fast file-upload path hands
   `telegram-bot-api` a plain filesystem path (`file://...`) instead of streaming
   the bytes itself, which only works if both processes can read/write the same
   files. If `systemctl` isn't available, this step is skipped and the script
   prints how to run the bot manually instead.

## Deploying updates: `scripts/update.sh`

`scripts/setup.sh` is for first-time setup (or re-running it to change `.env`,
packages, or the local server build). For just picking up new commits on this
branch, use the lighter, non-interactive-by-default `scripts/update.sh` instead:

```bash
./scripts/update.sh
```

In one command, it:

1. Refuses to pull over uncommitted local changes on the server (asks first
   interactively; just aborts with `--non-interactive`/`-y`), so a manual edit
   you made directly on the VPS is never silently overwritten.
2. Runs `git pull --ff-only` on whatever branch is currently checked out. A
   fast-forward-only pull never creates a merge commit; if your branch has
   diverged (local commits the remote doesn't have), it stops and tells you to
   resolve that yourself instead of guessing.
3. Reinstalls Python dependencies -- but only if `requirements.txt` actually
   changed in the pulled commits, so most updates skip this step. Pass
   `--skip-deps` to skip it unconditionally.
4. Restarts `yt-telegrambot.service` (and `telegram-bot-api.service` too, if
   that unit exists) via systemd, using `sudo` if you're not root.

It never touches `.env`, never installs system packages, and never rebuilds
the local Bot API server -- for any of those, use `scripts/setup.sh`.

## Checking for vulnerable dependencies: `scripts/check_updates.sh`

`requirements.txt` is pinned to exact versions, which is good for reproducible
installs but means a known vulnerability discovered in a pinned package stays
there until someone bumps it by hand. `scripts/check_updates.sh` automates that
safely:

```bash
./scripts/check_updates.sh
```

In one command, it:

1. Scans `requirements.txt` for known vulnerabilities using
   [`pip-audit`](https://pypi.org/project/pip-audit/) (checks against the PyPI
   Advisory Database / OSV), run in a throwaway virtualenv so it never pollutes
   the real one. If nothing is flagged, it says so and stops.
2. If something is flagged, lets `pip-audit --fix` propose a version bump --
   but only on a **scratch copy** of `requirements.txt`, never the real file.
3. Installs that scratch copy into a **second**, disposable virtualenv from
   nothing, and smoke-tests it: every package in it must import cleanly, and so
   must this project's own modules that directly use the packages being bumped
   (`src/security.py`, `src/yb/meta.py`, `src/yb/songs.py`, `src/uploader.py`,
   `database/databases.py`).
4. Only if that smoke test passes does it copy the fix over the real
   `requirements.txt`, reinstall the real `.venv`, and restart the running
   service(s) (same restart step as `scripts/update.sh`).
5. If anything fails along the way -- the fix doesn't install, or something
   fails to import -- it prints exactly what broke and leaves the real
   `requirements.txt` and `.venv` completely untouched. Nothing is restarted.

It never commits or pushes anything -- it only changes the file on disk. If you
want a fix it applied to also land in the repository, commit and push
`requirements.txt` yourself afterwards.

Flags: `--non-interactive`/`-y` applies a fix automatically once (and only
once) it passes the smoke test, which makes this safe to run unattended, e.g.
from a weekly cron job:

```cron
# Every Sunday at 4:17am, check for and safely apply dependency fixes.
17 4 * * 0 cd /path/to/yt-telegrambot && ./scripts/check_updates.sh -y >> logs/check_updates.log 2>&1
```

`--report-only` just scans and prints what's vulnerable without installing,
changing, or restarting anything. See `./scripts/check_updates.sh --help`.

## Building the local Bot API server

This step clones and compiles [`tdlib/telegram-bot-api`](https://github.com/tdlib/telegram-bot-api)
(including its `td` submodule) from source. It's the only way to get past
Telegram's 50 MB cloud-API cap, but it is also the heaviest and most failure-prone
part of setup, especially on a small VPS. Here's what the script does to make it
safer, and what to do if it still goes wrong.

### Credentials are asked for once

`api_id`/`api_hash` (from [my.telegram.org/apps](https://my.telegram.org/apps)) are
saved into `.env` as soon as you provide them (`TELEGRAM_API_ID` /
`TELEGRAM_API_HASH`), the same way `TOKEN` is. Re-running the script, or just
reaching this step again after an earlier interrupted run, will not ask for them a
second time -- it reads them back out of `.env`.

### Reusing an existing build

Before compiling anything, the script looks for an already-built binary under
`telegram-bot-api-src/` from a previous run. If it finds one, it asks whether to
reuse it instead of rebuilding from scratch (which is the slow part, often
10-30+ minutes). Say no if you suspect that build is broken or outdated.

### Memory-safe parallel builds (avoiding OOM kills)

tdlib's C++ translation units are memory-heavy -- roughly 1.5-2 GB of RAM **per
parallel compiler job**, more during the final linking steps. Blindly compiling
with one job per CPU core (`-j$(nproc)`) on a small VPS can trigger the kernel's
OOM killer, which can kill the compiler, this script, or even your whole SSH
session.

To avoid that, the script:

- Reads `MemTotal` + `SwapTotal` from `/proc/meminfo` and computes a safe number of
  parallel jobs: roughly `(RAM + swap in MB) / 2048`, capped at your CPU core count
  and never less than 1.
- If total RAM+swap is under ~2 GB, it warns you and offers to create a temporary
  2 GB swap file (`/swapfile-yt-telegrambot-build`) via `fallocate`/`dd` + `mkswap`
  + `swapon` before building. You can remove it again afterwards with:
  ```bash
  sudo swapoff /swapfile-yt-telegrambot-build
  sudo rm /swapfile-yt-telegrambot-build
  ```
- Always lets you override the computed number of jobs at the prompt -- lower is
  slower but safer.

**If a build still gets killed:** re-run the script, reuse the existing source
(it won't re-clone), and pick a lower job count (even `1`) at the prompt, or add
more swap manually first. `dmesg | grep -i oom` will confirm whether the kernel's
OOM killer was the cause.

### Live build progress

`cmake --build` prints `"[ XX%] Building ..."` lines as it compiles. The script
redraws just the percentage on a single line instead of either dumping thousands
of build lines to your terminal or going silent for the whole 10-30+ minutes. The
full, unfiltered build log is always kept at `/tmp/telegram-bot-api-build.log` for
debugging, and is also printed automatically (last 100 lines) if the build fails.

### Smoke test

A file that exists and is executable isn't necessarily a binary that actually
works -- a partial build, a bad link, or a build interrupted by the OOM killer can
leave something that passes those checks but is still broken. After a build (or
after choosing to reuse an existing one), the script runs:

```bash
telegram-bot-api --version
```

`--version` is a real `telegram-bot-api` flag that prints the version and exits
`0` without needing `--api-id`/`--api-hash`/`--local`, so it's a safe, fast way to
confirm the binary genuinely runs before it gets wired into systemd. If this fails,
the script stops and tells you to delete `telegram-bot-api-src/build` and re-run to
rebuild from a clean slate.

## Troubleshooting

- **The build killed my SSH session / "Killed" with no other error.** This is the
  OOM killer. Re-run the script (it reuses the already-cloned source), accept a
  lower parallel-job count when prompted, and/or accept the swap file offer. See
  "Memory-safe parallel builds" above.
- **The build failed with a compiler error.** Check
  `/tmp/telegram-bot-api-build.log` (also auto-printed on failure) for the actual
  error -- it's usually a missing build dependency. Re-running the package
  installation step (answer "yes" when asked) should resolve most of these.
- **It asked me for my bot token / api_id / api_hash again.** It shouldn't, as long
  as `.env` still has them and you didn't choose to "start it over from scratch"
  when asked. If it's asking again, check whether `.env` actually got written
  (`cat .env`, permissions `600`) -- a previous run that was killed before writing
  `.env` won't have persisted anything yet.
- **Package installation looks like it's doing nothing.** It isn't silent by
  accident -- full `apt`/`dnf`/`pacman` output is redirected to
  `/tmp/yt-telegrambot-packages.log` to keep the terminal readable. Tail that file
  if you want to watch it live, or check it after a failure (it's also
  auto-printed on failure).
- **"Missing: ..." after the package step.** Some required tool still isn't on
  `PATH` even after installation (or you chose to skip installation). Install it
  manually for your distro, or re-run the script and let it install packages.
- **The bot can't upload files over 50 MB even with the local server built.**
  Check that `BOT_API_BASE_URL` and `BOT_API_LOCAL_MODE=true` are actually set in
  `.env` (the script sets both automatically after a successful build), and that
  `telegram-bot-api.service` is running (`sudo systemctl status telegram-bot-api`).
- **Re-running after any interruption.** Just run `./scripts/setup.sh` again. Every
  step is designed to pick up where it left off: packages are idempotent, `.env` is
  only filled in where it's blank, an existing build is offered for reuse, and
  systemd units are safe to rewrite.

## systemd usage

Once installed, the usual commands apply:

```bash
sudo systemctl status yt-telegrambot
sudo journalctl -u yt-telegrambot -f

# only if the local Bot API server was built:
sudo systemctl status telegram-bot-api
sudo journalctl -u telegram-bot-api -f
```

Both services are configured with `Restart=on-failure` and run as the system user
you chose during setup. To stop automatic startup, use
`sudo systemctl disable --now yt-telegrambot` (and `telegram-bot-api` if applicable).

## Admin CLI: `database/dbcli.py`

A command-line tool for managing users and the song cache directly against the
live SQLite databases, without going through Telegram. Run it from the repo
root; `python3 database/dbcli.py --help` lists every command with its options.

```bash
python3 database/dbcli.py list                           # every user
python3 database/dbcli.py info <telegram_id>
python3 database/dbcli.py grant <telegram_id> premium --days 30   # or admin / subscribed
python3 database/dbcli.py admin <telegram_id>             # admin, no expiry
python3 database/dbcli.py revoke <telegram_id>            # back to free tier
python3 database/dbcli.py delete-user <telegram_id>
python3 database/dbcli.py reset-quota <telegram_id>       # force today's count to 0
python3 database/dbcli.py payments [telegram_id]
python3 database/dbcli.py refund <charge_id>              # DB bookkeeping only, not a real Telegram refund
python3 database/dbcli.py stats
python3 database/dbcli.py songs                           # list cached songs
python3 database/dbcli.py clear-songs --restart           # wipe the ENTIRE song cache
```

`clear-songs` deletes every row in `idSongs.db`'s `songs` table **and** every
cached audio file under `Songs/` -- useful after a change to how songs are
encoded or named (like the FLAC/filename fixes above), so old cached files get
regenerated with the new behavior instead of being served stale from before the
fix. It asks for a typed `DELETE` confirmation unless you pass `-y`/`--yes`, and
`--restart` restarts `yt-telegrambot.service` afterward (not required for the
clear itself to take effect -- the bot reads the database fresh on every
request -- but convenient to do in one command).
