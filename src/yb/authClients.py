"""Find a pytubefix client that can deliver a usable audio stream."""

import re
from typing import Callable

from pytubefix import YouTube

from src.logging_utils import get_file_logger

logger = get_file_logger(__name__, "authClients.log")

_DIGITS_RE = re.compile(r"\d+")


class AuthClient:
    """Try several YouTube clients until one exposes a compatible audio stream."""

    CLIENTS = (
        "ANDROID_VR",
        "WEB",
        "WEB_MUSIC",
        "IOS_MUSIC",
        "IOS",
        "WEB_SAFARI",
        "ANDROID",
        "TV",
    )

    def __init__(
        self,
        url: str,
        on_progress: Callable | None = None,
    ) -> None:
        """
        Args:
            url: Full YouTube watch URL.
            on_progress: pytubefix callback ``(stream, chunk, bytes_remaining)``.
                It must be given to ``YouTube(...)`` here, because streams
                inherit the callback from the object that created them.
        """
        self.url = url
        self.on_progress = on_progress
        self.clients = list(self.CLIENTS)

    @staticmethod
    def _bitrate(stream) -> int:
        """Return the bitrate in kbps.

        ``stream.abr`` is a string such as ``"128kbps"``. Sorting the raw
        strings is wrong ("48kbps" > "128kbps"), so compare real numbers.
        """
        match = _DIGITS_RE.search(stream.abr or "")
        return int(match.group()) if match else 0

    def _best_audio(self, yt: YouTube):
        """Return the best compatible audio stream of ``yt`` (or ``None``)."""
        candidates = [
            stream
            for stream in yt.streams.filter(only_audio=True)
            if not getattr(stream, "is_sabr", False)
        ]

        if not candidates:
            return None

        # Highest bitrate first; on a tie prefer AAC/M4A (cheaper to process).
        return max(
            candidates,
            key=lambda s: (self._bitrate(s), s.mime_type == "audio/mp4"),
        )

    def check_clients(self):
        """Return ``(yt, audio_stream, client_name)`` or ``None``."""
        logger.info("Checking available clients...")

        for client in self.clients:
            logger.info("Testing client: %s", client)

            try:
                yt = YouTube(
                    self.url,
                    client=client,
                    on_progress_callback=self.on_progress,
                )

                audio = self._best_audio(yt)

                if audio:
                    logger.info(
                        "Client %s works: %s (%s)", client, audio, audio.abr
                    )
                    return yt, audio, client

                logger.warning(
                    "Client %s has no compatible audio stream", client
                )

            except Exception as error:
                logger.error(
                    "Client %s failed: %s: %s",
                    client,
                    type(error).__name__,
                    error,
                )

        return None