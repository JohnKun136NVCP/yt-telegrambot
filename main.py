from dotenv import load_dotenv

from src.bot import main

load_dotenv()  # Load environment variables from a .env file, if present.

if __name__ == "__main__":
    # src.bot.main() loads and validates configuration itself (src/config.py)
    # and exits with a clear message if something required (like TOKEN) is
    # missing, instead of the bot crashing deep inside python-telegram-bot.
    main()
