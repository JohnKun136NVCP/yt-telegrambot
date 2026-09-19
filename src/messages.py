"""User-facing texts and the daily quote service.

All texts use Telegram's HTML parse mode. Dynamic values MUST go through
``html.escape``: with the old Markdown mode a quote containing ``_`` or ``*``
could make Telegram reject the whole message.
"""

import html
import random
from dataclasses import dataclass
from datetime import date

import requests

from src.logging_utils import get_file_logger

logger = get_file_logger(__name__, "quotes.log")


# =============================================================================
# Quotes
# =============================================================================

# One header emoji per weekday (Monday = 0).
_WEEKDAY_EMOJI = ("🌱", "🔥", "💡", "🌊", "🚀", "🌈", "☀️")

# Used only when the API is down or rate limited, so users always get a quote.
_FALLBACK_QUOTES = (
    ("The journey of a thousand miles begins with a single step.", "Lao Tzu"),
    ("Fortune favors the bold.", "Virgil"),
    ("The beginning is the most important part of the work.", "Plato"),
    ("It does not matter how slowly you go as long as you do not stop.", "Confucius"),
    ("Knowing yourself is the beginning of all wisdom.", "Aristotle"),
)


@dataclass(frozen=True)
class Quote:
    """A quote and its author."""

    text: str
    author: str

    def format_html(self) -> str:
        """Return the quote as a styled Telegram HTML message."""
        emoji = _WEEKDAY_EMOJI[date.today().weekday()]

        return (
            f"{emoji} <b>Quote of the day</b>\n\n"
            f"<blockquote>“{html.escape(self.text)}”</blockquote>\n"
            f"✍️ <b>{html.escape(self.author)}</b>\n\n"
            "<i>See you tomorrow with a new one ✨</i>"
        )

    def __str__(self) -> str:
        return f"{self.text}\n— {self.author}"


class Quotes:
    """Fetch random quotes from ZenQuotes (with an offline fallback)."""

    API_URL = "https://zenquotes.io/api/random"

    def __init__(self) -> None:
        self.quote: Quote | None = None

    def _fetch_from_api(self) -> Quote | None:
        """Return a quote from ZenQuotes or ``None`` if anything goes wrong."""
        try:
            response = requests.get(self.API_URL, timeout=10)
            response.raise_for_status()
            data = response.json()

        except (requests.RequestException, ValueError) as error:
            logger.error("Error getting quote: %s", error)
            return None

        if not data or not isinstance(data, list):
            logger.warning("ZenQuotes returned an empty response.")
            return None

        text = str(data[0].get("q", "")).strip()
        author = str(data[0].get("a", "")).strip() or "Unknown author"

        # When rate limited, ZenQuotes answers with a "quote" that is really an
        # error notice signed by "zenquotes.io". Never send that to users.
        if not text or author.lower() == "zenquotes.io":
            logger.warning("ZenQuotes returned an unusable quote: %r", text[:80])
            return None

        return Quote(text=text, author=author)

    def get_quote(self, allow_fallback: bool = True) -> Quote | None:
        """Get a random quote.

        This function is blocking (network I/O): call it with
        ``asyncio.to_thread`` from async code.
        """
        quote = self._fetch_from_api()

        if quote is None and allow_fallback:
            text, author = random.choice(_FALLBACK_QUOTES)
            quote = Quote(text=text, author=author)
            logger.info("Using a fallback quote.")

        self.quote = quote
        return quote

    def check_quote(self) -> bool:
        """Return ``True`` if a quote is currently stored."""
        return self.quote is not None


# =============================================================================
# Static texts
# =============================================================================

def start_text(name: str) -> str:
    """Welcome message."""
    return (
        f"👋 <b>Hi {html.escape(name)}!</b>\n\n"
        "I turn YouTube videos into audio files.\n"
        "Send me a link and I'll send you the song 🎧"
    )


HELP_TEXT = (
    "📖 <b>How to use</b>\n\n"
    "1️⃣ Open a video you like on YouTube, for example:\n"
    "<code>https://www.youtube.com/watch?v=widZEAJc0QM</code>\n"
    "2️⃣ Tap <b>Share</b>\n"
    "3️⃣ Choose <b>Telegram</b>\n"
    "4️⃣ Pick the chat with this bot — or just paste the link here\n\n"
    "❓ Questions? Contact the developer @KiyotakaKatzut01"
)

SUBSCRIBE_CAPTION = (
    "🎧 <b>Unlock Full Access — Support the Project</b>\n\n"
    "🚀 <i>Unlimited downloads (if YouTube allows it)</i>\n"
    "⏳ <i>No time restrictions</i>\n\n"
    "🆓 <b>Free version limits</b>\n"
    "⛔ Max <b>1 song per day</b>\n"
    "📜 Daily quotes included, but limited\n\n"
    "💬 <b>Why support?</b>\n"
    "This project is <b>free</b>, clean and safe: no malicious scripts, "
    "no viruses. Because of <b>YouTube's new policies</b> it is getting "
    "harder to maintain. Your support helps me fix bugs and keep it running 💪\n\n"
    "💖 <b>How to support me</b>\n"
    '☕ <a href="https://buymeacoffee.com/johnkun29">Buy Me a Coffee</a>\n'
    '🧡 <a href="https://ko-fi.com/johnkun136nvcp">Ko-fi</a>\n'
    '💻 <a href="https://github.com/sponsors/JohnKun136NVCP">GitHub Sponsors</a>\n\n'
    "📲 <b>How to unlock full access</b>\n"
    "1. Support me on any platform above\n"
    "2. Use /myid to get your Telegram user ID\n"
    "3. Send me your ID and proof of support via /help\n\n"
    "🙏 <b>Thank you!</b> Every bit of help keeps this project growing 🌱"
)