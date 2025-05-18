"""
ytbot.py
A Telegram bot for downloading songs from YouTube and sending them to users as audio files. 
The bot manages user registration, handles YouTube link submissions, downloads and stores songs, 
and periodically sends messages or quotes to registered users.
Modules and Features:
- User management and registration in a SQLite database.
- Downloading and caching of YouTube audio files in various formats.
- Sending audio files to users with metadata and thumbnails.
- Periodic messaging to all users (e.g., quotes or announcements).
- Command handlers for /start and /help.
- Logging of bot activity and error handling.
- Integration with external modules for song downloading, message management, and database operations.
Dependencies:
- httpx, httpcore: For HTTP requests and error handling.
- logging, warnings: For logging and warning management.
- os, sqlite3: For file and database operations.
- difflib: For file name similarity matching.
- telegram, telegram.ext: For Telegram bot API integration.
- getSongs, messages, databases: Custom modules for song downloading, message management, and database operations.
Main Functions:
- getUser: Registers or updates a user in the database.
- messageToUser: Sends messages or quotes to all registered users.
- start: Handles the /start command and greets the user.
- help_command: Handles the /help command and provides usage instructions.
- changeCommands: Sets bot commands and menu buttons.
- download: Handles YouTube link submissions, downloads audio, and sends it to the user.
- main: Initializes and runs the Telegram bot application.
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
    filename="botlogs.log",
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
        userDatabase = usrdatabase(id,username)
        userDatabase.isOnTableOrInsert()
        userDatabase.reorderIdUserTable()
        userDatabase.close()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

async def messageToUser(context: ContextTypes.DEFAULT_TYPE):
    info = messagesAndQuotes()
    try:
        connect = sqlite3.connect("users.db")
        cursor = connect.cursor()
        cursor.execute('SELECT telegram_id FROM users')
        result = cursor.fetchall()
        if result and os.path.exists(info.userMessage):
            idUsers = [row[0] for row in result]
            if info.showMessageUser() != "":
                for idUser in idUsers:
                        try:
                            await context.bot.send_message(chat_id=idUser, text=f'{info.showMessageUser()}',parse_mode="MarkdownV2")
                        except (BadRequest, Forbidden) as e:
                            logger.error(f"Error sending message to user {idUser}: {e}")
                            # Remove the user from the database if they are blocked
                            cursor.execute('DELETE FROM users WHERE telegram_id = ?', (idUser,))
                            connect.commit()
                            
            elif info.showMessageUser()== "" and idUsers:
                info.get_quote()
                for idUser in idUsers:
                    try:
                        await context.bot.send_message(chat_id=idUser, text=f'Quote of the day:\n{info.quouteString}')
                    except (BadRequest, Forbidden) as e:
                        logger.error(f"Error sending message to user {idUser}: {e}")
                        # Remove the user from the database if they are blocked
                        cursor.execute('DELETE FROM users WHERE telegram_id = ?', (idUser,))
                        connect.commit()      
    except sqlite3.Error as e:logger.error(f"Database error: {e}")
async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text("Hi {}, I'm a bot that can download songs from YouTube. Send me a link to a YouTube video and I'll send you the audio file.".format(user['username']))

async def help_command(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text(f"How to use:\n 1. Go to the page with an interesting video (for example - https://www.youtube.com/watch?v=widZEAJc0QM). \n2. Click the Share button. \n3. In the menu that opens, select - Telegram. \n4. When Telegram opens, click on the chat with the blue dude! Or just paste the link to the video into the chat and send it to the bot.\n Do you have any questions? Please contact the developer @KiyotakaKatzut01.")

async def changeCommands(application: Application) -> None:
    command = [BotCommand("start", "Start the bot"), BotCommand("help", "Get help")]
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
                            if similarity_ratio > 0.9:match_files.append(os.path.join(root, file))
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
        application.add_handler(CommandHandler("help", help_command))
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
            httpcore.ReadTimeout, httpcore.WriteTimeout, httpcore.CloseError, 
            httpcore.SocketError) as e:
        logger.error(f"HTTPX/HTTPCORE-related error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")