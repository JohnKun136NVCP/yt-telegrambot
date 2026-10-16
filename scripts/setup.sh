#!/usr/bin/env bash
#
# scripts/setup.sh -- autoconfiguration for yt-telegrambot on a plain Linux
# terminal (no Docker).
#
# What it does, in order:
#   1. Installs system packages (ffmpeg + build tools) with the distro's
#      package manager (apt/dnf/pacman).
#   2. Creates a Python virtualenv and installs requirements.txt.
#   3. Asks for TOKEN / ADMIN_IDS / plan prices / limits and writes a
#      chmod-600 .env file (never overwritten silently -- if one already
#      exists you're asked whether to start it over from scratch; either
#      way, every value that is still missing or blank afterwards gets
#      asked for, so a half-filled .env from a previous run gets completed
#      instead of silently shipping a blank TOKEN).
#   4. Creates the runtime directories the bot expects (logs, database,
#      Songs, img, thumbimg).
#   5. Optionally builds Telegram's official local Bot API server
#      (tdlib/telegram-bot-api) from source, which is the only way this
#      bot can ever send/receive files over 50 MB -- Telegram's cloud API
#      hard-caps uploads at 50 MB no matter what the bot does. If a build
#      from an earlier run is found, you're asked whether to reuse it
#      instead of rebuilding; the compile step itself shows a live "[ XX%]"
#      progress readout instead of going silent for several minutes.
#   6. Writes systemd units for the bot and (if built) the local Bot API
#      server, both running as the SAME system user so the bot's
#      file://-based fast upload path can read the files the local server
#      writes to disk.
#
# Safe to re-run: every step asks before overwriting something it already
# created, and installation steps are idempotent.
#
# Usage:
#   ./scripts/setup.sh                 interactive
#   ./scripts/setup.sh --non-interactive   accept every default, skip
#                                           the local Bot API server build,
#                                           and skip systemd (prints the
#                                           unit files instead of installing
#                                           them) -- useful in CI.

set -euo pipefail

# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

NON_INTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --non-interactive|-y) NON_INTERACTIVE=1 ;;
        --help|-h)
            sed -n '2,32p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (see --help)" >&2
            exit 1
            ;;
    esac
done

BOLD="$(tput bold 2>/dev/null || true)"
DIM="$(tput dim 2>/dev/null || true)"
RED="$(tput setaf 1 2>/dev/null || true)"
GREEN="$(tput setaf 2 2>/dev/null || true)"
YELLOW="$(tput setaf 3 2>/dev/null || true)"
RESET="$(tput sgr0 2>/dev/null || true)"

info()  { printf '%s[*]%s %s\n' "$GREEN" "$RESET" "$1"; }
warn()  { printf '%s[!]%s %s\n' "$YELLOW" "$RESET" "$1"; }
fail()  { printf '%s[x]%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }
step()  { printf '\n%s==>%s %s%s%s\n' "$BOLD" "$RESET" "$BOLD" "$1" "$RESET"; }

ask() {
    # ask <prompt> <default> -> echoes the answer
    local prompt="$1" default="$2" answer
    if [ "$NON_INTERACTIVE" = "1" ]; then
        echo "$default"
        return
    fi
    read -r -p "$prompt [$default]: " answer || true
    echo "${answer:-$default}"
}

ask_secret() {
    # ask_secret <prompt> -> echoes the answer, input not echoed to the tty
    local prompt="$1" answer
    if [ "$NON_INTERACTIVE" = "1" ]; then
        echo ""
        return
    fi
    read -r -s -p "$prompt: " answer || true
    echo "" >&2
    echo "$answer"
}

confirm() {
    # confirm <prompt> [default y|N] -> returns 0/1
    local prompt="$1" default="${2:-n}" answer
    if [ "$NON_INTERACTIVE" = "1" ]; then
        [ "$default" = "y" ] && return 0 || return 1
    fi
    local hint="y/N"; [ "$default" = "y" ] && hint="Y/n"
    read -r -p "$prompt [$hint]: " answer || true
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy] ]]
}

# --- .env helpers ------------------------------------------------------------
# These read/write $ENV_FILE directly (instead of only building it once from
# a batch of prompts) so an existing .env from a previous run can be
# completed in place: already-set values are left untouched, only missing or
# blank ones trigger a prompt.

env_get() {
    # env_get <key> -> current value in $ENV_FILE, or "" if missing/blank
    grep -m1 "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true
}

env_set() {
    # env_set <key> <value> -> update the key in $ENV_FILE in place,
    # appending it if it isn't there yet.
    local key="$1" value="$2" escaped
    escaped="${value//&/\\&}"
    escaped="${escaped//#/\\#}"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s#^${key}=.*#${key}=${escaped}#" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

prompt_if_empty() {
    # prompt_if_empty <key> <prompt> <default> [secret:0/1] [required:0/1] [hint]
    #
    # Only prompts (and only then prints <hint>, if given) when <key> is
    # currently missing or blank in $ENV_FILE -- an already-filled value from
    # a previous run is left exactly as it is.
    local key="$1" prompt="$2" default="$3" secret="${4:-0}" required="${5:-0}" hint="${6:-}"
    local current value

    current="$(env_get "$key")"
    [ -n "$current" ] && return

    [ -n "$hint" ] && echo && echo "$hint"

    if [ "$secret" = "1" ]; then
        value="$(ask_secret "$prompt")"
    else
        value="$(ask "$prompt" "$default")"
    fi

    if [ "$required" = "1" ]; then
        while [ "$NON_INTERACTIVE" = "0" ] && [ -z "$value" ]; do
            warn "$key cannot be empty."
            if [ "$secret" = "1" ]; then
                value="$(ask_secret "$prompt")"
            else
                value="$(ask "$prompt" "$default")"
            fi
        done
    else
        value="${value:-$default}"
    fi

    env_set "$key" "$value"
}

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
    warn "Running as root. The bot process itself should not run as root; you'll be asked which system user to run it as in the systemd step below."
else
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        SUDO=""
        warn "sudo not found; package installation and systemd steps may fail" \
             "without root."
    fi
fi

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------

step "Installing system packages"

PKGS_COMMON="ffmpeg git curl ca-certificates"
PKGS_BUILD="cmake g++ make gperf zlib1g-dev libssl-dev"      # Debian/Ubuntu names
PKGS_BUILD_RPM="cmake gcc-c++ make gperf zlib-devel openssl-devel"  # Fedora/RHEL names

if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
    $SUDO apt-get update -y
    # shellcheck disable=SC2086
    $SUDO apt-get install -y python3 python3-venv python3-pip $PKGS_COMMON $PKGS_BUILD
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
    # shellcheck disable=SC2086
    $SUDO dnf install -y python3 python3-pip python3-virtualenv $PKGS_COMMON $PKGS_BUILD_RPM
elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
    # shellcheck disable=SC2086
    $SUDO pacman -Sy --needed --noconfirm python python-pip ffmpeg git curl cmake gcc make gperf zlib openssl
else
    PKG_MANAGER=""
    warn "No supported package manager found (looked for apt-get/dnf/pacman)."
    warn "Install manually: python3, python3-venv, pip, ffmpeg, git, cmake, a C++ compiler, gperf, zlib and OpenSSL dev headers."
    if ! confirm "Continue anyway?" n; then
        exit 1
    fi
fi

command -v ffmpeg >/dev/null 2>&1 || warn "ffmpeg still not on PATH -- audio conversion will fail until it is installed."

# ---------------------------------------------------------------------------
# 2. Python virtualenv
# ---------------------------------------------------------------------------

step "Setting up the Python virtual environment"

VENV_DIR="$REPO_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    info "Created virtualenv at $VENV_DIR"
else
    info "Virtualenv already exists at $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet
pip install -r requirements.txt
deactivate
info "Dependencies installed into $VENV_DIR"

# ---------------------------------------------------------------------------
# 3. Runtime directories
# ---------------------------------------------------------------------------

step "Creating runtime directories"

for d in logs database Songs img thumbimg; do
    mkdir -p "$REPO_DIR/$d"
done
info "Created logs/ database/ Songs/ img/ thumbimg/"

# ---------------------------------------------------------------------------
# 4. .env
# ---------------------------------------------------------------------------

step "Configuring .env"

ENV_FILE="$REPO_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    info "Found an existing .env at $ENV_FILE."
    if confirm "Start it over from scratch (every value blank again)?" n; then
        cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)"
        info "Backed up the existing .env before overwriting."
        rm -f "$ENV_FILE"
    else
        info "Keeping it -- checking for missing or blank values next."
    fi
fi

if [ ! -f "$ENV_FILE" ]; then
    # Every key present but blank, so env_get/env_set (and prompt_if_empty
    # below) have a single, predictable file to work against from here on.
    # Local Bot API server values are filled in later (section 5) if the
    # user chooses to build it; left blank here means "use Telegram's cloud
    # API", which is a fully working, 50 MB-capped default.
    cat > "$ENV_FILE" <<EOF
# Generated by scripts/setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Keep this file secret -- it holds your bot token. Permissions are set to
# 600 (owner read/write only) right after this script writes it.

# --- Required ---------------------------------------------------------------
TOKEN=
ADMIN_IDS=

# --- File size tiers ---------------------------------------------------------
STANDARD_MAX_MB=
PREMIUM_MAX_MB=

# --- Download queue -----------------------------------------------------------
QUEUE_MAX_SIZE=
QUEUE_WORKERS=
JOB_TIMEOUT_SECONDS=
MIN_SECONDS_BETWEEN_REQUESTS=

# --- Telegram Stars plans (code:label:days:stars,...; blank = defaults) ------
STAR_PLANS=

# --- Local Bot API server (filled in automatically if you build it below) ---
BOT_API_BASE_URL=
BOT_API_LOCAL_MODE=false
EOF
    chmod 600 "$ENV_FILE"
fi

# Every call below is a no-op for a key that already has a non-blank value
# (from an earlier run, or from the file just written above) -- only a
# missing/blank one is actually prompted for. TOKEN is the only value the
# bot cannot start without, so it's the only one that loops until non-empty.
prompt_if_empty TOKEN "Bot TOKEN" "" 1 1 \
    "Get a bot token from @BotFather on Telegram (the 'New Bot' flow)."

prompt_if_empty ADMIN_IDS "ADMIN_IDS" "" 0 0 \
    "Telegram user IDs (comma-separated) that should have admin access (/grant, /revoke, /refund, /stats). Get your own id from @userinfobot."

prompt_if_empty STANDARD_MAX_MB "STANDARD_MAX_MB (free/standard users)" "49.5" 0 0 \
    "File-size caps. Telegram's cloud API refuses uploads over 50 MB no matter what this bot sends, so STANDARD_MAX_MB should normally stay under that; PREMIUM_MAX_MB only takes effect if you set up the local Bot API server later in this script."
prompt_if_empty PREMIUM_MAX_MB "PREMIUM_MAX_MB (premium/admin users, local server only)" "1900"

prompt_if_empty QUEUE_MAX_SIZE "QUEUE_MAX_SIZE (jobs allowed to wait)" "50" 0 0 "Download queue."
prompt_if_empty QUEUE_WORKERS "QUEUE_WORKERS (concurrent downloads)" "2"
prompt_if_empty JOB_TIMEOUT_SECONDS "JOB_TIMEOUT_SECONDS (per-job hard timeout)" "1800"
prompt_if_empty MIN_SECONDS_BETWEEN_REQUESTS "MIN_SECONDS_BETWEEN_REQUESTS (per-user flood control)" "3"

prompt_if_empty STAR_PLANS "STAR_PLANS" "" 0 0 \
    "Telegram Stars subscription plans, format code:label:days:stars separated by commas. Leave empty to use the bundled defaults (1 week / 1 month / 1 year)."

chmod 600 "$ENV_FILE"
info "$ENV_FILE is ready (chmod 600)."

# ---------------------------------------------------------------------------
# 5. Optional: local Bot API server (only way past the 50 MB cloud cap)
# ---------------------------------------------------------------------------

step "Local Telegram Bot API server (optional, needed for files over 50 MB)"

BUILD_LOCAL_SERVER=0
LOCAL_SERVER_BIN=""

echo "Telegram's cloud Bot API refuses to upload/download files over 50 MB,"
echo "no matter what this bot sends. The only fix is running your own copy of"
echo "Telegram's official 'telegram-bot-api' server (https://github.com/tdlib/telegram-bot-api)"
echo "on this same machine, started with --local. Building it from source takes"
echo "real CPU/RAM (a few minutes on a modern machine, much longer on a small VPS)"
echo "and needs an api_id/api_hash pair from https://my.telegram.org/apps."
echo "Skip this if the 50 MB cloud limit is fine for your users."

if confirm "Build and configure the local Bot API server now?" n; then
    BUILD_LOCAL_SERVER=1

    API_ID="$(ask "Telegram api_id (from my.telegram.org/apps)" "")"
    API_HASH="$(ask_secret "Telegram api_hash (from my.telegram.org/apps)")"

    while [ "$NON_INTERACTIVE" = "0" ] && { [ -z "$API_ID" ] || [ -z "$API_HASH" ]; }; do
        warn "Both api_id and api_hash are required to run the local server."
        API_ID="$(ask "Telegram api_id" "$API_ID")"
        API_HASH="$(ask_secret "Telegram api_hash")"
    done

    BUILD_DIR="$REPO_DIR/telegram-bot-api-src"
    DATA_DIR="$REPO_DIR/bot-api-data"
    mkdir -p "$DATA_DIR"

    # `--target install` (below) installs into $BUILD_DIR/bin/telegram-bot-api
    # -- check there first so a previous run's build can be reused instead of
    # recompiling tdlib from scratch every single time (that's the slow part).
    EXISTING_BIN=""
    if [ -x "$BUILD_DIR/bin/telegram-bot-api" ]; then
        EXISTING_BIN="$BUILD_DIR/bin/telegram-bot-api"
    elif [ -d "$BUILD_DIR" ]; then
        EXISTING_BIN="$(find "$BUILD_DIR" -maxdepth 3 -type f -name telegram-bot-api -perm -u+x 2>/dev/null | head -n1)"
    fi

    if [ -n "$EXISTING_BIN" ] && confirm "Found an already-built telegram-bot-api at $EXISTING_BIN. Reuse it and skip rebuilding?" y; then
        LOCAL_SERVER_BIN="$EXISTING_BIN"
        info "Reusing the existing build at $LOCAL_SERVER_BIN."
    else
        if [ ! -d "$BUILD_DIR" ]; then
            info "Cloning tdlib/telegram-bot-api (this includes the td submodule, be patient)..."
            git clone --recursive https://github.com/tdlib/telegram-bot-api.git "$BUILD_DIR"
        else
            info "Source already present at $BUILD_DIR, reusing it."
        fi

        mkdir -p "$BUILD_DIR/build"
        (
            cd "$BUILD_DIR/build"
            info "Configuring build (cmake)..."
            # -DCMAKE_INSTALL_PREFIX:PATH=.. matches tdlib/telegram-bot-api's
            # own README exactly, so `--target install` below places the
            # binary at $BUILD_DIR/bin/telegram-bot-api (one level above
            # build/) instead of trying to write into /usr/local as root.
            cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX:PATH=.. .. >/tmp/telegram-bot-api-cmake.log 2>&1 \
                || { cat /tmp/telegram-bot-api-cmake.log; fail "cmake configure failed, see above."; }

            info "Building telegram-bot-api (this can take 10-30+ minutes)..."
            BUILD_LOG="/tmp/telegram-bot-api-build.log"
            : > "$BUILD_LOG"
            # `cmake --build` (Makefiles generator, the default) prints
            # "[ XX%] Building ..." lines as it goes -- pull just the
            # percentage out of those and redraw it on one line instead of
            # either dumping thousands of build lines or going silent for
            # the whole 10-30+ minutes. Full output still goes to $BUILD_LOG
            # for debugging. The `if ! pipeline; then` form (rather than
            # `pipeline || { ...; }`) is required so a failing cmake doesn't
            # trip `set -e` before the progress bar's trailing newline and
            # the log tail below get a chance to run.
            if ! cmake --build . --target install -- -j"$(nproc)" 2>&1 \
                    | tee "$BUILD_LOG" \
                    | while IFS= read -r line; do
                          if [[ "$line" =~ ^\[[[:space:]]*([0-9]+)%\] ]]; then
                              printf '\r    Building telegram-bot-api... %3s%%' "${BASH_REMATCH[1]}"
                          fi
                      done
            then
                echo
                tail -n 100 "$BUILD_LOG"
                fail "Build failed, see $BUILD_LOG"
            fi
            echo
        )

        CANDIDATE="$BUILD_DIR/bin/telegram-bot-api"
        if [ ! -x "$CANDIDATE" ]; then
            CANDIDATE="$(find "$BUILD_DIR" -maxdepth 3 -type f -name telegram-bot-api -perm -u+x | head -n1)"
        fi
        [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ] || fail "Could not locate the built telegram-bot-api binary."
        LOCAL_SERVER_BIN="$CANDIDATE"
        info "Built telegram-bot-api at $LOCAL_SERVER_BIN"
    fi

    LOCAL_SERVER_PORT="$(ask "Local Bot API HTTP port" "8081")"

    # Point the bot at the local server and turn on file://-based uploads.
    env_set BOT_API_BASE_URL "http://127.0.0.1:$LOCAL_SERVER_PORT"
    env_set BOT_API_LOCAL_MODE "true"
    chmod 600 "$ENV_FILE"
    info "Updated $ENV_FILE to use the local Bot API server."
else
    info "Skipping the local Bot API server. STANDARD_MAX_MB stays the effective cap for everyone (see src/config.py: effective_premium_max_mb())."
fi

# ---------------------------------------------------------------------------
# 6. systemd units
# ---------------------------------------------------------------------------

step "systemd services"

if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found; skipping service setup. Run the bot manually with:"
    warn "  source .venv/bin/activate && python3 main.py"
else
    if confirm "Install systemd services (bot$( [ "$BUILD_LOCAL_SERVER" = "1" ] && echo " + local Bot API server" ))?" y; then
        RUN_USER="$(ask "System user to run the service(s) as" "${SUDO_USER:-$(whoami)}")"

        if ! id "$RUN_USER" >/dev/null 2>&1; then
            fail "User '$RUN_USER' does not exist. Create it first (e.g. 'sudo useradd -m $RUN_USER') and re-run."
        fi

        # Both units run as the same user ON PURPOSE: the bot's local-file
        # upload path hands telegram-bot-api a plain filesystem path
        # (file://...) instead of streaming the bytes itself, which only
        # works if both processes can read/write the same files.
        BOT_UNIT="/etc/systemd/system/yt-telegrambot.service"
        cat <<EOF | $SUDO tee "$BOT_UNIT" >/dev/null
[Unit]
Description=yt-telegrambot (Telegram YouTube-audio bot)
After=network-online.target $( [ "$BUILD_LOCAL_SERVER" = "1" ] && echo "telegram-bot-api.service")
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/python3 $REPO_DIR/main.py
Restart=on-failure
RestartSec=5
# Hardening (kept loose enough that ffmpeg and yt-dlp/pytubefix still work).
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
        info "Wrote $BOT_UNIT"

        if [ "$BUILD_LOCAL_SERVER" = "1" ]; then
            API_UNIT="/etc/systemd/system/telegram-bot-api.service"
            cat <<EOF | $SUDO tee "$API_UNIT" >/dev/null
[Unit]
Description=Telegram local Bot API server (tdlib/telegram-bot-api)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$DATA_DIR
ExecStart=$LOCAL_SERVER_BIN --local --api-id=$API_ID --api-hash=$API_HASH --dir=$DATA_DIR --http-port=$LOCAL_SERVER_PORT
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
            info "Wrote $API_UNIT"
            $SUDO chown -R "$RUN_USER" "$DATA_DIR"
        fi

        $SUDO chown "$RUN_USER" "$ENV_FILE" || true
        $SUDO chmod 600 "$ENV_FILE" || true

        $SUDO systemctl daemon-reload

        if [ "$BUILD_LOCAL_SERVER" = "1" ]; then
            $SUDO systemctl enable --now telegram-bot-api.service
            info "Started telegram-bot-api.service -- waiting a moment for it to come up..."
            sleep 2
            $SUDO systemctl --no-pager status telegram-bot-api.service || true
        fi

        $SUDO systemctl enable --now yt-telegrambot.service
        info "Started yt-telegrambot.service"
        $SUDO systemctl --no-pager status yt-telegrambot.service || true

        echo
        info "Useful commands:"
        echo "    sudo systemctl status yt-telegrambot"
        echo "    sudo journalctl -u yt-telegrambot -f"
        [ "$BUILD_LOCAL_SERVER" = "1" ] && echo "    sudo journalctl -u telegram-bot-api -f"
    else
        info "Skipped systemd setup. Start the bot manually with:"
        echo "    source .venv/bin/activate && python3 main.py"
    fi
fi

step "Done"
echo "Configuration file: $ENV_FILE (chmod 600)"
echo "Virtualenv:         $VENV_DIR"
[ "$BUILD_LOCAL_SERVER" = "1" ] && echo "Local Bot API:       $LOCAL_SERVER_BIN (port ${LOCAL_SERVER_PORT:-8081})"
echo
echo "Admin-only bot commands once it's running: /grant, /revoke, /refund, /stats"
