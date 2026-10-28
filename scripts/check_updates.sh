#!/usr/bin/env bash
#
# scripts/check_updates.sh -- look for known-vulnerable dependencies (via
# pip-audit, which checks packages against the PyPI Advisory Database / OSV)
# and only apply a fix if it installs cleanly AND imports cleanly in a
# disposable, throwaway environment first. Nothing real is ever touched
# unless that check passes.
#
# This never guesses version numbers itself: pip-audit's own database is
# what decides which version fixes a given vulnerability. If the proposed
# fix fails to install, or anything fails to import afterwards, nothing is
# changed and nothing is restarted -- the script just reports what broke.
#
# What it does, in order:
#   1. Builds a throwaway virtualenv (always deleted afterwards, win or
#      lose) and installs pip-audit into it. This never touches the
#      project's real .venv.
#   2. Scans requirements.txt for known vulnerabilities. If there are none,
#      it says so and stops -- nothing else happens.
#   3. If there are, copies requirements.txt to a scratch file and lets
#      pip-audit fix *that copy* (never the real file yet).
#   4. Builds a SECOND throwaway virtualenv and tries to install the
#      scratch copy into it from nothing.
#        - If that install fails because the bumped package needs a newer
#          version of some OTHER pinned package (e.g. a newer aiohttp
#          needing a newer yarl than requirements.txt has pinned), it
#          retries once with every pin in the scratch copy relaxed to a
#          floor ("X>=version" instead of "X==version") and lets pip's own
#          resolver pick a mutually-compatible set -- nothing is allowed to
#          go *below* the version it already had (or the fixed version
#          pip-audit asked for), only to move up as far as needed. Whatever
#          pip actually resolves is then re-pinned exactly, in the original
#          file's order, keeping comments and extras like "[job-queue]".
#        - If even that can't find a working combination, nothing is
#          changed; it tells you exactly which packages are in conflict so
#          you can resolve it by hand.
#   5. Smoke-tests the install that *did* work: every third-party package
#      in it must import cleanly, and so must this project's own modules
#      that directly use the packages being bumped (src/security.py,
#      src/yb/meta.py, src/yb/songs.py, src/uploader.py,
#      database/databases.py).
#   6. Only if that smoke test passes: copies the final, tested candidate
#      over the real requirements.txt, reinstalls the real .venv from it,
#      and restarts the running service(s) -- the same restart step
#      scripts/update.sh uses.
#   7. If anything in steps 3-5 fails: prints exactly what broke, leaves
#      requirements.txt and the real .venv exactly as they were, and exits
#      non-zero. Nothing is restarted.
#
# This script only ever changes requirements.txt and the local .venv on
# THIS machine -- it does not touch git, commit, or push anything. If you
# want the fix to also land in the repository, commit requirements.txt
# yourself after a successful run.
#
# Usage:
#   ./scripts/check_updates.sh                 interactive: shows the
#                                               proposed change and asks
#                                               before applying it
#   ./scripts/check_updates.sh --non-interactive, -y
#                                               apply automatically, but
#                                               ONLY if the smoke test
#                                               passes -- safe to put in
#                                               cron for unattended runs
#   ./scripts/check_updates.sh --report-only    just scan and show what's
#                                               vulnerable; never install,
#                                               change, or restart anything
#
# Exit codes: 0 = nothing vulnerable (or fix applied successfully),
#             1 = vulnerabilities found but not fixed (--report-only, or
#                 declined at the confirmation prompt),
#             2 = a fix was attempted but failed the install/smoke test,
#                 or a prerequisite (venv, pip-audit) was missing.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

NON_INTERACTIVE=0
REPORT_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --non-interactive|-y) NON_INTERACTIVE=1 ;;
        --report-only) REPORT_ONLY=1 ;;
        --help|-h)
            sed -n '2,72p' "${BASH_SOURCE[0]}"
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
fail()  { printf '%s[x]%s %s\n' "$RED" "$RESET" "$1" >&2; }
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

if [ ! -f "$REPO_DIR/requirements.txt" ]; then
    fail "requirements.txt not found at $REPO_DIR -- is this the repo root?"
    exit 2
fi

REAL_VENV="$REPO_DIR/.venv"
if [ ! -d "$REAL_VENV" ]; then
    fail "No virtualenv found at $REAL_VENV -- run scripts/setup.sh first."
    exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found on PATH."
    exit 2
fi

AUDIT_TMP="$(mktemp -d -t yt-telegrambot-audit.XXXXXX)"
cleanup() { rm -rf "$AUDIT_TMP"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Throwaway venv just for pip-audit itself
# ---------------------------------------------------------------------------

step "Setting up a throwaway environment for pip-audit"

python3 -m venv "$AUDIT_TMP/audit-venv"
AUDIT_PY="$AUDIT_TMP/audit-venv/bin/python"
AUDIT_PIP_AUDIT="$AUDIT_TMP/audit-venv/bin/pip-audit"

if ! "$AUDIT_PY" -m pip install --quiet --upgrade pip pip-audit; then
    fail "Could not install pip-audit (no network access, or pypi.org unreachable from here)."
    exit 2
fi

# ---------------------------------------------------------------------------
# 2. Scan the real requirements.txt
# ---------------------------------------------------------------------------

step "Scanning requirements.txt for known vulnerabilities"

set +e
"$AUDIT_PIP_AUDIT" -r "$REPO_DIR/requirements.txt"
SCAN_STATUS=$?
set -e

if [ "$SCAN_STATUS" -eq 0 ]; then
    info "No known vulnerabilities found. Nothing to do."
    exit 0
fi

warn "One or more pinned dependencies have known vulnerabilities (see above)."

if [ "$REPORT_ONLY" = "1" ]; then
    info "Report-only mode -- not installing or changing anything."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Let pip-audit propose a fix, on a SCRATCH COPY only
# ---------------------------------------------------------------------------

step "Computing a candidate fix (on a scratch copy -- requirements.txt is untouched so far)"

CANDIDATE="$AUDIT_TMP/requirements.candidate.txt"
cp "$REPO_DIR/requirements.txt" "$CANDIDATE"

set +e
"$AUDIT_PIP_AUDIT" -r "$CANDIDATE" --fix
FIX_STATUS=$?
set -e

if diff -q "$REPO_DIR/requirements.txt" "$CANDIDATE" >/dev/null 2>&1; then
    warn "pip-audit could not find a safe version for every flagged package (see output above)."
    warn "Nothing was changed. Fix the remaining package(s) manually and re-run."
    exit 2
fi

# ---------------------------------------------------------------------------
# 4. Install the candidate into a SECOND throwaway venv, from nothing.
#    If the literal bump conflicts with another pinned package, retry once
#    with every pin relaxed to a floor and let pip's resolver reconcile
#    them -- then re-pin whatever it actually chose.
# ---------------------------------------------------------------------------

step "Test-installing the candidate in a disposable environment"

python3 -m venv "$AUDIT_TMP/test-venv"
TEST_PY="$AUDIT_TMP/test-venv/bin/python"

if ! "$TEST_PY" -m pip install --quiet --upgrade pip >/dev/null; then
    fail "Could not bootstrap the disposable test environment."
    exit 2
fi

set +e
"$TEST_PY" -m pip install --quiet -r "$CANDIDATE"
INSTALL_STATUS=$?
set -e

if [ "$INSTALL_STATUS" -ne 0 ]; then
    warn "That exact version combination doesn't install -- it conflicts with another pinned package."
    step "Retrying with a mutually-compatible set of versions"

    # Relax every pin to a floor ("X>=version" instead of "X==version") so
    # pip's resolver can raise whatever else it needs to -- it can only
    # move versions UP from here, never below what was already pinned (or
    # below the fixed version pip-audit just chose for the flagged
    # package), so this can't silently reintroduce the vulnerability.
    FLOOR_CANDIDATE="$AUDIT_TMP/requirements.floor.txt"
    sed 's/==/>=/' "$CANDIDATE" > "$FLOOR_CANDIDATE"

    rm -rf "$AUDIT_TMP/test-venv"
    python3 -m venv "$AUDIT_TMP/test-venv"
    TEST_PY="$AUDIT_TMP/test-venv/bin/python"
    "$TEST_PY" -m pip install --quiet --upgrade pip >/dev/null

    if ! "$TEST_PY" -m pip install --quiet -r "$FLOOR_CANDIDATE"; then
        fail "No mutually-compatible set of versions was found automatically."
        warn "Nothing was changed. The real requirements.txt and .venv are untouched."
        warn "This needs a manual look: the vulnerable package's fixed version"
        warn "conflicts with another dependency's own requirements."
        exit 2
    fi

    # Pin down exactly what the resolver chose, in the ORIGINAL file's
    # order, keeping its comments, blank lines, and extras like
    # "[job-queue]" -- only the version numbers change.
    FREEZE="$AUDIT_TMP/freeze.txt"
    "$TEST_PY" -m pip freeze --local > "$FREEZE"

    RESOLVED="$AUDIT_TMP/requirements.resolved.txt"
    cat > "$AUDIT_TMP/pin_resolved.py" <<'PYEOF'
import re
import sys

original_path, freeze_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


resolved = {}
with open(freeze_path, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        resolved[normalize(name)] = version

out_lines = []
with open(original_path, encoding="utf-8") as handle:
    for raw_line in handle:
        stripped = raw_line.rstrip("\n")
        body = stripped.split("#", 1)[0].strip()
        if not body or "==" not in body:
            out_lines.append(stripped)
            continue
        name_and_extras = body.split("==", 1)[0]
        bare_name = re.split(r"[\[;]", name_and_extras, maxsplit=1)[0].strip()
        key = normalize(bare_name)
        if key not in resolved:
            out_lines.append(stripped)  # not actually installed; keep as-is
            continue
        out_lines.append(f"{name_and_extras.strip()}=={resolved[key]}")

with open(output_path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(out_lines) + "\n")
PYEOF

    if ! "$TEST_PY" "$AUDIT_TMP/pin_resolved.py" "$REPO_DIR/requirements.txt" "$FREEZE" "$RESOLVED"; then
        fail "Could not reconstruct a pinned requirements.txt from the resolved environment."
        exit 2
    fi

    CANDIDATE="$RESOLVED"
    info "Found a mutually-compatible set of versions."
fi

info "Proposed change:"
diff -u "$REPO_DIR/requirements.txt" "$CANDIDATE" || true

# ---------------------------------------------------------------------------
# 5. Smoke-test: every package must import, and so must the project's own
#    modules that directly use the packages being bumped.
# ---------------------------------------------------------------------------

step "Smoke-testing the candidate (import check)"

SMOKE_SCRIPT="$AUDIT_TMP/smoke_test.py"
cat > "$SMOKE_SCRIPT" <<'PYEOF'
import importlib
import re
import sys

requirements_path, repo_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo_dir)

# requirements.txt package name -> the name you actually `import`, for the
# cases where they differ. Anything not listed here is assumed to match
# (lowercased, dashes -> underscores).
IMPORT_NAME_OVERRIDES = {
    "opencv-python": "cv2",
    "python-telegram-bot": "telegram",
    "python-dotenv": "dotenv",
    "apscheduler": "apscheduler",
    "charset-normalizer": "charset_normalizer",
    "nodejs-wheel-binaries": None,  # a CLI/binary wrapper, not an importable API
}

failures = []

with open(requirements_path, encoding="utf-8") as handle:
    for raw_line in handle:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        # Strip an extras marker like "[job-queue]" and the version pin.
        name = re.split(r"[\[=<>!~; ]", line, maxsplit=1)[0].strip()
        if not name:
            continue
        key = name.lower()
        module = IMPORT_NAME_OVERRIDES.get(key, key.replace("-", "_"))
        if module is None:
            continue
        try:
            importlib.import_module(module)
        except Exception as error:  # noqa: BLE001 -- report every failure, not just the first
            failures.append(f"{name} (import {module}): {error!r}")

# This project's own modules that directly call into the packages being
# bumped. A library-only import, so this should never have side effects
# (no network calls, no bot startup) -- just class/function definitions
# running at module load time.
for project_module in (
    "src.security",
    "src.yb.meta",
    "src.yb.songs",
    "src.uploader",
    "database.databases",
):
    try:
        importlib.import_module(project_module)
    except Exception as error:  # noqa: BLE001
        failures.append(f"{project_module}: {error!r}")

if failures:
    print("SMOKE TEST FAILED:")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)

print("Smoke test passed: every package and project module imported cleanly.")
PYEOF

if ! "$TEST_PY" "$SMOKE_SCRIPT" "$CANDIDATE" "$REPO_DIR"; then
    fail "The candidate fix failed the smoke test (see above) -- it would likely break the bot."
    warn "Nothing was changed. The real requirements.txt and .venv are untouched."
    exit 2
fi

info "Smoke test passed."

# ---------------------------------------------------------------------------
# 6. Apply for real
# ---------------------------------------------------------------------------

step "Applying the fix"

if ! confirm "Apply this to requirements.txt, reinstall the real .venv, and restart the service(s)?" y; then
    info "Not applied. Re-run and confirm when you're ready (the candidate above is a safe, tested change)."
    exit 1
fi

cp "$CANDIDATE" "$REPO_DIR/requirements.txt"
info "requirements.txt updated."
warn "This only changed the file on disk -- commit and push it yourself if you want the fix in the repository."

# shellcheck disable=SC1091
source "$REAL_VENV/bin/activate"
pip install --quiet -r "$REPO_DIR/requirements.txt"
deactivate
info "Real .venv reinstalled."

step "Restarting services"

if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found. If you're running the bot manually, restart it yourself:"
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
        warn "yt-telegrambot.service isn't installed -- restart the bot manually:"
        warn "  source .venv/bin/activate && python3 main.py"
    fi
fi

step "Done"
