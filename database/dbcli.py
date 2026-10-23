"""Admin command-line tool for the bot's SQLite databases.

Talks to the SAME schema/classes the bot itself uses (``usrdatabase`` /
``ytdatabase`` in ``database/databases.py``) instead of a separate, drifted
copy of the table definitions -- the previous version of this file predated
the payments table and the ``premium_until`` column, so it could silently
corrupt or ignore premium/admin state. Run it from the repo root:

    python3 database/dbcli.py <command> [args...]

Commands:
    list                              List every user.
    info <telegram_id>                Show one user's full record.
    grant <telegram_id> <type> [--days N]
                                       Grant/extend access. <type> is one of
                                       admin, premium, subscribed. Omit
                                       --days (or pass 0) for no expiry;
                                       otherwise it expires in N days from
                                       now (stacking on any remaining time).
    revoke <telegram_id>              Downgrade a user back to the free tier.
    admin <telegram_id>               Shortcut for `grant <id> admin` with no
                                       expiry (admin never expires).
    delete-user <telegram_id>         Permanently remove a user's row.
    reset-quota <telegram_id>         Force today's download counter to 0.
    payments [telegram_id]            List Stars payments (all, or one user).
    refund <charge_id>                Mark a payment refunded IN THE DATABASE
                                       ONLY. This does not call Telegram's
                                       API or return the user's Stars -- for
                                       a real refund use the bot's own
                                       /refund <telegram_id> admin command,
                                       which calls refund_star_payment() and
                                       then does this bookkeeping itself.
    stats                             Bot-wide usage/payment stats.
    songs                             List cached songs (idSongs.db).
    clear-songs [-y] [--restart]      Wipe the ENTIRE songs cache: every row
                                      in idSongs.db's `songs` table AND
                                      every cached audio file under Songs/.
                                      The next request for any song
                                      re-downloads it from scratch. Asks for
                                      a typed confirmation unless -y is
                                      given. --restart restarts
                                      yt-telegrambot.service afterward
                                      (needs systemd + sudo) -- not required
                                      for the clear itself to take effect.

Examples:
    python3 database/dbcli.py grant 123456789 premium --days 30
    python3 database/dbcli.py admin 123456789
    python3 database/dbcli.py revoke 123456789
    python3 database/dbcli.py info 123456789
    python3 database/dbcli.py payments 123456789
    python3 database/dbcli.py clear-songs --restart
"""

import argparse
import os
import shutil
import subprocess
import sys
from contextlib import closing
from pathlib import Path

# Allow running as `python3 database/dbcli.py ...` from any directory by
# making sure the repo root (this file's parent's parent) is on sys.path,
# since `database.databases` is imported as a package. Also used to find
# Songs/ for `clear-songs`, independently of the current working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from database.databases import usrdatabase, ytdatabase  # noqa: E402

VALID_GRANT_TYPES = ("admin", "premium", "subscribed")

# Kept in sync with SUPPORTED_FORMATS in src/bot.py -- the extensions a
# cached song can actually be stored as on disk.
AUDIO_EXTENSIONS = (".flac", ".m4a", ".mp3")


def _fmt(value) -> str:
    return "-" if value in (None, "") else str(value)


def cmd_list(_args) -> int:
    with closing(usrdatabase()) as db:
        db.cursor.execute(
            "SELECT telegram_id, username, type_user, songs_by_day, "
            "premium_until, last_request_time FROM users ORDER BY telegram_id"
        )
        rows = db.cursor.fetchall()

    if not rows:
        print("No users yet.")
        return 0

    header = f"{'telegram_id':<14} {'username':<20} {'type':<12} {'today':<6} {'expires':<20} last_request"
    print(header)
    print("-" * len(header))
    for telegram_id, username, type_user, songs_by_day, premium_until, last_request in rows:
        print(
            f"{telegram_id:<14} {_fmt(username):<20} {_fmt(type_user):<12} "
            f"{songs_by_day:<6} {_fmt(premium_until):<20} {_fmt(last_request)}"
        )
    return 0


def cmd_info(args) -> int:
    with closing(usrdatabase()) as db:
        user = db.get_user(args.telegram_id)

    if user is None:
        print(f"No such user: {args.telegram_id}")
        return 1

    for key, value in user.items():
        print(f"{key:<16} {value}")
    return 0


def cmd_grant(args) -> int:
    type_user = args.type_user.lower()

    if type_user not in VALID_GRANT_TYPES:
        print(f"type must be one of: {', '.join(VALID_GRANT_TYPES)}")
        return 1

    with closing(usrdatabase()) as db:
        existing = db.get_user(args.telegram_id)

        if existing is None:
            # set_premium() is a no-op without an existing row.
            db.add_user(args.telegram_id, args.username or str(args.telegram_id))

        ok = db.set_premium(args.telegram_id, type_user, days=args.days or None)
        user = db.get_user(args.telegram_id)

    if not ok:
        print(f"Could not grant {type_user} to {args.telegram_id}.")
        return 1

    expiry = user["premium_until"] or "never"
    print(f"Granted '{type_user}' to {args.telegram_id} (expires: {expiry}).")
    return 0


def cmd_admin(args) -> int:
    with closing(usrdatabase()) as db:
        existing = db.get_user(args.telegram_id)

        if existing is None:
            db.add_user(args.telegram_id, args.username or str(args.telegram_id))

        db.ensure_admin(args.telegram_id)

    print(f"{args.telegram_id} is now admin (no expiry).")
    print(
        "Note: if this id is NOT also listed in ADMIN_IDS in .env, it will "
        "keep admin status in the database, but add it to ADMIN_IDS too if "
        "you want it restored automatically should users.db ever be reset."
    )
    return 0


def cmd_revoke(args) -> int:
    with closing(usrdatabase()) as db:
        ok = db.revoke_premium(args.telegram_id)

    if not ok:
        print(f"No such user: {args.telegram_id}")
        return 1

    print(f"Revoked premium/admin for {args.telegram_id} (back to 'unsubscribed').")
    return 0


def cmd_delete_user(args) -> int:
    with closing(usrdatabase()) as db:
        db.cursor.execute(
            "DELETE FROM users WHERE telegram_id = ?", (args.telegram_id,)
        )
        deleted = db.cursor.rowcount
        db.connect.commit()

    if deleted:
        print(f"Deleted user {args.telegram_id}.")
        return 0

    print(f"No such user: {args.telegram_id}")
    return 1


def cmd_reset_quota(args) -> int:
    with closing(usrdatabase()) as db:
        db.cursor.execute(
            "UPDATE users SET songs_by_day = 0 WHERE telegram_id = ?",
            (args.telegram_id,),
        )
        updated = db.cursor.rowcount
        db.connect.commit()

    if updated:
        print(f"Reset today's download count for {args.telegram_id} to 0.")
        return 0

    print(f"No such user: {args.telegram_id}")
    return 1


def cmd_payments(args) -> int:
    with closing(usrdatabase()) as db:
        if args.telegram_id:
            db.cursor.execute(
                "SELECT telegram_id, charge_id, plan_code, stars, days, "
                "created_at, refunded FROM payments WHERE telegram_id = ? "
                "ORDER BY id DESC",
                (args.telegram_id,),
            )
        else:
            db.cursor.execute(
                "SELECT telegram_id, charge_id, plan_code, stars, days, "
                "created_at, refunded FROM payments ORDER BY id DESC"
            )
        rows = db.cursor.fetchall()

    if not rows:
        print("No payments found.")
        return 0

    header = f"{'telegram_id':<14} {'charge_id':<24} {'plan':<10} {'stars':<6} {'days':<5} {'created_at':<20} refunded"
    print(header)
    print("-" * len(header))
    for telegram_id, charge_id, plan_code, stars, days, created_at, refunded in rows:
        print(
            f"{telegram_id:<14} {charge_id:<24} {plan_code:<10} {stars:<6} "
            f"{days:<5} {created_at:<20} {bool(refunded)}"
        )
    return 0


def cmd_refund(args) -> int:
    with closing(usrdatabase()) as db:
        payment = db.get_payment(args.charge_id)

        if payment is None:
            print(f"No payment found with charge_id: {args.charge_id}")
            return 1

        if payment["refunded"]:
            print("That payment is already marked refunded.")
            return 0

        db.mark_refunded(args.charge_id)

    print(
        f"Marked charge {args.charge_id} (user {payment['telegram_id']}) as "
        "refunded in the database.\n"
        "This did NOT call Telegram's API or return the user's Stars -- use "
        f"the bot's /refund {payment['telegram_id']} admin command for an "
        "actual refund; it calls Telegram and then does this same bookkeeping."
    )
    return 0


def cmd_stats(_args) -> int:
    with closing(usrdatabase()) as db:
        stats = db.stats()

    for key, value in stats.items():
        print(f"{key:<20} {value}")
    return 0


def cmd_songs(_args) -> int:
    with closing(ytdatabase()) as db:
        db.cursor.execute(
            "SELECT id, name, channel, uri, duration, thumbnail_url FROM songs "
            "ORDER BY id"
        )
        rows = db.cursor.fetchall()

    if not rows:
        print("No cached songs yet.")
        return 0

    header = f"{'id':<6} {'name':<40} {'channel':<25} duration"
    print(header)
    print("-" * len(header))
    for song_id, name, channel, _uri, duration, _thumb in rows:
        print(f"{song_id:<6} {_fmt(name)[:40]:<40} {_fmt(channel)[:25]:<25} {_fmt(duration)}")
    return 0


def _restart_service(unit: str = "yt-telegrambot") -> bool:
    """Restart a systemd unit, using sudo if we're not root. Best-effort."""
    if shutil.which("systemctl") is None:
        print("systemctl not found -- restart the bot manually.")
        return False

    command = [] if os.geteuid() == 0 else (["sudo"] if shutil.which("sudo") else [])
    command += ["systemctl", "restart", unit]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        print(f"Could not restart {unit}.service: {error}")
        return False

    print(f"Restarted {unit}.service")
    return True


def cmd_clear_songs(args) -> int:
    songs_dir = REPO_ROOT / "Songs"

    with closing(ytdatabase()) as db:
        db.cursor.execute("SELECT COUNT(*) FROM songs")
        row_count = db.cursor.fetchone()[0]

    files = []
    if songs_dir.is_dir():
        for extension in AUDIO_EXTENSIONS:
            files.extend(songs_dir.glob(f"*{extension}"))

    if row_count == 0 and not files:
        print("The songs cache is already empty -- nothing to clear.")
        return 0

    print(f"This will permanently delete:")
    print(f"  - {row_count} row(s) from idSongs.db's 'songs' table")
    print(f"  - {len(files)} cached audio file(s) under {songs_dir}")
    print("Every song will be re-downloaded from scratch on its next request.")

    if not args.yes:
        answer = input("Type DELETE to confirm: ").strip()

        if answer != "DELETE":
            print("Aborted -- nothing was deleted.")
            return 1

    with closing(ytdatabase()) as db:
        db.cursor.execute("DELETE FROM songs")
        db.connect.commit()

    removed = 0
    for path in files:
        try:
            path.unlink()
            removed += 1
        except OSError as error:
            print(f"Could not remove {path}: {error}")

    print(f"Cleared {row_count} database row(s) and {removed}/{len(files)} file(s).")

    if args.restart:
        _restart_service()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbcli.py",
        description="Admin CLI for yt-telegrambot's SQLite databases.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List every user.").set_defaults(func=cmd_list)

    p = sub.add_parser("info", help="Show one user's full record.")
    p.add_argument("telegram_id", type=int)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("grant", help="Grant/extend admin, premium or subscribed access.")
    p.add_argument("telegram_id", type=int)
    p.add_argument("type_user", choices=VALID_GRANT_TYPES)
    p.add_argument("--days", type=int, default=0, help="Expires in N days (0 = never).")
    p.add_argument("--username", default=None, help="Used only if the user has no row yet.")
    p.set_defaults(func=cmd_grant)

    p = sub.add_parser("admin", help="Shortcut: grant admin with no expiry.")
    p.add_argument("telegram_id", type=int)
    p.add_argument("--username", default=None, help="Used only if the user has no row yet.")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("revoke", help="Downgrade a user back to the free tier.")
    p.add_argument("telegram_id", type=int)
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("delete-user", help="Permanently remove a user's row.")
    p.add_argument("telegram_id", type=int)
    p.set_defaults(func=cmd_delete_user)

    p = sub.add_parser("reset-quota", help="Force today's download counter to 0.")
    p.add_argument("telegram_id", type=int)
    p.set_defaults(func=cmd_reset_quota)

    p = sub.add_parser("payments", help="List Stars payments (all, or one user).")
    p.add_argument("telegram_id", type=int, nargs="?", default=None)
    p.set_defaults(func=cmd_payments)

    p = sub.add_parser(
        "refund", help="Mark a payment refunded IN THE DATABASE ONLY (see --help)."
    )
    p.add_argument("charge_id")
    p.set_defaults(func=cmd_refund)

    sub.add_parser("stats", help="Bot-wide usage/payment stats.").set_defaults(func=cmd_stats)
    sub.add_parser("songs", help="List cached songs (idSongs.db).").set_defaults(func=cmd_songs)

    p = sub.add_parser(
        "clear-songs",
        help="Wipe the songs cache (DB rows + cached audio files under Songs/).",
    )
    p.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt.")
    p.add_argument(
        "--restart", action="store_true",
        help="Restart yt-telegrambot.service afterward (needs systemd + sudo).",
    )
    p.set_defaults(func=cmd_clear_songs)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
