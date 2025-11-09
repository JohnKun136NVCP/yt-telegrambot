"""
ytbot.py
A Telegram bot for downloading songs from YouTube and sending them to users as audio files. 
The bot manages user registration, handles YouTube song downloads, maintains a user database, 
and sends daily messages or quotes to all registered users.

Modules:

    - httpx, httpcore: For HTTP requests and error handling.
    - logging, warnings: For logging and warning management.
    - os, sqlite3: For file and database operations.
    - difflib: For filename similarity matching.
    - getSongs: For downloading songs from YouTube.
    - messages: For managing messages and quotes.
    - databases: For user and YouTube song database management.
    - datetime: For scheduling daily messages.
    - telegram, telegram.ext: For Telegram bot API integration.

Functions:

    async def getUser(id, username):
        Registers a user in the database if not already present and reorders user table IDs.
    async def messageToUser(context):
        Sends a daily message or quote to all registered users. Removes users who have blocked the bot.
    async def start(update, context):
        Handles the /start command. Registers the user and sends a welcome message.
    async def help_command(update, context):
        Handles the /help command. Registers the user and sends usage instructions.
    async def changeCommands(application):
        Sets the bot's command list and chat menu button.
    async def download(update, context):
        Handles incoming messages with YouTube links. Downloads the song, stores metadata, 
        and sends the audio file to the user if found or downloaded.
        Initializes and runs the Telegram bot application, sets up handlers, and schedules daily jobs.

Logging:
    
    Logs errors and important events to 'botlogs.log'.

Error Handling:

    Handles database, HTTP, and Telegram API errors gracefully, logging them for debugging.

Usage:

    Import this module and call main(TELEGRAM_TOKEN) with your bot's token to start the bot.
"""

import httpx
import httpcore
import logging
import warnings
import os
import sqlite3
from difflib import SequenceMatcher as sm
from getSongs import downloadSongsYb
from messages import messagesAndQuotes
from databases import ytdatabase
from databases import usrdatabase
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
    #filename="botlogs.log",
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger('httpx').setLevel(logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger('httpcore').setLevel(logging.INFO)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.ERROR)
logging.getLogger('httpcore').setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)




async def getUser(id,username):
    try:
        userDatabase = usrdatabase()
        userDatabase.add_user(id,username,0,False,'unsubscribed')
        userDatabase.close()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

async def messageToUser(context: ContextTypes.DEFAULT_TYPE):
    info = messagesAndQuotes()
    try:
            conn = sqlite3.connect("users.db")
            cursor = conn.cursor()

            # Filted non-premium users
            cursor.execute("""
                SELECT telegram_id 
                FROM users 
                WHERE (premium = 0 OR premium IS NULL)
                AND (type_user IS NULL OR LOWER(type_user) = 'unsubscribed')
            """)
            result = cursor.fetchall()

            if not result:
                logger.info("No hay usuarios no premium registrados.")
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
                            logger.error(f"Error enviando mensaje a {idUser}: {e}")
                            # If user has blocked the bot or other error, remove from database
                            cursor.execute('DELETE FROM users WHERE telegram_id = ?', (idUser,))
                            conn.commit()

                # If no custom message, send the quote of the day
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
    photo="photo_2.png",
    caption="""
    🎧 *Unlock Full Access \\- Support the Project*  
    🚀 _Unlimited downloads \\(if YouTube allows it\\)_  
    ⏳ _No time restrictions_

    🆓 *Free Version Limitations:*  
    ⛔ Max *3 songs per day*  
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

async def download(update: Update, context: CallbackContext) -> None:
    sopported_formats = [".m4a", ".mp3", ".flac"]
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    url = update.message.text
    try:
        songs = downloadSongsYb(str(url))
        songs.regexUrl()
        db = ytdatabase()
        # Create user database instance
        user_db = usrdatabase()
        # To try to reset daily song counts if needed
        reset_result, reset_msg = user_db.reset_daily_song_counts(user['id'], user['username'])
        if reset_result:
            await update.message.reply_text(f"🔄 {reset_msg}")
        if not reset_result:
            logger.info(f"No reset needed for user {user['username']}: {reset_msg}")
        can_request, msg_request = user_db.can_request_song(user['id'])
        if not can_request:
            await update.message.reply_text(f"🚫 {msg_request}")
            user_db.close()
            return
        user_db.registerTimeRequest(user['id'])
        user_db.close()
        
        songs.generateYbUrl()
        # Check if the song exists in the database
        if not db.isOntheDatabase(songs.id_url):
            songs.download()
            db.insertData(
                songs.songsData.title,
                songs.songsData.artist,
                songs.id_url,
                songs.songsData.duration,
                songs.songsData.thumbalImg
            )
            isOnDB, result = db.verifyURL(songs.id_url)
            if isOnDB:
                titleName, artistName, duration, thumbal = (
                    result[1],
                    result[2],
                    result[4],
                    result[5],
                )
                # Search for matching files in the "Songs/" directory
                match_files = []
                current_path = os.getcwd()
                new_dir_path = os.path.join(current_path, "Songs/")
            for root, dirs, files in os.walk(new_dir_path):
                for file in os.listdir(root):
                    for ext in sopported_formats:
                        if file.endswith(ext):
                            similarity_ratio = sm(None, file, titleName + ext).ratio()
                            if similarity_ratio > 0.97:match_files.append(os.path.join(root, file))
            # Send matches to the user
            if match_files:
                for audio_path in match_files:
                    with open(audio_path, "rb") as audio:
                        thumbal = songs.download_thumbnail(thumbal)
                        await context.bot.send_audio(
                            chat_id=update.message.chat_id,
                            audio=audio,
                            title=titleName,
                            performer=artistName,
                            duration=duration,
                            thumbnail=thumbal,
                            caption=f"Downloaded from YouTube\n @songytbbot"
                        )
                songs.cleanTempdir(thumbal)
                db.close()
                user_db = usrdatabase()
                user_db.request_song(user['id'])
                user_db.close()
            else:
                await update.message.reply_text(
                    "Sorry, no matches were found for this song."
                )
    except Exception as e:
        # Error handling
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Sorry, an error occurred while processing the request. Try again later.")

def main(TELEGRAM_TOKEN):
    try:
        application = Application.builder().token(str(TELEGRAM_TOKEN)).post_init(changeCommands).read_timeout(40).write_timeout(180).connect_timeout(600).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("subscribe", subscribe_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("myid", yourid_command))
        job_queue = application.job_queue
        job_queue.run_daily(
            messageToUser,
            time(hour=18, minute=00, second=0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
        application.run_polling()
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
