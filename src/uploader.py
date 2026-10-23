"""Telegram audio upload with real-time progress, including a fast path for
a local Bot API server.

python-telegram-bot reads the whole file into memory before sending it, so
there is no way to know how much has really been uploaded. To get a real
progress bar we call the Bot API ``sendAudio`` method ourselves with httpx
and stream the file from disk through a small wrapper that reports every
chunk that is handed to the network layer.

When the bot is paired with a self-hosted local Bot API server (see
``scripts/setup.sh``) and both processes share a filesystem, there is an even
faster option: per Telegram's own docs ("Using a Local Bot API Server" --
https://core.telegram.org/bots/api), a local server lets you "upload files
using their local path and the file URI scheme" instead of transferring the
bytes over HTTP at all -- the server just reads the file directly off disk.
``send_audio_with_progress(..., local_file_mode=True)`` uses that path.
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import tempfile
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

# Generous write timeout: a large file over a slow uplink can take minutes.
# Local-file-mode requests are tiny (no bytes attached) and finish almost
# instantly regardless.
_TIMEOUT = httpx.Timeout(30.0, read=300.0, write=1800.0)

# One pooled client, reused for every upload instead of opening a fresh TCP +
# TLS connection per call. Several QUEUE_WORKERS can upload at once, so the
# pool is sized generously; httpx creates connections lazily, this is just a
# ceiling.
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client

    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT, limits=_LIMITS)

    return _client


async def close_client() -> None:
    """Close the pooled HTTP client. Call this on bot shutdown."""
    global _client

    if _client is not None and not _client.is_closed:
        await _client.aclose()

    _client = None


class UploadError(RuntimeError):
    """Raised when Telegram rejects the upload, or it is refused locally."""


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


async def _post_with_retry(url: str, *, data: dict, files: dict | None) -> dict:
    """POST to the Bot API, retrying once on a flood-control (429) reply."""
    for attempt in range(2):
        client = _get_client()
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
    max_size_mb: float | None = None,
    local_file_mode: bool = False,
) -> dict:
    """Send ``audio_path`` with ``sendAudio`` and report upload progress.

    ``on_progress`` receives an integer percentage (as a float) each time it
    changes. The percentage is measured when bytes are handed to the socket,
    so it can run slightly ahead of the real network on very fast
    connections. In ``local_file_mode`` no bytes are transferred at all (see
    module docstring), so ``on_progress`` is simply called once with 100.

    ``max_size_mb``, if given, is a last line of defense: the file is
    rejected here, before any network call, if it is larger than that --
    even though the download pipeline (``src/yb/songs.py``) already picks a
    bitrate that keeps files under the caller's limit, this keeps the two
    layers independently correct.

    Returns the ``result`` object of the Bot API response.
    """
    if max_size_mb is not None:
        size_mb = audio_path.stat().st_size / (1024 * 1024)

        if size_mb > max_size_mb:
            raise UploadError(
                f"Refusing to upload {size_mb:.1f} MB "
                f"(limit for this user is {max_size_mb:.0f} MB)."
            )

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

    if local_file_mode:
        # Local Bot API server fast path: the server reads the files
        # directly off disk, so this request carries no binary payload at
        # all and completes almost instantly.
        #
        # Caveat: in this mode Telegram takes the file's name from the path
        # itself (there is no multipart "filename" field to override it
        # with), and the real cache file on disk is named "<video_id>.<ext>"
        # to avoid collisions -- so without the staging below, every
        # download would show up on the user's phone as a cryptic video id
        # instead of "Artist - Title".
        #
        # The uniqueness needed to avoid clashing with a concurrent upload
        # of the same song goes in a TEMPORARY DIRECTORY, never in the file
        # name itself -- an earlier version embedded it right in the name
        # (".upload-<uuid>-Artist - Title.flac"), and that stray text and
        # leading dot is exactly what some Telegram clients ended up saving
        # to disk / failing to recognize the extension of. The basename
        # Telegram ever sees is now the exact, clean display name. A hard
        # link (same inode, no byte copy) is created under that name and
        # the whole temp directory is removed once the upload finishes; it
        # falls back to a symlink, then a real copy, only if hard-linking
        # isn't possible (e.g. tmp/data on different filesystems).
        staged_dir = Path(
            tempfile.mkdtemp(prefix="tg-upload-", dir=audio_path.parent)
        )
        staged_path = staged_dir / filename

        try:
            try:
                os.link(audio_path, staged_path)
            except OSError:
                try:
                    staged_path.symlink_to(audio_path.resolve())
                except OSError:
                    shutil.copy2(audio_path, staged_path)

            data["audio"] = f"file://{staged_path.resolve()}"

            if thumbnail is not None and thumbnail.exists():
                data["thumbnail"] = f"file://{thumbnail.resolve()}"

            if on_progress:
                on_progress(100.0)

            return await _post_with_retry(url, data=data, files=None)
        finally:
            shutil.rmtree(staged_dir, ignore_errors=True)

    mime_type = MIME_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")

    thumb_bytes: bytes | None = None

    if thumbnail is not None and thumbnail.exists():
        thumb_bytes = thumbnail.read_bytes()

    # Retrying a multipart upload needs a FRESH file handle each time -- once
    # httpx has streamed ProgressFile to EOF for a failed attempt, reusing it
    # would send an empty body. So, unlike the (bodiless) local-file-mode
    # path, the retry loop lives here rather than in `_post_with_retry`.
    for attempt in range(2):
        with ProgressFile(audio_path, on_progress) as audio_file:
            files = {"audio": (filename, audio_file, mime_type)}

            if thumb_bytes:
                files["thumbnail"] = ("thumbnail.jpg", thumb_bytes, "image/jpeg")

            client = _get_client()
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
