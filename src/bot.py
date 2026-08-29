
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

async def messageToUser(context: ContextTypes.DEFAULT_TYPE):
    try:
        info = Quotes()
        conn = sqlite3.connect("database/users.db")
        cursor = conn.cursor()

        # Filter non-premium users
        cursor.execute("""
            SELECT telegram_id 
            FROM users 
            WHERE (premium = 0 OR premium IS NULL)
            AND (type_user IS NULL OR LOWER(type_user) = 'unsubscribed')
        """)
        result = cursor.fetchall()

        if not result:
            logger.info("There are no non-premium users registered.")
            conn.close()
            return

        non_premium_users = [row[0] for row in result]

        # Check if custom message file exists
        if os.path.exists(info.userMessage):
            # Send custom message to non-premium users
            message_text = info.showMessageUser()
            if message_text:
                for idUser in non_premium_users:
                    try:
                        await context.bot.send_message(
                            chat_id=idUser,
                            text=message_text,
                            parse_mode="MarkdownV2"
                        )
                    except (BadRequest, Forbidden) as e:
                        logger.error(f"Error sending mensaje a {idUser}: {e}")
                        # If user has blocked the bot or other error, remove from database
                        cursor.execute('DELETE FROM users WHERE telegram_id = ?', (idUser,))
                        conn.commit()
                else:
                    info.get_quote()
                    
                    quote_text = f"✨ Quote of the day ✨\n{info.quouteString}"
                    for idUser in non_premium_users:
                        try:
                            await context.bot.send_message(chat_id=idUser, text=quote_text)
                        except (BadRequest, Forbidden) as e:
                            logger.error(f"Error from user {idUser}: {e}")
                            cursor.execute('DELETE FROM users WHERE telegram_id = ?', (idUser,))
                            conn.commit()

            else:
                logger.warning(f"The file {info.userMessage} doesn't exists.")

            conn.close()

    except sqlite3.Error as e:
            logger.error(f"Database error: {e}")

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

async def download(
    update: Update,
    context: CallbackContext
) -> None:

    user = update.effective_user
    url = update.message.text.strip()

    await getUser(
        user.id,
        user.username
    )

    status_message = await update.message.reply_text(
        "🔎 Finding the link..."
    )

    db = None
    user_db = None

    try:

        # =====================================================
        # Create downloader
        # =====================================================

        songs = DownloadYB(url)

        songs.regexUrl()
        songs.generateYbUrl()

        # =====================================================
        # User database
        # =====================================================

        user_db = usrdatabase()

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

            await asyncio.sleep(2)

        can_request, msg_request = (
            user_db.can_request_song(
                user.id
            )
        )

        if not can_request:

            await status_message.edit_text(
                f"🚫 {msg_request}"
            )

            return

        user_db.registerTimeRequest(
            user.id
        )

        # =====================================================
        # YouTube database
        # =====================================================

        db = ytdatabase()

        exists = db.isOntheDatabase(
            songs.video_id
        )

        if not exists:

            # -------------------------------------------------
            # Download
            # -------------------------------------------------

            await status_message.edit_text(
                "🔎 Finding a compatible client..."
            )

            # -------------------------------------------------
            # IMPORTANT:
            #
            # DownloadYB is synchronous.
            # Run it in another thread so Telegram
            # remains responsive.
            # -------------------------------------------------

            await status_message.edit_text(
                "⬇️ Downloading the song..."
            )

            final_file = await asyncio.to_thread(
                songs.download
            )

            # -------------------------------------------------
            # Metadata is already stored in songs_data.
            # -------------------------------------------------

            await status_message.edit_text(
                "💾 Saving information..."
            )

            db.insertData(
                songs.songs_data.title,
                songs.songs_data.artist,
                songs.video_id,
                songs.songs_data.duration,
                songs.songs_data.thumbalImg
            )

        else:

            final_file = None

            await status_message.edit_text(
                "📚 The song is already in the database."
            )

        # =====================================================
        # Get DB information
        # =====================================================

        is_on_db, result = (
            db.verifyURL(
                songs.video_id
            )
        )

        if not is_on_db:

            await status_message.edit_text(
                "❌ Error retrieving song data."
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
        # Find audio file
        # =====================================================

        await status_message.edit_text(
            "🔎 Finding the audio file..."
        )

        supported_formats = {
            ".m4a",
            ".mp3",
            ".flac"
        }

        audio_path = None

        # If this request downloaded the file,
        # we already know exactly which file it is.
        if final_file:

            if final_file.exists():

                audio_path = final_file

        # If it was already in DB, search Songs/.
        if audio_path is None:

            songs_dir = Path("Songs")

            if songs_dir.exists():

                # Prefer exact ID in filename if available.
                for path in songs_dir.rglob("*"):

                    if (
                        path.is_file()
                        and path.suffix.lower()
                        in supported_formats
                    ):

                        if id_video in path.name:

                            audio_path = path
                            break

                # Fallback to title.
                if audio_path is None:

                    normalized_title = (
                        title_name.strip().lower()
                    )

                    for path in songs_dir.rglob("*"):

                        if (
                            path.is_file()
                            and path.suffix.lower()
                            in supported_formats
                        ):

                            if (
                                path.stem.strip().lower()
                                == normalized_title
                            ):

                                audio_path = path
                                break

        if audio_path is None:

            await status_message.edit_text(
                "❌ No se encontró el archivo de audio."
            )

            return

        # =====================================================
        # Thumbnail
        # =====================================================

        thumbnail_path = None

        if thumbnail_url:

            await status_message.edit_text(
                "🖼️ Uploading the thumbnail..."
            )

            thumbnail_path = await asyncio.to_thread(
                songs.download_thumbnail,
                thumbnail_url,
                id_video
            )

        # =====================================================
        # Send audio
        # =====================================================

        await status_message.edit_text(
            "📤 Sending the song..."
        )

        with audio_path.open(
            "rb"
        ) as audio:

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
                    "Downloaded from YouTube\n"
                    "@songytbbot"
                )
            )

        # =====================================================
        # Register request
        # =====================================================

        user_db.request_song(
            user.id
        )

        # =====================================================
        # Finished
        # =====================================================

        await status_message.edit_text(
            "✅ Song sent successfully!"
        )

        await asyncio.sleep(3)

        try:

            await status_message.delete()

        except BadRequest:

            pass

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
                "🌐 Connection error. "
                "Please try again."
            )

        except Exception:

            pass

    except Exception as e:

        logger.exception(
            "Unexpected error processing %s",
            url
        )

        try:

            await status_message.edit_text(
                "❌ An error occurred while processing "
                "the song. Please try again."
            )

        except Exception:

            pass

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
