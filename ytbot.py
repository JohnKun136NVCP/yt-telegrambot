"""
This script implements a Telegram bot that allows users to download audio files from YouTube videos. 
It includes functionalities for user management, message broadcasting, and audio file handling.
Modules:
- logging: For logging bot activities.
- os: For file and directory operations.
- sqlite3: For database interactions.
- difflib: For comparing file names to find matches.
- datetime: For time-related operations.
- telegram: For interacting with the Telegram Bot API.
- telegram.ext: For handling bot commands and messages.
Functions:
- getUser(id, username): Ensures the user is in the database or inserts them if not.
- messageToUser(context): Sends a weekly message or quote to all users in the database.
- start(update, context): Handles the /start command, welcoming the user and explaining the bot's functionality.
- help_command(update, context): Handles the /help command, providing instructions on how to use the bot.
- changeCommands(application): Sets the bot's commands and chat menu button.
- download(update, context): Handles YouTube video links sent by users, downloads the audio, and sends it back to the user.
- main(TELEGRAM_TOKEN): Initializes and runs the bot, setting up handlers and scheduling weekly messages.
Classes and External Dependencies:
- messagesAndQuotes: Handles messages and quotes for users.
- downloadSongsYb: Manages YouTube audio downloading.
- ytdatabase: Handles YouTube-related database operations.
- usrdatabase: Manages user-related database operations.
Logging:
- Logs bot activities to a file named "botlogs.log".
- Suppresses warnings from the "httpx" library.
Job Queue:
- Schedules a weekly task to send messages or quotes to users.
Error Handling:
- Basic error handling is implemented to prevent the bot from crashing on exceptions.
"""
import logging
import os
import sqlite3
from difflib import SequenceMatcher as sm
from getSongs import downloadSongsYb
from messages import messagesAndQuotes
from databases import ytdatabase
from databases import usrdatabase
from datetime import time
from telegram import Update, BotCommand, Bot
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

logging.basicConfig(
    filename="botlogs.log",
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def getUser(id,username):
    userDatabase = usrdatabase(id,username)
    userDatabase.isOnTableOrInsert()
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
                        await context.bot.send_message(chat_id=idUser, text=f'{info.showMessageUser()}',parse_mode="MarkdownV2")
            elif info.get_quote()== "" and idUsers:
                info.get_quote()
                for idUser in idUsers:
                    await context.bot.send_message(chat_id=idUser, text=f'Quote of the Week:\n{info.quouteString}')
    except sqlite3.Error as e:pass
async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text("Hi {}, I'm a bot that can download songs from YouTube. Send me a link to a YouTube video and I'll send you the audio file.".format(user['username']))

async def help_command(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    await getUser(user['id'],user['username'])
    await update.message.reply_text(f"How to use:\n 1. Go to the page with an interesting video (for example - https://www.youtube.com/watch?v=pIGMmlXApUE). \n2. Click the Share button. \n3. In the menu that opens, select - Telegram. \n4. When Telegram opens, click on the chat with the blue dude! Or just paste the link to the video into the chat and send it to the bot.")

async def changeCommands(application: Application) -> None:
    command = [BotCommand("start", "Start the bot"), BotCommand("help", "Get help")]
    await application.bot.set_my_commands(command)
    await application.bot.set_chat_menu_button()

async def download(update: Update, context: CallbackContext) -> None:
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
                for file in files:
                    if file.endswith(".flac"):
                        similarity_ratio = sm(None, file, titleName+".flac").ratio()
                        if similarity_ratio > 0.9:  # Match threshold
                            match_files.append(os.path.join(root, file))
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
            else:
                await update.message.reply_text(
                    "Sorry, no matches were found for this song."
                )

    except Exception as e:
        # Error handling
        await update.message.reply_text(f"Sorry, an error occurred while processing the request.")

def main(TELEGRAM_TOKEN):
    try:
        application = Application.builder().token(str(TELEGRAM_TOKEN)).post_init(changeCommands).read_timeout(7).write_timeout(29).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        job_queue = application.job_queue
        job_queue.run_repeating(
            messageToUser,
            interval=604800,
            first=4
        )
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
        application.run_polling()
    except Exception as e:pass
