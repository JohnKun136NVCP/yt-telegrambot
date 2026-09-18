
import asyncio
import httpx
import httpcore
import logging
import warnings
import os
import sqlite3
from difflib import SequenceMatcher as sm
from pathlib import Path
from src.yb.songs import DownloadYB
from src.messages import Quotes
from database.databases import ytdatabase
from database.databases import usrdatabase
from datetime import time
from telegram import Update, BotCommand, Bot
from telegram.error import Forbidden, BadRequest
from telegram.warnings import PTBDeprecationWarning
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackContext,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
# Enable logging
warnings.filterwarnings("error", category=PTBDeprecationWarning)
logging.basicConfig(
    filename="logs/botlogs.log",
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger('httpx').setLevel(logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("telegram.ext").setLevel(logging.CRITICAL)
logging.getLogger('httpcore').setLevel(logging.INFO)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.ERROR)
logging.getLogger('httpcore').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


# Global error handler for unhandled exceptions
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception not handled", exc_info=context.error)
    if isinstance(context.error, (httpx.HTTPError, httpcore.ConnectError)):
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Warning: Network error occurred while processing your request. Please try again later.")



async def getUser(id,username):
    try:
        userDatabase = usrdatabase()
        userDatabase.add_user(id,username,0,False,'unsubscribed')
        userDatabase.close()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

async def messageToUser(
    context: ContextTypes.DEFAULT_TYPE
):
    """
    Send the daily random quote to non-premium users.
    """

    conn = None

    try:

        info = Quotes()

        # =====================================================
        # Database
        # =====================================================

        conn = sqlite3.connect(
            "database/users.db"
        )

        cursor = conn.cursor()

        cursor.execute("""
            SELECT telegram_id
            FROM users
            WHERE (premium = 0 OR premium IS NULL)
            AND (
                type_user IS NULL
                OR LOWER(type_user) = 'unsubscribed'
            )
        """)

        result = cursor.fetchall()

        if not result:

            logger.info(
                "There are no non-premium users."
            )

            return

        non_premium_users = [
            row[0]
            for row in result
        ]

        # =====================================================
        # Get quote
        # =====================================================

        quote = info.get_quote()

        if not quote:

            logger.warning(
                "Could not obtain the daily quote."
            )

            return

        # =====================================================
        # Message
        # =====================================================

        quote_text = (
            "✨ *Quote of the day* ✨\n\n"
            f"_{quote}_"
        )

        # =====================================================
        # Send
        # =====================================================

        for idUser in non_premium_users:

            try:

                await context.bot.send_message(
                    chat_id=idUser,
                    text=quote_text,
                    parse_mode="Markdown"
                )

                logger.info(
                    "Quote sent to user %s",
                    idUser
                )

            except Forbidden:

                logger.warning(
                    "User %s blocked the bot. "
                    "Removing from database.",
                    idUser
                )

                cursor.execute(
                    """
                    DELETE FROM users
                    WHERE telegram_id = ?
                    """,
                    (idUser,)
                )

                conn.commit()

            except BadRequest as error:

                logger.error(
                    "BadRequest sending quote "
                    "to %s: %s",
                    idUser,
                    error
                )

    except sqlite3.Error as error:

        logger.error(
            "Database error: %s",
            error
        )

    except Exception as error:

        logger.exception(
            "Error sending daily quote: %s",
            error
        )

    finally:

        if conn:

            conn.close()


async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text("Hi {}, I'm a bot that can download songs from YouTube. Send me a link to a YouTube video and I'll send you the audio file.".format(user['username']))

async def help_command(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text(f"How to use:\n 1. Go to the page with an interesting video (for example - https://www.youtube.com/watch?v=widZEAJc0QM). \n2. Click the Share button. \n3. In the menu that opens, select - Telegram. \n4. When Telegram opens, click on the chat with the blue dude! Or just paste the link to the video into the chat and send it to the bot.\n Do you have any questions? Please contact the developer @KiyotakaKatzut01.")

async def subscribe_command(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await context.bot.send_photo(
    chat_id=update.effective_chat.id,
    photo="img/photo_2.png",
    caption="""
    🎧 *Unlock Full Access \\- Support the Project*  
    🚀 _Unlimited downloads \\(if YouTube allows it\\)_  
    ⏳ _No time restrictions_

    🆓 *Free Version Limitations:*  
    ⛔ Max *1 song per day*  
    📜 Quote spanning is available, but limited
    🕒 Global limit 2 by all users per day

    💬 *Why support?*  
    This project is *free*, clean, and safe \\- no malicious scripts, no viruses, just pure functionality\\.  
    Due to *YouTube’s new policies*, it’s getting harder to maintain\\.  
    I fix bugs, improve the code, and keep it running for everyone \\- your support helps me keep going 💪

    💖 *How to support me:*  
    ☕ [Buy Me a Coffee](https://buymeacoffee.com/johnkun29)  
    🧡 [Ko\\-Fi](https://ko-fi.com/johnkun136nvcp)  
    💻 [GitHub Sponsors](https://github.com/sponsors/JohnKun136NVCP)

    📲 *How to unlock full access:*  
    1\\. Support me on any platform above  
    2\\. Use /myid to get your Telegram user ID  
    3\\. Send me your ID and proof of support via /help

    🙏 *Thank you for supporting this project\\!*  
    Every bit of help keeps it alive and growing 🌱
    """,
        parse_mode="MarkdownV2"
    )
async def yourid_command(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text(f"Your Telegram ID is: {user['id']}")


async def changeCommands(application: Application) -> None:
    command = [BotCommand("start", "Start interaction with the bot"), 
               BotCommand("help", "Get help on how to use the bot"),
               BotCommand("subscribe", "Subscribe to premium features and info"),
               BotCommand("myid", "Show your Telegram user ID")]
    await application.bot.set_my_commands(command)
    await application.bot.set_chat_menu_button()
def create_progress_bar(
    percentage: float,
    length: int = 10
) -> str:

    percentage = max(
        0.0,
        min(100.0, percentage)
    )

    filled = int(
        length * percentage / 100
    )

    empty = length - filled

    return (
        "━" * filled
        + "░" * empty
    )

async def update_progress(
    message,
    download_status="⏳",
    processing_status="⏳",
    upload_status="⏳",
    finished=False,
    duration=None,
    download_percentage=None
):
    """
    Update the single persistent processing status message.
    """

    if download_percentage is not None:

        progress_bar = create_progress_bar(
            download_percentage
        )

        download_line = (
            f"  {download_status} Downloading audio "
            f"┃ {progress_bar} "
            f"{download_percentage:.0f}%"
        )

    else:

        download_line = (
            f"  {download_status} Downloading audio"
        )

    text = (
        "👩‍🔬 *Request processing:*\n\n"
        f"{download_line}\n"
        f"  {processing_status} Processing and optimization\n"
        f"  {upload_status} Uploading to Telegram"
    )

    if finished:

        if duration is not None and duration > 0:

            minutes = duration // 60
            seconds = duration % 60

            duration_text = (
                f"{minutes:02d}:{seconds:02d}"
            )

            text += (
                "\n\n"
                "🎵 *Download completed!*\n"
                f"⏱ Duration: `{duration_text}`"
            )

        else:

            text += (
                "\n\n"
                "🎵 *Download completed!*"
            )

    try:

        await message.edit_text(
            text,
            parse_mode="Markdown"
        )

    except BadRequest as error:

        if "Message is not modified" not in str(error):

            logger.warning(
                "Could not update status message: %s",
                error
            )



async def download(
    update: Update,
    context: CallbackContext
) -> None:

    user = update.effective_user
    message = update.effective_message

    if not message:
        return

    url = message.text.strip()

    # =========================================================
    # Register user
    # =========================================================

    await getUser(
        user.id,
        user.username
    )

    # =========================================================
    # Status message
    # =========================================================

<<<<<<< Updated upstream
    status_message = await message.reply_text(
        "🔎 Checking your request..."
=======
    status_message = await update.message.reply_text(
        "👩‍🔬 *Request processing:*\n\n"
        "  🔄 Downloading audio ┃ ░░░░░░░░░░ 0%\n"
        "  ⏳ Processing and optimization\n"
        "  ⏳ Uploading to Telegram",
        parse_mode="Markdown"
>>>>>>> Stashed changes
    )

    # =========================================================
    # Progress queue
    # =========================================================

    progress_queue = asyncio.Queue()

    def download_progress_callback(percentage):
        try:
            progress_queue.put_nowait(
                float(percentage)
            )
        except Exception as e:
            logger.debug(
                "Could not queue download progress: %s",
                e
            )

    db = None
    user_db = None

    try:

        # =====================================================
        # Downloader
        # =====================================================

        songs = DownloadYB(url)

        # IMPORTANTE:
        # El callback debe asignarse ANTES de ejecutar
        # songs.download()

        songs.progress_callback = (
            download_progress_callback
        )

        songs.regexUrl()
        songs.generateYbUrl()

        # =====================================================
        # User database
        # =====================================================

        user_db = usrdatabase()

        # -----------------------------------------------------
        # Reset individual user limit
        # -----------------------------------------------------

        reset_result, reset_msg = (
            user_db.reset_daily_song_counts(
                user.id,
                user.username
            )
        )

        if reset_result:

            await status_message.edit_text(
                f"🔄 {reset_msg}"
            )

            await asyncio.sleep(1)

<<<<<<< Updated upstream
        # -----------------------------------------------------
        # Check whether user can download
        #
        # This checks:
        #
        # - premium
        # - admin
        # - subscribed
        # - individual free limit
        # - global free limit
        #
        # BUT does NOT consume the limit.
        # -----------------------------------------------------

        can_request, request_message = (
=======
            await update_progress(
                status_message,
                download_status="🔄",
                processing_status="⏳",
                upload_status="⏳",
                download_percentage=0
            )

        can_request, msg_request = (
>>>>>>> Stashed changes
            user_db.can_request_song(
                user.id
            )
        )

        if not can_request:

            await status_message.edit_text(
                f"🚫 {request_message}"
            )

            return

        # =====================================================
        # YouTube database
        # =====================================================

        db = ytdatabase()

        exists = db.isOntheDatabase(
            songs.video_id
        )

        # =====================================================
<<<<<<< Updated upstream
        # DOWNLOAD NEW SONG
=======
        # Download
>>>>>>> Stashed changes
        # =====================================================

        if not exists:

<<<<<<< Updated upstream
            # -------------------------------------------------
            # Find client
            # -------------------------------------------------

            await status_message.edit_text(
                "🔎 Finding a compatible YouTube client..."
            )

            # -------------------------------------------------
            # Download
            # -------------------------------------------------

            await status_message.edit_text(
                "⬇️ Downloading the song..."
=======
            await update_progress(
                status_message,
                download_status="🔄",
                processing_status="⏳",
                upload_status="⏳",
                download_percentage=0
            )

            # Ejecutar la descarga en otro thread para no
            # bloquear el event loop de Telegram.
            download_task = asyncio.create_task(
                asyncio.to_thread(
                    songs.download
                )
>>>>>>> Stashed changes
            )

            last_percentage = -1

            if not final_file:

                raise RuntimeError(
                    "DownloadYB returned no file."
                )

            final_file = Path(
                final_file
            )

            if not final_file.exists():

                raise FileNotFoundError(
                    f"Downloaded file does not exist: "
                    f"{final_file}"
                )

            # -------------------------------------------------
<<<<<<< Updated upstream
            # Save metadata in database
            # -------------------------------------------------

            await status_message.edit_text(
                "💾 Saving song information..."
=======
            # Monitorizar progreso
            # -------------------------------------------------

            while not download_task.done():

                try:

                    percentage = await asyncio.wait_for(
                        progress_queue.get(),
                        timeout=0.5
                    )

                    percentage = max(
                        0.0,
                        min(100.0, float(percentage))
                    )

                    # Actualizar cada 5%
                    rounded_percentage = (
                        int(percentage) // 5
                    ) * 5

                    if rounded_percentage != last_percentage:

                        last_percentage = (
                            rounded_percentage
                        )

                        await update_progress(
                            status_message,
                            download_status="🔄",
                            processing_status="⏳",
                            upload_status="⏳",
                            download_percentage=(
                                rounded_percentage
                            )
                        )

                except asyncio.TimeoutError:

                    continue

            # -------------------------------------------------
            # Obtener resultado
            # -------------------------------------------------

            final_file = await download_task

            # -------------------------------------------------
            # Descargar terminado
            # -------------------------------------------------

            await update_progress(
                status_message,
                download_status="✅",
                processing_status="🔄",
                upload_status="⏳",
                download_percentage=100
>>>>>>> Stashed changes
            )

            # =================================================
            # Duration
            # =================================================

            duration = (
                songs.songs_data.duration
            )

            logger.info(
                "Duration for database: %s",
                duration
            )

            # =================================================
            # Save information
            # =================================================

            db.insertData(
                songs.songs_data.title,
                songs.songs_data.artist,
                songs.video_id,
                duration,
                songs.songs_data.thumbalImg
            )

        # =====================================================
        # SONG ALREADY EXISTS
        # =====================================================

        else:

            # =================================================
            # Song already exists
            # =================================================

            final_file = None

<<<<<<< Updated upstream
            await status_message.edit_text(
                "📚 Song already exists in the database."
=======
            await update_progress(
                status_message,
                download_status="✅",
                processing_status="🔄",
                upload_status="⏳",
                download_percentage=100
>>>>>>> Stashed changes
            )

            await asyncio.sleep(0.5)

        # =====================================================
        # Get metadata from database
        # =====================================================

        is_on_db, result = (
            db.verifyURL(
                songs.video_id
            )
        )

        if not is_on_db:

            await status_message.edit_text(
                "❌ Error retrieving song information."
            )

            return

        (
            _,
            title_name,
            artist_name,
            id_video,
            duration,
            thumbnail_url
        ) = result

        # =====================================================
        # Find audio
        # =====================================================

<<<<<<< Updated upstream
        await status_message.edit_text(
            "🔎 Locating the audio file..."
        )

=======
>>>>>>> Stashed changes
        supported_formats = {
            ".m4a",
            ".mp3",
            ".flac"
        }

        audio_path = None

        # -----------------------------------------------------
<<<<<<< Updated upstream
        # If we downloaded it during this request,
        # use the exact file.
=======
        # Use file returned by downloader
>>>>>>> Stashed changes
        # -----------------------------------------------------

        if final_file:

            if final_file.exists():

                audio_path = final_file

        # -----------------------------------------------------
<<<<<<< Updated upstream
        # If it already existed in DB, search Songs/
=======
        # Search Songs directory
>>>>>>> Stashed changes
        # -----------------------------------------------------

        if audio_path is None:

            songs_dir = Path("Songs")

            if songs_dir.exists():

<<<<<<< Updated upstream
                # -------------------------------------------------
                # First: try YouTube ID
                # -------------------------------------------------

=======
                # First search by YouTube ID
>>>>>>> Stashed changes
                for path in songs_dir.rglob("*"):

                    if not path.is_file():
                        continue

                    if (
<<<<<<< Updated upstream
                        path.suffix.lower()
                        not in supported_formats
=======
                        path.is_file()
                        and path.suffix.lower()
                        in supported_formats
                        and id_video in path.name
>>>>>>> Stashed changes
                    ):
                        continue

<<<<<<< Updated upstream
                    if id_video in path.name:

                        audio_path = path

                        break

                # -------------------------------------------------
                # Second: try exact title
=======
                        audio_path = path
                        break

                # -------------------------------------------------
                # Fallback: search by title
>>>>>>> Stashed changes
                # -------------------------------------------------

                if audio_path is None:

                    normalized_title = (
                        title_name
                        .strip()
                        .lower()
                    )

                    for path in songs_dir.rglob("*"):

                        if not path.is_file():
                            continue

                        if (
<<<<<<< Updated upstream
                            path.suffix.lower()
                            not in supported_formats
                        ):
                            continue

                        if (
                            path.stem
                            .strip()
                            .lower()
=======
                            path.is_file()
                            and path.suffix.lower()
                            in supported_formats
                            and path.stem.strip().lower()
>>>>>>> Stashed changes
                            == normalized_title
                        ):

                            audio_path = path
<<<<<<< Updated upstream

                            break

=======
                            break

>>>>>>> Stashed changes
        # =====================================================
        # File not found
        # =====================================================

        if audio_path is None:

            await status_message.edit_text(
                "❌ No audio file was found for this song."
            )

            return

        # =====================================================
        # Processing
        # =====================================================

        await update_progress(
            status_message,
            download_status="✅",
            processing_status="🔄",
            upload_status="⏳",
            download_percentage=100
        )

        # =====================================================
        # Get REAL duration
        # =====================================================

        try:

            from mutagen import File

            audio_info = File(
                str(audio_path)
            )

            if (
                audio_info
                and audio_info.info
            ):

                duration = int(
                    audio_info.info.length
                )

                logger.info(
                    "Telegram duration: %s",
                    duration
                )

        except Exception as e:

            logger.warning(
                "Could not read final duration: %s",
                e
            )

        # =====================================================
        # Thumbnail
        # =====================================================

        thumbnail_path = None

        if thumbnail_url:

<<<<<<< Updated upstream
            await status_message.edit_text(
                "🖼️ Downloading the thumbnail..."
            )

=======
>>>>>>> Stashed changes
            thumbnail_path = await asyncio.to_thread(
                songs.download_thumbnail,
                thumbnail_url,
                id_video
            )

        # =====================================================
<<<<<<< Updated upstream
        # Sending
=======
        # Upload
>>>>>>> Stashed changes
        # =====================================================

        await update_progress(
            status_message,
            download_status="✅",
            processing_status="✅",
            upload_status="🔄",
            download_percentage=100
        )

        with audio_path.open("rb") as audio:

            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=audio,
                title=title_name,
                performer=artist_name,
                duration=duration,
                thumbnail=(
                    thumbnail_path
                    if thumbnail_path
                    else None
                ),
                caption=(
                    "🎵 Downloaded from YouTube\n"
                    "🤖 @songytbbot"
                )
            )

        # =====================================================
        # IMPORTANT:
        #
        # Only register the request AFTER Telegram
        # successfully sends the audio.
        #
        # Premium/admin/subscribed:
        #     Does NOT consume global free quota.
        #
        # Free:
        #     +1 personal request
        #     +1 global request
        # =====================================================

        success, request_result = (
            user_db.request_song(
                user.id
            )
        )

        if not success:

            logger.warning(
                "Song was sent but request registration "
                "failed for user %s: %s",
                user.id,
                request_result
            )

        # =====================================================
        # Finished
        # =====================================================

        await status_message.edit_text(
            "👩‍🔬 *Request processing:*\n\n"
            "  ✅ Downloading audio ┃ ━━━━━━━━━━ 100%\n"
            "  ✅ Processing and optimization\n"
            "  ✅ Uploading to Telegram\n\n"
            f"🎵 *{title_name}*\n"
            f"👤 {artist_name}\n"
            f"⏱ *Duration:* "
            f"{duration // 60:02d}:{duration % 60:02d}",
            parse_mode="Markdown"
        )

        await asyncio.sleep(2)

    # =========================================================
    # Network error
    # =========================================================

    # =========================================================
    # NETWORK ERROR
    # =========================================================

    except (
        httpx.HTTPError,
        httpx.ConnectError,
        httpcore.ConnectError
    ) as e:

        logger.error(
            "Network error processing %s: %s",
            url,
            e
        )

        try:

            await status_message.edit_text(
<<<<<<< Updated upstream
                "🌐 Connection error while processing "
                "the song. Please try again later."
=======
                "👩‍🔬 *Request processing:*\n\n"
                "  ❌ Downloading audio\n"
                "  ⏳ Processing and optimization\n"
                "  ⏳ Uploading to Telegram\n\n"
                "🌐 Connection error. "
                "Please try again.",
                parse_mode="Markdown"
>>>>>>> Stashed changes
            )

        except Exception:
            pass

    # =========================================================
<<<<<<< Updated upstream
    # LIMIT / VALIDATION ERRORS
    # =========================================================

    except ValueError as e:

        logger.warning(
            "Invalid request from user %s: %s",
            user.id,
            e
        )

        try:

            await status_message.edit_text(
                "❌ The YouTube link is not valid."
            )

        except Exception:

            pass

    # =========================================================
    # GENERAL ERROR
=======
    # Unexpected error
>>>>>>> Stashed changes
    # =========================================================

    except Exception as e:

        logger.exception(
            "Unexpected error processing %s",
            url
        )

        try:

            await status_message.edit_text(
<<<<<<< Updated upstream
                "❌ An error occurred while processing "
                "the song. Please try again later."
=======
                "👩‍🔬 *Request processing:*\n\n"
                "  ❌ Downloading audio\n"
                "  ❌ Processing and optimization\n"
                "  ❌ Uploading to Telegram\n\n"
                "❌ An error occurred while "
                "processing the song.",
                parse_mode="Markdown"
>>>>>>> Stashed changes
            )

        except Exception:
            pass

    # =========================================================
<<<<<<< Updated upstream
    # CLOSE DATABASES
=======
    # Cleanup
>>>>>>> Stashed changes
    # =========================================================

    finally:

        if user_db:

            try:
                user_db.close()

            except Exception:

                pass

        if db:

            try:
                db.close()

            except Exception:

                pass


def main(TELEGRAM_TOKEN):
    try:
        application = Application.builder().token(str(TELEGRAM_TOKEN)).post_init(changeCommands).read_timeout(40).write_timeout(180).connect_timeout(600).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("myid", yourid_command))
        application.add_error_handler(error_handler)
        job_queue = application.job_queue
        job_queue.run_daily(
            messageToUser,
            time(hour=18, minute=00, second=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
        application.run_polling(drop_pending_updates=True, close_loop=False)
    except httpx.HTTPError as e:
        logger.error(f"HTTP error: {e}")
    except (httpx.RequestError, httpx.TransportError, httpx.TimeoutException, 
            httpx.ConnectError, httpx.ReadError, httpx.WriteTimeout, 
            httpx.PoolTimeout, httpx.NetworkError, httpx.ConnectTimeout,
            httpcore.ProtocolError, httpcore.ProxyError, httpcore.ConnectTimeout, 
            httpcore.ReadTimeout, httpcore.WriteTimeout, 
            httpcore.ConnectError) as e:
        logger.error(f"HTTPX/HTTPCORE-related error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
