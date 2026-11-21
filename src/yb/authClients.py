"""Find a pytubefix client that can deliver a usable audio stream."""

import re
from typing import Callable

from pytubefix import YouTube, extract
from pytubefix.botGuard import bot_guard
from pytubefix.innertube import InnerTube

from src.logging_utils import get_file_logger

logger = get_file_logger(__name__, "authClients.log")

_DIGITS_RE = re.compile(r"\d+")


def _make_po_token_verifier(video_id: str) -> Callable[[], tuple[str, str]]:
    """Build a ``po_token_verifier`` callback for ``pytubefix``'s ``YouTube``.

    By default pytubefix only tries to get a po_token (YouTube's anti-bot
    "Proof of Origin" token) for a handful of clients, and even then it's
    the implicit, lazy ``YouTube.pot``/``YouTube.visitor_data`` machinery --
    which only produces a token good enough for WEB-based clients. YouTube's
    SABR protection increasingly rejects every other client without one,
    which is what was happening here (``SABRError: ... PoToken PENDING`` /
    ``PENDING_MISSING`` for every client).

    ``use_po_token=True`` + a custom ``po_token_verifier`` forces pytubefix
    to fetch a po_token for every client. The verifier pytubefix ships by
    default (``_default_po_token_verifier``) calls the blocking ``input()``
    twice -- which would hang this bot forever on a headless server with no
    TTY -- so a safe, non-interactive one must always be supplied instead.

    This one reuses pytubefix's own, non-interactive building blocks: a
    plain WEB ``player()`` call for ``visitor_data``, and the bundled
    Node/botGuard runner (``pytubefix.botGuard.bot_guard``, via the pinned
    ``nodejs-wheel-binaries`` package) for the po_token itself -- the exact
    same pair ``YouTube.visitor_data``/``YouTube.pot`` would produce, just
    computed eagerly instead of lazily so it works for every client.

    pytubefix calls this at most once per ``YouTube``/``InnerTube`` instance
    (the result is cached internally), and only when it actually needs a
    po_token for an API call, so it is memoized here too: all clients tried
    for the same video share a single visitor_data/po_token pair and a
    single Node subprocess run, instead of paying that cost per client.
    """
    cache: dict[str, tuple[str, str]] = {}

    def verifier() -> tuple[str, str]:
        cached = cache.get("tokens")
        if cached:
            return cached

        innertube_response = InnerTube("WEB").player(video_id)
        try:
            visitor_data = innertube_response["responseContext"]["visitorData"]
        except KeyError:
            params = innertube_response["responseContext"]["serviceTrackingParams"][0]["params"]
            visitor_data = next(p["value"] for p in params if p["key"] == "visitor_data")

        po_token = bot_guard.generate_po_token(video_id=video_id)

        tokens = (visitor_data, po_token)
        cache["tokens"] = tokens
        return tokens

    return verifier


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
        """Return the best compatible audio stream of ``yt`` (or ``None``).

        SABR ("Server ABR") is YouTube's newer streaming mode: more and more
        videos/clients now ONLY expose audio through it instead of a plain
        downloadable URL. This used to be filtered out here on the (now
        outdated) assumption that a SABR stream can't be downloaded -- but
        pytubefix >= 11.2 can: ``Stream.download()``/``.stream()`` detect
        ``is_sabr`` themselves and transparently speak the SABR protocol
        (``pytubefix.sabr.core.server_abr_stream.ServerAbrStream``) instead
        of a plain HTTP range request. Excluding these streams here was
        turning an otherwise-downloadable stream into "no compatible audio
        stream" for every client that happens to be SABR-only for a given
        video, which is exactly what was happening for long/popular videos.
        """
        candidates = list(yt.streams.filter(only_audio=True))

        if not candidates:
            return None

        # Highest bitrate first; on a tie prefer AAC/M4A (cheaper to process).
        return max(
            candidates,
            key=lambda s: (self._bitrate(s), s.mime_type == "audio/mp4"),
        )

    def check_clients(self):
        """Return ``(yt, audio_stream, client_name)`` or ``None``."""
        return next(self.iter_clients(), None)

    def iter_clients(self):
        """Yield ``(yt, audio_stream, client_name)`` for every client that offers audio.

        A client can list a stream and still get ``403 Forbidden`` when the
        bytes are requested, so the downloader keeps this generator and asks
        for the next client when that happens.
        """
        logger.info("Checking available clients...")

        po_token_verifier = None
        try:
            po_token_verifier = _make_po_token_verifier(extract.video_id(self.url))
        except Exception as error:
            # Best effort: if the video id can't even be parsed out of the
            # URL here, fall back to pytubefix's own default behaviour per
            # client instead of failing the whole generator up front --
            # ``YouTube(...)`` below will hit (and report) the same problem
            # per client, same as before this po_token change.
            logger.warning(
                "Could not prepare a po_token verifier: %s: %s",
                type(error).__name__, error,
            )

        for client in self.clients:
            logger.info("Testing client: %s", client)

            try:
                yt = YouTube(
                    self.url,
                    client=client,
                    on_progress_callback=self.on_progress,
                    **(
                        {"use_po_token": True, "po_token_verifier": po_token_verifier}
                        if po_token_verifier
                        else {}
                    ),
                )

                audio = self._best_audio(yt)

                if audio:
                    logger.info(
                        "Client %s works: %s (%s, sabr=%s)",
                        client, audio, audio.abr, getattr(audio, "is_sabr", False),
                    )
                    yield yt, audio, client
                    continue

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