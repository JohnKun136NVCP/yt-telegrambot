"""Telegram audio upload with real-time progress.

python-telegram-bot reads the whole file into memory before sending it, so
there is no way to know how much has really been uploaded. To get a real
progress bar we call the Bot API ``sendAudio`` method ourselves with httpx and
stream the file from disk through a small wrapper that reports every chunk
that is handed to the network layer.
"""

import asyncio
import io
import os
from pathlib import Path
from typing import Callable

import httpx
from telegram import Bot

from src.logging_utils import get_file_logger

logger = get_file_logger(__name__, "uploader.log")

MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".flac": "audio/flac",
}

# Generous write timeout: a 50 MB file over a slow uplink can take minutes.
_TIMEOUT = httpx.Timeout(30.0, read=300.0, write=600.0)


class UploadError(RuntimeError):
    """Raised when Telegram rejects the upload."""


class ProgressFile(io.BufferedReader):
    """Binary file that reports the read percentage (0-100) as it is consumed."""

    def __init__(
        self,
        path: str | Path,
        callback: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(io.FileIO(path, "rb"))
        self._total = max(os.path.getsize(path), 1)
        self._callback = callback
        self._last_pct = -1

    def read(self, size: int | None = -1) -> bytes:
        data = super().read(size)

        if data and self._callback:
            pct = int(min(self.tell(), self._total) * 100 / self._total)

            # Only notify when the integer percentage changes.
            if pct != self._last_pct:
                self._last_pct = pct
                self._callback(float(pct))

        return data

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        # httpx rewinds the file before streaming it: restart the counter.
        self._last_pct = -1
        return super().seek(offset, whence)


async def send_audio_with_progress(
    bot: Bot,
    chat_id: int,
    audio_path: Path,
    *,
    title: str,
    performer: str,
    duration: int,
    filename: str,
    caption: str | None = None,
    thumbnail: Path | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> dict:
    """Send ``audio_path`` with ``sendAudio`` and report upload progress.

    ``on_progress`` receives an integer percentage (as a float) each time it
    changes. The percentage is measured when bytes are handed to the socket,
    so it can run slightly ahead of the real network on very fast connections.

    Returns the ``result`` object of the Bot API response.
    """
    url = f"{bot.base_url}/sendAudio"

    data = {
        "chat_id": str(chat_id),
        "title": title,
        "performer": performer,
        "duration": str(int(duration or 0)),
    }

    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"

    mime_type = MIME_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")

    thumb_bytes: bytes | None = None

    if thumbnail is not None and thumbnail.exists():
        thumb_bytes = thumbnail.read_bytes()

    # One retry is allowed when Telegram answers with a flood-wait (HTTP 429).
    for attempt in range(2):

        with ProgressFile(audio_path, on_progress) as audio_file:

            files = {"audio": (filename, audio_file, mime_type)}

            if thumb_bytes:
                files["thumbnail"] = ("thumbnail.jpg", thumb_bytes, "image/jpeg")

            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(url, data=data, files=files)

        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            raise UploadError("Unexpected response from Telegram.")

        if payload.get("ok"):
            return payload.get("result", {})

        retry_after = payload.get("parameters", {}).get("retry_after")

        if response.status_code == 429 and retry_after and attempt == 0:
            logger.warning("Flood control, retrying in %s s", retry_after)
            await asyncio.sleep(float(retry_after) + 1)
            continue

        raise UploadError(payload.get("description", "Telegram rejected the upload."))

    raise UploadError("Upload failed after retrying.")