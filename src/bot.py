"""Telegram bot: downloads YouTube audio and sends it with live progress.

Request flow, in order: flood control -> link validation -> daily quota ->
tier lookup (free/premium -> size cap) -> bounded job queue -> download ->
upload (with a local-server fast path for premium-sized files) -> metadata.
See src/config.py, src/security.py, src/job_queue.py and src/payments.py for
the pieces this module wires together.
"""

from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
import time
import warnings
from collections import defaultdict
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import time as dtime
from functools import wraps
from pathlib import Path

import httpx
from telegram import BotCommand, Message, Update
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)
from telegram.warnings import PTBDeprecationWarning

from database.databases import usrdatabase, ytdatabase
from src import messages, payments
from src.config import ConfigError, get_config
from src.job_queue import JobQueue, JobRecord, QueueFullError
from src.logging_utils import get_file_logger
from src.messages import Quotes
from src.security import FloodControl, is_youtube_url
from src.uploader import UploadError, close_client, send_audio_with_progress
from src.yb.songs import AudioTooLargeError, DownloadYB

# =============================================================================
# Logging
# =============================================================================

Path("logs").mkdir(exist_ok=True)

warnings.filterwarnings("error", category=PTBDeprecationWarning)

logging.basicConfig(
    filename="logs/botlogs.log",
    encoding="utf-8",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# The old code called setLevel() four times per logger, so only the last call
# (CRITICAL) counted and every real Telegram error was hidden. httpx at INFO
# would also write the bot token (it is part of the URL) into the log file.
for _noisy in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
queue_logger = get_file_logger("src.job_queue", "queue.log")

# =============================================================================
# Constants
# =============================================================================

SONGS_DIR = Path("Songs")
QUEUE_DB_PATH = "database/queue.db"

# Checked in this order: best quality first, so a premium-quality cache hit
# (.flac/.m4a) is always preferred over a leftover quality-reduced .mp3 from
# an earlier free-tier download of the same video.
SUPPORTED_FORMATS = (".flac", ".m4a", ".mp3")

SUBSCRIBE_IMAGE = Path("img/photo_2.png")
USERS_DB_PATH = "database/users.db"

# Naive time: python-telegram-bot interprets it as UTC.
DAILY_QUOTE_TIME = dtime(hour=18, minute=0, second=0)

# Never download the same video twice at the same time.
_video_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Per-user cooldown between link submissions (not persisted -- see
# src/security.py's FloodControl docstring for why that's fine here).
_flood_control: FloodControl | None = None


def get_flood_control() -> FloodControl:
    global _flood_control

    if _flood_control is None:
        _flood_control = FloodControl(get_config().min_seconds_between_requests)

    return _flood_control


@dataclass
class SongInfo:
    """Everything needed to send a song to the user."""

    path: Path
    title: str
    artist: str
    duration: int
    thumbnail_url: str | None
    video_id: str
    quality_note: str | None = None


# =============================================================================
# Helpers
# =============================================================================

def _display_name(user) -> str:
    """Best available name for a user (usernames are optional on Telegram)."""
    return user.username or user.first_name or str(user.id)


def format_duration(seconds: int) -> str:
    """Format seconds as ``mm:ss`` (or ``h:mm:ss`` for long audio)."""
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes:02d}:{secs:02d}"


def _retry_seconds(error: RetryAfter) -> float:
    """``retry_after`` is an int or a timedelta depending on the PTB version."""
    delay = error.retry_after
    return float(delay.total_seconds() if hasattr(delay, "total_seconds") else delay)


def _register_user_sync(user_id: int, username: str) -> None:
    config = get_config()

    with closing(usrdatabase()) as user_db:
        user_db.add_user(user_id, username, 0, False, "unsubscribed")

        # Bot-operator ids (ADMIN_IDS in .env) always have admin status,
        # restored automatically even if the users.db file is ever replaced.
        if user_id in config.admin_ids:
            user_db.ensure_admin(user_id)


async def register_user(user) -> None:
    """Make sure the user exists in the database."""
    try:
        await asyncio.to_thread(_register_user_sync, user.id, _display_name(user))
    except sqlite3.Error:
        logger.exception("Database error while registering user %s", user.id)


def _tier_sync(user_id: int) -> tuple[bool, float]:
    """Return ``(unlimited, max_size_mb)`` for a user, off the event loop."""
    config = get_config()

    with closing(usrdatabase()) as db:
        unlimited = db.is_unlimited(user_id)

    max_size_mb = config.effective_premium_max_mb() if unlimited else config.standard_max_mb
    return unlimited, max_size_mb


def find_audio_file(video_id: str, legacy_title: str | None = None) -> Path | None:
    """Locate the stored audio of ``video_id``.

    New files are named ``<video_id>.<ext>``. ``legacy_title`` enables a slower
    search for files stored by older versions (named after the song title).
    """
    for suffix in SUPPORTED_FORMATS:
        candidate = SONGS_DIR / f"{video_id}{suffix}"

        if candidate.is_file():
            return candidate

    if legacy_title is None or not SONGS_DIR.exists():
        return None

    wanted = legacy_title.strip().lower()

    for path in SONGS_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_FORMATS:
            continue

        if video_id in path.name or path.stem.strip().lower() == wanted:
            return path

    return None


def _cached_file_is_reusable(audio_path: Path, max_size_mb: float, unlimited: bool) -> bool:
    """Whether a previously-downloaded file is good enough for THIS request.

    Two ways a cache hit is rejected (the file is kept on disk either way --
    only a fresh file is produced alongside it):
      - It is bigger than this requester's cap (a premium user's FLAC/M4A
        would fail to upload for a standard-tier requester).
      - The requester is unlimited-tier but the cached file is an ``.mp3``
        (meaning some earlier, size-constrained request had to shrink it) --
        such a requester is entitled to the original, un-reduced quality.
    """
    size_mb = DownloadYB.size_mb(audio_path)

    if size_mb > max_size_mb:
        return False

    if unlimited and max_size_mb > DownloadYB.MAX_SIZE_MB and audio_path.suffix.lower() == ".mp3":
        return False

    return True


def _cleanup_other_versions(video_id: str, keep: Path) -> None:
    """Remove other cached files for ``video_id`` once a new one replaces them."""
    for suffix in SUPPORTED_FORMATS:
        if suffix == keep.suffix.lower():
            continue

        stale = SONGS_DIR / f"{video_id}{suffix}"

        if stale.exists() and stale != keep:
            stale.unlink(missing_ok=True)
            logger.info("Removed superseded cache file: %s", stale)


# =============================================================================
# Live progress message
# =============================================================================

_PENDING, _ACTIVE, _DONE, _FAILED = "pending", "active", "done", "failed"

_STATE_ICONS = {
    _PENDING: "⏳",
    _ACTIVE: "🔄",
    _DONE: "✅",
    _FAILED: "❌",
}


def build_progress_bar(percentage: float, length: int = 10) -> str:
    """Return a bar such as ``▰▰▰▱▱▱▱▱▱▱``."""
    percentage = max(0.0, min(100.0, percentage))
    filled = int(length * percentage / 100)
    return "▰" * filled + "▱" * (length - filled)


class StatusMessage:
    """A single Telegram message that shows live progress.

    Progress setters only store numbers, so they are safe to call from the
    download worker thread. A background task samples those numbers and edits
    the message at most once every ``MIN_EDIT_INTERVAL`` seconds, staying
    below Telegram's edit rate limits.
    """

    MIN_EDIT_INTERVAL = 1.5

    def __init__(self, queued: bool = False) -> None:
        self._message: Message | None = None
        self._title = "🎧 <b>Processing your request</b>"
        self._queued = queued
        self._steps = {
            "download": _PENDING if queued else _ACTIVE,
            "process": _PENDING,
            "upload": _PENDING,
        }
        self._download_pct = 0.0
        self._upload_pct = 0.0
        self._footer = ""

        self._last_text = ""
        self._last_edit = 0.0
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()
        self._pump_task: asyncio.Task | None = None

    @classmethod
    async def create(cls, source: Message, queued: bool = False) -> "StatusMessage":
        """Reply to ``source`` with the initial status and start updating it."""
        status = cls(queued=queued)
        text = status._render()

        status._message = await source.reply_text(text, parse_mode=ParseMode.HTML)
        status._last_text = text
        status._last_edit = time.monotonic()
        status._pump_task = asyncio.create_task(status._pump())

        return status

    # -------------------------------------------------------------------------
    # State changes
    # -------------------------------------------------------------------------

    def set_download_progress(self, percentage: float) -> None:
        """Thread-safe: called by the downloader."""
        self._download_pct = max(self._download_pct, float(percentage))

    def set_upload_progress(self, percentage: float) -> None:
        self._upload_pct = float(percentage)

    def mark_dequeued(self) -> None:
        """A worker has picked this job up: stop showing "waiting in queue"."""
        self._queued = False

        if self._steps["download"] == _PENDING:
            self._steps["download"] = _ACTIVE

    def mark_cached(self) -> None:
        """The song was already downloaded: skip straight to processing."""
        self._queued = False
        self._download_pct = 100.0
        self._steps.update(download=_DONE, process=_ACTIVE)

    def begin_upload(self) -> None:
        self._download_pct = 100.0
        self._upload_pct = 0.0
        self._steps.update(download=_DONE, process=_DONE, upload=_ACTIVE)

    async def finish(self, song: SongInfo) -> None:
        self._download_pct = self._upload_pct = 100.0
        self._steps = {key: _DONE for key in self._steps}
        self._title = "✅ <b>Done!</b>"
        self._footer = (
            f"🎵 <b>{html.escape(song.title)}</b>\n"
            f"👤 {html.escape(song.artist)}\n"
            f"⏱ {format_duration(song.duration)}"
        )

        if song.quality_note:
            self._footer += f"\n\n<i>{html.escape(song.quality_note)}</i>"

        await self.refresh(force=True)
        await self.close()

    async def fail(self, note: str) -> None:
        self._queued = False

        for key, state in self._steps.items():
            if state == _ACTIVE:
                self._steps[key] = _FAILED

        self._title = "⚠️ <b>Something went wrong</b>"
        self._footer = note
        await self.refresh(force=True)
        await self.close()

    async def close(self) -> None:
        """Stop the background updater (safe to call more than once)."""
        if self._pump_task is not None:
            self._pump_task.cancel()

            with suppress(asyncio.CancelledError):
                await self._pump_task

            self._pump_task = None

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------

    def _step_lines(self, key: str, label: str, percentage: float | None) -> list[str]:
        state = self._steps[key]
        lines = [f"{_STATE_ICONS[state]} {label}"]

        if percentage is not None and state in (_ACTIVE, _DONE):
            shown = 100.0 if state == _DONE else percentage
            lines.append(
                f"<code>   {build_progress_bar(shown)} {shown:.0f}%</code>"
            )

        return lines

    def _render(self) -> str:
        lines = [self._title, ""]

        if self._queued:
            lines.append("🕒 Waiting in queue…")
        else:
            lines += self._step_lines("download", "Downloading audio", self._download_pct)

        lines += self._step_lines("process", "Processing & optimizing", None)
        lines += self._step_lines("upload", "Uploading to Telegram", self._upload_pct)

        if self._footer:
            lines += ["", self._footer]

        return "\n".join(lines)

    def _sync_stages(self) -> None:
        # The downloader only reports download progress, so 100% means the
        # processing (conversion + tagging) has started.
        if self._steps["download"] == _ACTIVE and self._download_pct >= 100:
            self._steps.update(download=_DONE, process=_ACTIVE)

    async def refresh(self, force: bool = False) -> None:
        """Edit the message if the text changed (throttled unless ``force``)."""
        async with self._lock:
            if self._message is None:
                return

            self._sync_stages()
            text = self._render()

            if text == self._last_text:
                return

            now = time.monotonic()

            if now < self._blocked_until:
                if not force:
                    return
                await asyncio.sleep(self._blocked_until - now)

            elif not force and now - self._last_edit < self.MIN_EDIT_INTERVAL:
                return

            try:
                await self._message.edit_text(text, parse_mode=ParseMode.HTML)
                self._last_text = text
                self._last_edit = time.monotonic()

            except RetryAfter as error:
                self._blocked_until = time.monotonic() + _retry_seconds(error) + 0.5

            except BadRequest as error:
                if "not modified" in str(error).lower():
                    self._last_text = text
                else:
                    logger.warning("Could not update status message: %s", error)

            except TelegramError as error:
                logger.warning("Could not update status message: %s", error)

    async def _pump(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.MIN_EDIT_INTERVAL)
                await self.refresh()

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception("Status updater crashed")


# =============================================================================
# Global error handler
# =============================================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)

    if isinstance(context.error, (TimedOut, httpx.TransportError)):
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ A network error occurred while processing your request. "
                "Please try again later."
            )


# =============================================================================
# Daily quote
# =============================================================================

def _fetch_free_user_ids() -> list[int]:
    with closing(sqlite3.connect(USERS_DB_PATH)) as conn:
        rows = conn.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE (premium = 0 OR premium IS NULL)
              AND (type_user IS NULL OR LOWER(type_user) = 'unsubscribed')
            """
        ).fetchall()

    return [row[0] for row in rows]


def _delete_user(user_id: int) -> None:
    with closing(sqlite3.connect(USERS_DB_PATH)) as conn:
        with conn:
            conn.execute("DELETE FROM users WHERE telegram_id = ?", (user_id,))


def _expire_premium_sync() -> int:
    with closing(usrdatabase()) as db:
        return db.expire_old_premium()


async def _send_html(bot, chat_id: int, text: str) -> None:
    """Send an HTML message, retrying once if Telegram asks us to slow down."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)

    except RetryAfter as error:
        await asyncio.sleep(_retry_seconds(error) + 1)
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)


async def send_daily_quote(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the quote of the day to non-premium users."""
    try:
        expired = await asyncio.to_thread(_expire_premium_sync)

        if expired:
            logger.info("Expired premium for %d user(s) before the daily broadcast.", expired)

        user_ids = await asyncio.to_thread(_fetch_free_user_ids)

        if not user_ids:
            logger.info("There are no non-premium users.")
            return

        # requests is blocking, so it runs in a worker thread.
        quote = await asyncio.to_thread(Quotes().get_quote)

        if quote is None:
            logger.warning("Could not obtain the daily quote.")
            return

        text = quote.format_html()
        sent = 0

        for user_id in user_ids:
            try:
                await _send_html(context.bot, user_id, text)
                sent += 1

            except Forbidden:
                logger.warning("User %s blocked the bot. Removing from database.", user_id)
                await asyncio.to_thread(_delete_user, user_id)

            except TelegramError as error:
                logger.error("Error sending quote to %s: %s", user_id, error)

            # Stay far below Telegram's ~30 messages/second broadcast limit.
            await asyncio.sleep(0.05)

        logger.info("Daily quote sent to %s/%s users", sent, len(user_ids))

    except sqlite3.Error:
        logger.exception("Database error while sending the daily quote")

    except Exception:
        logger.exception("Error sending the daily quote")


# =============================================================================
# Commands
# =============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await register_user(user)

    name = user.first_name or user.username or "there"
    await update.effective_message.reply_text(
        messages.start_text(name), parse_mode=ParseMode.HTML
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)
    await update.effective_message.reply_text(
        messages.HELP_TEXT,
        parse_mode=ParseMode.HTML,
        link_preview_options=messages.NO_PREVIEW,
    )


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await register_user(update.effective_user)

    with SUBSCRIBE_IMAGE.open("rb") as photo:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo,
            caption=messages.SUBSCRIBE_CAPTION,
            parse_mode=ParseMode.HTML,
        )


async def yourid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await register_user(user)
    await update.effective_message.reply_text(
        f"🆔 Your Telegram ID is: <code>{user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the sender's own tier, quota and upload-size cap."""
    user = update.effective_user
    await register_user(user)

    config = get_config()

    def _fetch():
        with closing(usrdatabase()) as db:
            return db.get_user(user.id)

    info = await asyncio.to_thread(_fetch)

    if info is None:
        await update.effective_message.reply_text("Send /start first.")
        return

    max_mb = config.effective_premium_max_mb() if info["unlimited"] else config.standard_max_mb

    lines = [
        "👤 <b>Your status</b>",
        "",
        f"Tier: <b>{html.escape(info['type_user'])}</b>",
    ]

    if info["unlimited"]:
        expiry = (
            f" (until {payments.format_date(info['premium_until'])})"
            if info["premium_until"]
            else " (no expiry)"
        )
        lines.append(f"Downloads: unlimited{expiry}")
    else:
        lines.append(
            f"Downloads today: {info['songs_by_day']}/{usrdatabase.FREE_USER_DAILY_LIMIT}"
        )

    lines.append(f"Max file size: {max_mb:.0f} MB")
    lines.append("")
    lines.append("Use /premium to upgrade.")

    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def set_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start interaction with the bot"),
            BotCommand("help", "Get help on how to use the bot"),
            BotCommand("premium", "Unlock unlimited downloads with Telegram Stars"),
            BotCommand("status", "Show your tier and daily quota"),
            BotCommand("subscribe", "Other ways to support the project"),
            BotCommand("myid", "Show your Telegram user ID"),
        ]
    )
    await application.bot.set_chat_menu_button()


# =============================================================================
# Admin commands
# =============================================================================

def admin_only(handler):
    """Decorator: refuse to run ``handler`` unless the sender is an admin."""

    @wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        config = get_config()

        if user is None or user.id not in config.admin_ids:
            await update.effective_message.reply_text("⛔ This command is for admins only.")
            return

        await handler(update, context)

    return wrapped


@admin_only
async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/grant <telegram_id> <admin|premium|subscribed> [days]``."""
    args = context.args or []

    if len(args) < 2 or not args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text(
            "Usage: /grant <telegram_id> <admin|premium|subscribed> [days]\n"
            "Omit [days] for no expiry."
        )
        return

    target_id = int(args[0])
    type_user = args[1].lower()

    if type_user not in {"admin", "premium", "subscribed"}:
        await update.effective_message.reply_text(
            "Type must be one of: admin, premium, subscribed."
        )
        return

    days: int | None = None

    if len(args) >= 3:
        if not args[2].isdigit() or int(args[2]) <= 0:
            await update.effective_message.reply_text("[days] must be a positive integer.")
            return
        days = int(args[2])

    def _apply() -> dict | None:
        with closing(usrdatabase()) as db:
            db.add_user(target_id, f"id:{target_id}")

            if type_user == "admin":
                db.ensure_admin(target_id)
            else:
                db.set_premium(target_id, type_user, days=days)

            return db.get_user(target_id)

    info = await asyncio.to_thread(_apply)
    expiry = payments.format_date(info["premium_until"]) if info else "unknown"

    await update.effective_message.reply_text(
        f"✅ User <code>{target_id}</code> is now <b>{info['type_user']}</b> "
        f"(until {expiry}).",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/revoke <telegram_id>`` -- downgrade a user to the free tier."""
    args = context.args or []

    if not args or not args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text("Usage: /revoke <telegram_id>")
        return

    target_id = int(args[0])

    def _apply() -> bool:
        with closing(usrdatabase()) as db:
            return db.revoke_premium(target_id)

    ok = await asyncio.to_thread(_apply)

    await update.effective_message.reply_text(
        f"✅ User {target_id} downgraded to the free tier."
        if ok else f"User {target_id} was not found."
    )


@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    def _apply() -> dict:
        with closing(usrdatabase()) as db:
            return db.stats()

    stats = await asyncio.to_thread(_apply)
    config = get_config()
    job_queue: JobQueue | None = context.bot_data.get("job_queue")
    waiting = job_queue.waiting if job_queue else "?"

    text = (
        "📊 <b>Bot stats</b>\n\n"
        f"Users: {stats['total_users']} "
        f"(admins: {stats['admins']}, premium/subscribed: {stats['premium_flagged']})\n"
        f"Free downloads today (bot-wide): {stats['free_downloads_today']}/"
        f"{usrdatabase.GLOBAL_FREE_DAILY_LIMIT}\n"
        f"Stars payments: {stats['payment_count']} ({stats['stars_total']} ⭐ total)\n"
        f"Queue: {waiting}/{config.queue_max_size} waiting, {config.queue_workers} worker(s)\n"
        f"Upload caps: {config.standard_max_mb:.0f} MB standard / "
        f"{config.effective_premium_max_mb():.0f} MB premium "
        f"({'local server' if config.uses_local_server else 'cloud API, no local server configured'})"
    )

    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


# =============================================================================
# Download flow
# =============================================================================

async def _check_quota(message: Message, user, username: str) -> bool:
    """Apply the daily limits. Returns ``True`` if the user may download."""
    try:
        with closing(usrdatabase()) as user_db:
            reset_done, reset_msg = user_db.reset_daily_song_counts(user.id, username)

            if reset_done:
                await message.reply_text(f"🔄 {reset_msg}")

            can_request, request_msg = user_db.can_request_song(user.id)

            if not can_request:
                await message.reply_text(f"🚫 {request_msg}")
                return False

            user_db.registerTimeRequest(user.id)

        return True

    except sqlite3.Error:
        logger.exception("Database error while checking the quota of %s", user.id)
        await message.reply_text("⚠️ Database error. Please try again later.")
        return False


async def _obtain_song(
    downloader: DownloadYB, status: StatusMessage, unlimited: bool
) -> SongInfo:
    """Return the song from the cache, or download it if needed."""
    video_id = downloader.video_id

    with closing(ytdatabase()) as db:

        record = None

        if db.isOntheDatabase(video_id):
            found, row = db.verifyURL(video_id)

            if found:
                record = row

        audio_path = find_audio_file(
            video_id, legacy_title=record[1] if record else None
        )

        if audio_path is not None and not _cached_file_is_reusable(
            audio_path, downloader.max_size_mb, unlimited
        ):
            logger.info(
                "Cache hit for %s rejected for this tier (size/quality mismatch), "
                "re-downloading.",
                video_id,
            )
            audio_path = None

        # -- Cached: no download needed -------------------------------------
        if audio_path is not None and record is not None:
            status.mark_cached()
            await status.refresh(force=True)

            _, title, artist, _, db_duration, thumbnail_url = record
            duration = (
                await asyncio.to_thread(DownloadYB.audio_duration, audio_path)
                or db_duration
                or 0
            )

            return SongInfo(audio_path, title, artist, duration, thumbnail_url, video_id)

        # -- Download (runs in a worker thread so the bot stays responsive) --
        downloader.progress_callback = status.set_download_progress
        audio_path = await asyncio.to_thread(downloader.download)
        await asyncio.to_thread(_cleanup_other_versions, video_id, audio_path)
        data = downloader.songs_data

        if record is None:
            db.insertData(
                data.title, data.artist, video_id, data.duration, data.thumbalImg
            )

        return SongInfo(
            audio_path, data.title, data.artist, data.duration,
            data.thumbalImg, video_id, downloader.quality_note,
        )


async def _run_download(
    downloader: DownloadYB,
    status: StatusMessage,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    unlimited: bool,
    max_size_mb: float,
) -> None:
    """The actual work for one request. Runs inside a job-queue worker."""
    config = get_config()
    url = downloader.url

    try:
        async with _video_locks[downloader.video_id]:
            song = await _obtain_song(downloader, status, unlimited)

        thumbnail = await asyncio.to_thread(
            downloader.download_thumbnail, song.thumbnail_url, song.video_id
        )

        # -- Upload with real-time progress ---------------------------------
        status.begin_upload()
        await status.refresh(force=True)

        await send_audio_with_progress(
            context.bot,
            chat_id,
            song.path,
            title=song.title,
            performer=song.artist,
            duration=song.duration,
            filename=(
                DownloadYB.clean_filename(f"{song.artist} - {song.title}")
                + song.path.suffix
            ),
            caption="🎵 Downloaded from YouTube\n🤖 @songytbbot",
            thumbnail=thumbnail,
            on_progress=status.set_upload_progress,
            max_size_mb=max_size_mb,
            local_file_mode=config.bot_api_local_mode,
        )

        await asyncio.to_thread(lambda: usrdatabase().request_song(user_id))

        await status.finish(song)

    except AudioTooLargeError:
        await status.fail(f"📦 This audio is too large for the {max_size_mb:.0f} MB limit.")

    except UploadError as error:
        logger.error("Telegram rejected the upload of %s: %s", url, error)
        await status.fail("📤 Telegram rejected the file. Please try again.")

    except (httpx.HTTPError, TimedOut) as error:
        logger.error("Network error processing %s: %s", url, error)
        await status.fail("🌐 Connection error. Please try again.")

    except Exception:
        logger.exception("Unexpected error processing %s", url)
        await status.fail("❌ An error occurred while processing the song.")

    finally:
        await status.close()


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    url = message.text.strip()
    username = _display_name(user)
    config = get_config()

    await register_user(user)

    # -- Flood control (skip for admins: trusted operators) -------------------
    if user.id not in config.admin_ids:
        wait = get_flood_control().check(user.id)

        if wait > 0:
            await message.reply_text(
                f"⏳ Please wait {max(1, round(wait))}s before sending another link."
            )
            return

    # -- Security: only ever act on genuine YouTube links ----------------------
    if not is_youtube_url(url):
        await message.reply_text(
            "🔗 That doesn't look like a YouTube link.\n"
            "Send me a valid one and I'll get the audio for you."
        )
        return

    downloader = DownloadYB(url, output_dir=SONGS_DIR)

    try:
        downloader.regexUrl()
        downloader.generateYbUrl()
    except ValueError:
        await message.reply_text(
            "🔗 That doesn't look like a YouTube link.\n"
            "Send me a valid one and I'll get the audio for you."
        )
        return

    if not await _check_quota(message, user, username):
        return

    unlimited, max_size_mb = await asyncio.to_thread(_tier_sync, user.id)
    downloader.set_size_limit(max_size_mb)

    job_queue: JobQueue = context.bot_data["job_queue"]
    status = await StatusMessage.create(message, queued=job_queue.waiting > 0)

    async def handler(_payload: str) -> None:
        await _run_download(
            downloader, status, context,
            update.effective_chat.id, user.id, unlimited, max_size_mb,
        )

    async def on_start(_job: JobRecord) -> None:
        status.mark_dequeued()
        await status.refresh(force=True)

    try:
        await job_queue.submit(
            chat_id=update.effective_chat.id,
            user_id=user.id,
            payload=url,
            handler=handler,
            on_start=on_start,
        )
    except QueueFullError as error:
        await status.fail(f"🚦 {error}")


# =============================================================================
# Startup / shutdown
# =============================================================================

async def post_init(application: Application) -> None:
    await set_bot_commands(application)

    config = get_config()

    job_queue = JobQueue(
        db_path=QUEUE_DB_PATH,
        max_size=config.queue_max_size,
        workers=config.queue_workers,
        job_timeout_seconds=config.job_timeout_seconds,
    )
    application.bot_data["job_queue"] = job_queue

    async def notify_stale_job(job: JobRecord) -> None:
        """Told about a job orphaned by an unclean shutdown: tell its chat."""
        try:
            await application.bot.send_message(
                chat_id=job.chat_id,
                text=(
                    "⚠️ The bot restarted while handling your request "
                    "(the server may have lost power or been redeployed).\n\n"
                    "Nothing is stuck -- please just send the link again."
                ),
            )
        except TelegramError as error:
            logger.warning(
                "Could not notify chat %s about a stale job: %s", job.chat_id, error
            )

    recovered = await job_queue.recover_stale_jobs(notify_stale_job)

    if recovered:
        logger.warning(
            "Startup recovery: notified %d chat(s) about jobs lost in the "
            "previous run instead of resuming them.",
            recovered,
        )

    job_queue.start()
    logger.info(
        "Bot ready. Standard cap %.0f MB, premium cap %.0f MB (%s).",
        config.standard_max_mb,
        config.effective_premium_max_mb(),
        "local Bot API server" if config.uses_local_server else "cloud API only",
    )


async def post_shutdown(application: Application) -> None:
    job_queue: JobQueue | None = application.bot_data.get("job_queue")

    if job_queue is not None:
        await job_queue.stop()
        job_queue.close()

    await close_client()


# =============================================================================
# Entry point
# =============================================================================

def main() -> None:
    try:
        config = get_config()
    except ConfigError as error:
        logger.error("Configuration error: %s", error)
        raise SystemExit(f"Configuration error: {error}") from error

    try:
        builder = (
            Application.builder()
            .token(config.token)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            # Without this, one long download blocks every other user.
            .concurrent_updates(True)
            .read_timeout(40)
            .write_timeout(180)
            .connect_timeout(600)
        )

        if config.uses_local_server:
            builder = (
                builder
                .base_url(config.bot_api_base_url)
                .base_file_url(config.bot_api_base_file_url)
                .local_mode(config.bot_api_local_mode)
            )
            logger.info("Using local Bot API server at %s", config.bot_api_base_url)

        application = builder.build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("myid", yourid_command))
        application.add_handler(CommandHandler("status", status_command))

        # -- Payments (Telegram Stars) ----------------------------------------
        application.add_handler(CommandHandler("premium", payments.premium_command))
        application.add_handler(
            CallbackQueryHandler(payments.buy_plan_callback, pattern=r"^buy:")
        )
        application.add_handler(PreCheckoutQueryHandler(payments.precheckout_callback))
        application.add_handler(
            MessageHandler(filters.SUCCESSFUL_PAYMENT, payments.successful_payment_callback)
        )

        # -- Admin ---------------------------------------------------------------
        application.add_handler(CommandHandler("grant", grant_command))
        application.add_handler(CommandHandler("revoke", revoke_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("refund", admin_only(payments.refund_command)))

        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
        application.add_error_handler(error_handler)

        application.job_queue.run_daily(
            send_daily_quote,
            DAILY_QUOTE_TIME,
            days=(0, 1, 2, 3, 4, 5, 6),
        )

        application.run_polling(drop_pending_updates=True, close_loop=False)

    except Exception:
        logger.exception("Unexpected error in main")
