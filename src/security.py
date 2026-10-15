"""Security helpers: link validation and per-user flood control.

Kept dependency-free (stdlib only) so it can be imported and unit-tested
without the Telegram stack.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

ALLOWED_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)

# YouTube serves thumbnails from i.ytimg.com (and a few regional i*.ytimg.com
# variants) -- never from an arbitrary host.
_ALLOWED_THUMBNAIL_SUFFIXES = (".ytimg.com", "ytimg.com")


def is_youtube_url(url: str) -> bool:
    """Whether ``url``'s host is a known YouTube domain.

    Used to reject obviously-wrong links before spending a queue slot and a
    download attempt on them. Note this is a usability check, not the only
    thing standing between a user and an SSRF: ``DownloadYB`` never fetches
    the user's raw URL -- it extracts the 11-character video id with a strict
    ``[A-Za-z0-9_-]{11}`` regex and always rebuilds a fresh
    ``https://www.youtube.com/watch?v=<id>`` URL from that id before handing
    anything to pytubefix. A hostile host in the original link is therefore
    never itself fetched, by construction.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False

    return host in ALLOWED_YOUTUBE_HOSTS


def is_allowed_thumbnail_url(url: str | None) -> bool:
    """Defense in depth: only ever fetch thumbnails from YouTube's own CDN."""
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower()
    return host.endswith(_ALLOWED_THUMBNAIL_SUFFIXES)


class FloodControl:
    """A simple in-memory per-user cooldown.

    Deliberately not persisted to disk: on restart everyone gets a fresh
    cooldown window, which is harmless (worst case: one request slightly
    sooner than ideal) and keeps this free of extra moving parts. Paired with
    the bounded, persistent job queue in ``src/job_queue.py`` for the part
    that *does* need to survive a restart.
    """

    def __init__(self, min_interval_seconds: float):
        self._min_interval = min_interval_seconds
        self._last_allowed: dict[int, float] = {}

    def check(self, user_id: int) -> float:
        """Return 0 if ``user_id`` may act now, otherwise seconds left to wait.

        Only an *allowed* call resets the window, so rapid repeated spamming
        keeps getting pushed back relative to the last allowed action rather
        than being able to "refresh" its own cooldown by retrying quickly.
        """
        now = time.monotonic()
        last = self._last_allowed.get(user_id)

        if last is not None:
            elapsed = now - last

            if elapsed < self._min_interval:
                return self._min_interval - elapsed

        self._last_allowed[user_id] = now
        return 0.0

    def forget(self, user_id: int) -> None:
        """Clear a user's cooldown (e.g. after an instant validation failure
        that should not count against them)."""
        self._last_allowed.pop(user_id, None)
