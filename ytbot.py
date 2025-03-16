import logging
import time
import os
from difflib import SequenceMatcher as sm
from getSongs import downloadSongsYb
from getSongs import dataBase
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Hi, I'm a bot that can download songs from YouTube. Send me a link to a YouTube video and I'll send you the audio file.")

async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(f"How to use:\n 1. Go to the page with an interesting video (for example - https://www.youtube.com/watch?v=pIGMmlXApUE). \n2. Click the Share button. \n3. In the menu that opens, select - Telegram. \n4. When Telegram opens, click on the chat with the blue dude! Or just paste the link to the video into the chat and send it to the bot.")

async def changeCommands(application: Application) -> None:
    command = [BotCommand("start", "Start the bot"), BotCommand("help", "Get help")]
    await application.bot.set_my_commands(command)
    await application.bot.set_chat_menu_button()

async def download(update: Update, context: CallbackContext) -> None:
    try:
        url = update.message.text
        songs = downloadSongsYb(str(url))
        songs.regexUrl()
        db = dataBase()
        songs.regexUrl()
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
                    if file.endswith(".m4a"):
                        similarity_ratio = sm(None, file, titleName+".m4a").ratio()
                        if similarity_ratio > 0.9:  # Match threshold
                            match_files.append(os.path.join(root, file))
            # Send matches to the user
            if match_files:
                for audio_path in match_files:
                    with open(audio_path, "rb") as audio:
                        thumbal = songs.download_thumbnail(thumbal)
                        await context.bot.send_audio(
                            chat_id=update.message.chat_id,
                            audio=audio_path,
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
        await update.message.reply_text(
            f"Sorry, an error occurred while processing the request. Details: {str(e)}"
        )

def main(TELEGRAM_TOKEN):
    try:
        application = Application.builder().token(str(TELEGRAM_TOKEN)).post_init(changeCommands).read_timeout(7).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
        application.run_polling()
    except Exception as e:pass