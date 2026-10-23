#!/usr/bin/env bash
#
# scripts/update.sh -- pull the latest code and restart the running
# services, in one command. This is the lightweight day-to-day deploy
# step; for first-time setup, changing .env, installing system packages,
# or building the local Bot API server, use scripts/setup.sh instead --
# this script never touches any of that.
#
# What it does, in order:
#   1. Refuses to pull over uncommitted local changes (asks first in
#      interactive mode; just aborts in --non-interactive mode) so a
#      manual edit on the server is never silently clobbered.
#   2. `git pull --ff-only` on whatever branch is currently checked out.
#      A fast-forward-only pull never creates a merge commit or rewrites
#      history; if it can't fast-forward (local commits that aren't on
#      the remote), it stops and tells you instead of guessing.
#   3. Reinstalls Python dependencies ONLY if requirements.txt actually
#      changed in the pulled commits, so most updates skip this step.
#   4. Restarts yt-telegrambot.service (and telegram-bot-api.service too,
#      if that unit exists) via systemd, with sudo if needed.
#
# Usage:
#   ./scripts/update.sh                 interactive
#   ./scripts/update.sh --non-interactive, -y
#                                        don't ask about local changes --
#                                        just abort if there are any
#   ./scripts/update.sh --skip-deps     skip reinstalling dependencies
#                                        even if requirements.txt changed

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

NON_INTERACTIVE=0
SKIP_DEPS=0
for arg in "$@"; do
    case "$arg" in
        --non-interactive|-y) NON_INTERACTIVE=1 ;;
        --skip-deps) SKIP_DEPS=1 ;;
        --help|-h)
            sed -n '2,28p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (see --help)" >&2
            exit 1
            ;;
    esac
done

BOLD="$(tput bold 2>/dev/null || true)"
RED="$(tput setaf 1 2>/dev/null || true)"
GREEN="$(tput setaf 2 2>/dev/null || true)"
YELLOW="$(tput setaf 3 2>/dev/null || true)"
RESET="$(tput sgr0 2>/dev/null || true)"

info()  { printf '%s[*]%s %s\n' "$GREEN" "$RESET" "$1"; }
warn()  { printf '%s[!]%s %s\n' "$YELLOW" "$RESET" "$1"; }
fail()  { printf '%s[x]%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }
step()  { printf '\n%s==>%s %s%s%s\n' "$BOLD" "$RESET" "$BOLD" "$1" "$RESET"; }

confirm() {
    local prompt="$1" default="${2:-n}" answer
    if [ "$NON_INTERACTIVE" = "1" ]; then
        [ "$default" = "y" ] && return 0 || return 1
    fi
    local hint="y/N"; [ "$default" = "y" ] && hint="Y/n"
    read -r -p "$prompt [$hint]: " answer || true
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy] ]]
}

if ! command -v git >/dev/null 2>&1 || [ ! -d "$REPO_DIR/.git" ]; then
    fail "This isn't a git checkout -- can't pull. Clone the repo with git to use this script."
fi

# ---------------------------------------------------------------------------
# 1. Refuse to pull over uncommitted local changes
# ---------------------------------------------------------------------------

step "Checking for local changes"

if [ -n "$(git status --porcelain)" ]; then
    warn "You have uncommitted local changes:"
    git status --short
    echo

    if [ "$NON_INTERACTIVE" = "1" ]; then
        fail "Refusing to pull over local changes in --non-interactive mode. Commit, stash, or discard them first."
    fi

    if ! confirm "Pull anyway? This can create merge conflicts in your working copy." n; then
        fail "Aborted. Commit or stash your changes first (e.g. 'git stash')."
    fi
else
    info "Working copy is clean."
fi

# ---------------------------------------------------------------------------
# 2. Pull (fast-forward only)
# ---------------------------------------------------------------------------

step "Pulling the latest changes"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BEFORE="$(git rev-parse HEAD)"

info "Branch: $BRANCH"
git fetch origin "$BRANCH"

if ! git merge --ff-only "origin/$BRANCH"; then
    fail "Can't fast-forward -- your branch has commits the remote doesn't (or has diverged). Resolve this manually (e.g. 'git log --oneline origin/$BRANCH..HEAD', then rebase or merge yourself) and re-run."
fi

AFTER="$(git rev-parse HEAD)"

if [ "$BEFORE" = "$AFTER" ]; then
    info "Already up to date -- nothing new to deploy."
    UPDATED=0
else
    COMMIT_COUNT="$(git rev-list --count "$BEFORE..$AFTER")"
    info "Updated $BRANCH: $COMMIT_COUNT new commit(s)."
    git log --oneline "$BEFORE..$AFTER"
    UPDATED=1
fi

# ---------------------------------------------------------------------------
# 3. Python dependencies (only if requirements.txt changed)
# ---------------------------------------------------------------------------

step "Python dependencies"

VENV_DIR="$REPO_DIR/.venv"

if [ "$UPDATED" = "0" ]; then
    info "No new commits -- nothing to reinstall."
elif [ "$SKIP_DEPS" = "1" ]; then
    info "Skipped (--skip-deps)."
elif ! git diff --name-only "$BEFORE" "$AFTER" | grep -qx "requirements.txt"; then
    info "requirements.txt unchanged -- nothing to reinstall."
elif [ ! -d "$VENV_DIR" ]; then
    warn "requirements.txt changed, but no virtualenv found at $VENV_DIR -- run scripts/setup.sh first, or install the new dependencies manually."
else
    info "requirements.txt changed -- reinstalling..."
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt --quiet
    deactivate
    info "Dependencies updated."
fi

# ---------------------------------------------------------------------------
# 4. Restart services
# ---------------------------------------------------------------------------

step "Restarting services"

if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found. If you're running the bot manually, stop it and restart with:"
    warn "  source .venv/bin/activate && python3 main.py"
else
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        SUDO=""
    fi

    if systemctl list-unit-files 2>/dev/null | grep -q '^yt-telegrambot\.service'; then
        $SUDO systemctl restart yt-telegrambot
        info "Restarted yt-telegrambot.service"

        if systemctl list-unit-files 2>/dev/null | grep -q '^telegram-bot-api\.service'; then
            $SUDO systemctl restart telegram-bot-api
            info "Restarted telegram-bot-api.service"
        fi

        sleep 2
        $SUDO systemctl --no-pager status yt-telegrambot || true
    else
        warn "yt-telegrambot.service isn't installed (run scripts/setup.sh's systemd step, or start the bot manually):"
        warn "  source .venv/bin/activate && python3 main.py"
    fi
fi

step "Done"
