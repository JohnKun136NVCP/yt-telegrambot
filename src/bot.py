"""Telegram bot: downloads YouTube audio and sends it with live progress."""

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
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBDeprecationWarning

from database.databases import usrdatabase, ytdatabase
from src import messages
from src.messages import Quotes
from src.uploader import UploadError, send_audio_with_progress
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

# =============================================================================
# Constants
# =============================================================================

SONGS_DIR = Path("Songs")
SUPPORTED_FORMATS = (".m4a", ".mp3", ".flac")
SUBSCRIBE_IMAGE = Path("img/photo_2.png")
USERS_DB_PATH = "database/users.db"

# Naive time: python-telegram-bot interprets it as UTC.
DAILY_QUOTE_TIME = dtime(hour=18, minute=0, second=0)

# Never download the same video twice at the same time.
_video_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


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
    with closing(usrdatabase()) as user_db:
        user_db.add_user(user_id, username, 0, False, "unsubscribed")


async def register_user(user) -> None:
    """Make sure the user exists in the database."""
    try:
        await asyncio.to_thread(_register_user_sync, user.id, _display_name(user))
    except sqlite3.Error:
        logger.exception("Database error while registering user %s", user.id)


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

    def __init__(self) -> None:
        self._message: Message | None = None
        self._title = "🎧 <b>Processing your request</b>"
        self._steps = {"download": _ACTIVE, "process": _PENDING, "upload": _PENDING}
        self._download_pct = 0.0
        self._upload_pct = 0.0
        self._footer = ""

        self._last_text = ""
        self._last_edit = 0.0
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()
        self._pump_task: asyncio.Task | None = None

    @classmethod
    async def create(cls, source: Message) -> "StatusMessage":
        """Reply to ``source`` with the initial status and start updating it."""
        status = cls()
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

    def mark_cached(self) -> None:
        """The song was already downloaded: skip straight to processing."""
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
        messages.HELP_TEXT, parse_mode=ParseMode.HTML
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


async def set_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start interaction with the bot"),
            BotCommand("help", "Get help on how to use the bot"),
            BotCommand("subscribe", "Subscribe to premium features and info"),
            BotCommand("myid", "Show your Telegram user ID"),
        ]
    )
    await application.bot.set_chat_menu_button()


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


async def _obtain_song(downloader: DownloadYB, status: StatusMessage) -> SongInfo:
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
        data = downloader.songs_data

        if record is None:
            db.insertData(
                data.title, data.artist, video_id, data.duration, data.thumbalImg
            )

        return SongInfo(
            audio_path, data.title, data.artist, data.duration,
            data.thumbalImg, video_id, downloader.quality_note,
        )


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or not message.text:
        return

    url = message.text.strip()
    username = _display_name(user)

    await register_user(user)

    # -- Validate the link before doing any work ------------------------------
    downloader = DownloadYB(url, output_dir=SONGS_DIR)

    try:
        video_id = downloader.regexUrl()
        downloader.generateYbUrl()
    except ValueError:
        await message.reply_text(
            "🔗 That doesn't look like a YouTube link.\n"
            "Send me a valid one and I'll get the audio for you."
        )
        return

    if not await _check_quota(message, user, username):
        return

    status = await StatusMessage.create(message)

    try:
        async with _video_locks[video_id]:
            song = await _obtain_song(downloader, status)

        thumbnail = await asyncio.to_thread(
            downloader.download_thumbnail, song.thumbnail_url, song.video_id
        )

        # -- Upload with real-time progress ---------------------------------
        status.begin_upload()
        await status.refresh(force=True)

        await send_audio_with_progress(
            context.bot,
            update.effective_chat.id,
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
        )

        with closing(usrdatabase()) as user_db:
            user_db.request_song(user.id)

        await status.finish(song)

    except AudioTooLargeError:
        await status.fail("📦 This audio is too large for Telegram's 50 MB limit.")

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


# =============================================================================
# Entry point
# =============================================================================

def main(TELEGRAM_TOKEN):
    try:
        application = (
            Application.builder()
            .token(str(TELEGRAM_TOKEN))
            .post_init(set_bot_commands)
            # Without this, one long download blocks every other user.
            .concurrent_updates(True)
            .read_timeout(40)
            .write_timeout(180)
            .connect_timeout(600)
            .build()
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("myid", yourid_command))
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