from pathlib import Path
import logging
import requests
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
logger.setLevel(logging.WARNING)
logger.setLevel(logging.ERROR)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler = logging.FileHandler("logs/quotes.log")
handler.setFormatter(formatter)
logger.addHandler(handler)


class Quotes:
    """Get and manage user messages and random quotes."""

    API_URL = "https://zenquotes.io/api/random"

    def __init__(self,):
        self.quote = {}

    def get_quote(self):
        """Get a random quote from ZenQuotes."""
        try:
            response = requests.get(self.API_URL, timeout=5)
            response.raise_for_status()

            data = response.json()

            if not data:
                print("The API returned an empty response.")
                return None

            self.quote = data[0]

            message = self.quote.get("q", "")
            author = self.quote.get("a", "Unknown author")

            return f"{message} - {author}"

        except requests.exceptions.RequestException as error:
            print(f"Error to get the quote: {error}")
            return None

    def check_quote(self):
        """Check if exists a stored quote."""
        return bool(self.quote)
