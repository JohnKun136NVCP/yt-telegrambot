import logging
import time
import os
from getSongs import downloadSongsYb
from getSongs import dataBase
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hi, I'm a bot that can download songs from YouTube. Send me a link to a YouTube video and I'll send you the audio file.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"How to use:\n 1. Go to the page with an interesting video (for example - https://www.youtube.com/watch?v=pIGMmlXApUE). \n2. Click the Share button. \n3. In the menu that opens, select - Telegram. \n4. When Telegram opens, click on the chat with the blue dude! Or just paste the link to the video into the chat and send it to the bot.")

async def changeCommands(application: Application) -> None:
    command = [BotCommand("start", "Start the bot"), BotCommand("help", "Get help")]
    await application.bot.set_my_commands(command)
    await application.bot.set_chat_menu_button()

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text
    try:
        songs = downloadSongsYb(str(url))
        songs.regexUrl()
        db = dataBase()
        songs.regexUrl()
        songs.generateYbUrl()
        if not db.isOntheDatabase(songs.id_url):
            songs.download()
            db.insertData(songs.title, songs.artist, songs.id_url)
        result = db.verifyURL(songs.id_url)
        if result:
            titleName, artistName = result[1], result[2]
            match_files = []
            current_path = os.getcwd()
            new_dir_path = os.path.join(current_path, "Songs/")
            for root, dirs, files in os.walk(new_dir_path):
                for file in files:
                   if file.endswith(".m4a") and titleName in file:
                       match_files.append(os.path.join(root, file))
                       file_root, file_ext = os.path.splitext(file)
            if match_files:
                for audio_path in match_files:
                    with open(audio_path, "rb") as audio:

                        await update.message.reply_audio(
                                    audio=audio_path,
                                    filename=file_root,
                                    title=titleName,
                                    performer=artistName,
                                    caption=f"Downloaded from YouTube\n @songytbbot",
                                )
    except:
        await update.message.reply_text("Sorry, an error occurred while processing the request. Please try again later.")

def main(TELEGRAM_TOKEN):
    application = Application.builder().token(str(TELEGRAM_TOKEN)).post_init(changeCommands).read_timeout(7).get_updates_connect_timeout(42).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.run_polling()