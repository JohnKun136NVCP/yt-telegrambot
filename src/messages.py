import logging
import requests


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:

    handler = logging.FileHandler(
        "logs/quotes.log"
    )

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)


class Quotes:
    """
    Get and manage random quotes from ZenQuotes.
    """

    API_URL = (
        "https://zenquotes.io/api/random"
    )

    def __init__(self):
        self.quote = {}

    def get_quote(self):
        """
        Get a random quote from ZenQuotes.

        Returns:
            str | None:
                Quote text with author.
        """

        try:

            response = requests.get(
                self.API_URL,
                timeout=10
            )

            response.raise_for_status()

            data = response.json()

            if not data:

                logger.warning(
                    "ZenQuotes returned an empty response."
                )

                return None

            self.quote = data[0]

            message = self.quote.get(
                "q",
                ""
            ).strip()

            author = self.quote.get(
                "a",
                "Unknown author"
            ).strip()

            if not message:

                logger.warning(
                    "ZenQuotes returned an empty quote."
                )

                return None

            if not author:

                author = "Unknown author"

            return (
                f"{message}\n"
                f"— {author}"
            )

        except requests.exceptions.RequestException as error:

            logger.error(
                "Error getting quote: %s",
                error
            )

            return None

        except ValueError as error:

            logger.error(
                "Invalid JSON returned by ZenQuotes: %s",
                error
            )

            return None

        except Exception as error:

            logger.exception(
                "Unexpected error getting quote: %s",
                error
            )

            return None

    def check_quote(self):
        """
        Check whether a quote is currently stored.
        """

        return bool(self.quote)