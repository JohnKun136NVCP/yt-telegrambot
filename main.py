from ytbot import main
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env file

TELEGRAM_TOKEN = os.getenv("TOKEN")

if __name__ == "__main__":
    main(TELEGRAM_TOKEN)