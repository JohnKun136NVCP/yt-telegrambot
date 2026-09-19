"""Thumbnail processing and audio tagging."""

import re
from pathlib import Path

import cv2
import numpy as np
import requests
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TIT2, TPE1
from mutagen.mp4 import MP4, MP4Cover

from src.logging_utils import get_file_logger

logger = get_file_logger(__name__, "meta.log")


class tagsong:
    """Download a YouTube thumbnail and turn it into a square album cover."""

    # Thumbnails that YouTube pads with black bars (4:3 image with 16:9 content).
    LETTERBOXED_SUFFIXES = ("sddefault.jpg", "hqdefault.jpg")

    # Telegram only shows a thumbnail that is JPEG, <= 320 px and <= 200 KB.
    TELEGRAM_THUMB_MAX_SIDE = 320
    TELEGRAM_THUMB_MAX_BYTES = 200 * 1024

    def __init__(self, thumbnail_url: str | None):
        self.thumbnail_url = thumbnail_url
        self.image: np.ndarray | None = None
        self.cropped_image: np.ndarray | None = None

    # -------------------------------------------------------------------------
    # Loading
    # -------------------------------------------------------------------------

    def download_image(self) -> np.ndarray:
        """Download and decode the thumbnail."""
        if not self.thumbnail_url:
            raise ValueError("Thumbnail URL is empty.")

        response = requests.get(self.thumbnail_url, timeout=20)
        response.raise_for_status()

        image = cv2.imdecode(
            np.frombuffer(response.content, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )

        if image is None:
            raise ValueError("Could not decode thumbnail image.")

        return image

    def load(self) -> np.ndarray:
        """Download the image once and cache it."""
        if self.image is None:
            self.image = self.download_image()

        return self.image

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    @staticmethod
    def _trim_black_borders(img: np.ndarray, tolerance: int = 10) -> np.ndarray:
        """Remove black rows/columns at the edges of the image."""
        non_black = (img > tolerance).any(axis=2)
        rows = np.flatnonzero(non_black.any(axis=1))
        cols = np.flatnonzero(non_black.any(axis=0))

        if rows.size and cols.size:
            return img[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]

        return img

    def process(self) -> np.ndarray:
        """Return the square, border-free cover (cached)."""
        if self.cropped_image is not None:
            return self.cropped_image

        image = self.load()

        if self.thumbnail_url and self.thumbnail_url.endswith(
            self.LETTERBOXED_SUFFIXES
        ):
            image = self._trim_black_borders(image)

        # Center square crop: replaces the old hard-coded 350/480/720/750 sizes
        # with the real image size, so it works for any thumbnail resolution.
        height, width = image.shape[:2]
        side = min(height, width)
        y = (height - side) // 2
        x = (width - side) // 2

        self.cropped_image = image[y:y + side, x:x + side]
        return self.cropped_image

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------

    @staticmethod
    def _encode_jpeg(image: np.ndarray, quality: int) -> bytes:
        ok, buffer = cv2.imencode(
            ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )

        if not ok:
            raise ValueError("Could not encode image as JPEG.")

        return buffer.tobytes()

    def to_jpeg_bytes(self, quality: int = 90) -> bytes:
        """Cover as JPEG bytes, ready to embed (no temporary files)."""
        return self._encode_jpeg(self.process(), quality)

    def save_telegram_thumbnail(self, output_path: str | Path) -> Path:
        """Save a thumbnail that respects Telegram's size limits."""
        image = self.process()
        height, width = image.shape[:2]

        scale = min(1.0, self.TELEGRAM_THUMB_MAX_SIDE / max(height, width))

        if scale < 1.0:
            image = cv2.resize(
                image,
                (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_AREA,
            )

        data = b""

        for quality in (90, 80, 70, 60, 50):
            data = self._encode_jpeg(image, quality)

            if len(data) <= self.TELEGRAM_THUMB_MAX_BYTES:
                break

        output_path = Path(output_path)
        output_path.write_bytes(data)

        return output_path


class songsData:
    """Song metadata and album artwork."""

    THUMBNAIL_RE = re.compile(r"^(.*?\.jpg)", re.IGNORECASE)

    def __init__(self):
        self.thumbalImg: str | None = None
        self.title: str = ""
        self.artist: str = ""
        self.duration: int = 0

        self._cover: bytes | None = None
        self._cover_loaded = False

    # -------------------------------------------------------------------------
    # Basic metadata
    # -------------------------------------------------------------------------

    def updateTitle(self, title) -> str:
        self.title = str(title or "").strip()
        return self.title

    def updateArtist(self, artist) -> str:
        self.artist = str(artist or "").strip()
        return self.artist

    def updateDuration(self, song_duration) -> int:
        """Set the duration from a mutagen object (``obj.info.length``)."""
        try:
            self.duration = int(song_duration.info.length)
        except (AttributeError, TypeError, ValueError):
            self.duration = 0

        return self.duration

    # -------------------------------------------------------------------------
    # Thumbnail
    # -------------------------------------------------------------------------

    def _cleanThumbalImg(self, thumbnail_url) -> str | None:
        if not isinstance(thumbnail_url, str):
            return None

        thumbnail_url = thumbnail_url.strip()

        if not thumbnail_url:
            return None

        match = self.THUMBNAIL_RE.match(thumbnail_url)

        if match:
            return match.group(1)

        # A valid URL that the regex does not know is kept as it is.
        if thumbnail_url.startswith(("http://", "https://")):
            return thumbnail_url

        return None

    def updateThumbalImg(self, thumbnail_url) -> str | None:
        self.thumbalImg = self._cleanThumbalImg(thumbnail_url)
        self._cover = None
        self._cover_loaded = False
        return self.thumbalImg

    def _get_cover(self) -> bytes | None:
        """Cover as JPEG bytes. Downloaded and processed only once."""
        if self._cover_loaded:
            return self._cover

        self._cover_loaded = True

        if not self.thumbalImg:
            return None

        try:
            self._cover = tagsong(self.thumbalImg).to_jpeg_bytes()
        except Exception as error:
            logger.warning("Could not process thumbnail: %s", error)
            self._cover = None

        return self._cover

    # -------------------------------------------------------------------------
    # Tag writers
    # -------------------------------------------------------------------------

    def updateMetaData(self, audio_path) -> None:
        """Write tags and cover into an MP4/M4A file."""
        target = MP4(str(audio_path))

        if target.tags is None:
            target.add_tags()

        if self.title:
            target["\xa9nam"] = [self.title]

        if self.artist:
            target["\xa9ART"] = [self.artist]

        cover = self._get_cover()

        if cover:
            target["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]

        target.save()

    def updateFlacCover(self, audio_path) -> None:
        """Write tags and cover into a FLAC file."""
        target = FLAC(str(audio_path))

        if self.title:
            target["title"] = self.title

        if self.artist:
            target["artist"] = self.artist

        cover = self._get_cover()

        if cover:
            picture = Picture()
            picture.data = cover
            picture.type = 3  # Front cover
            picture.mime = "image/jpeg"
            picture.desc = "Cover"

            target.clear_pictures()
            target.add_picture(picture)

        target.save()

    def updateMp3Meta(self, audio_path) -> None:
        """Write ID3 tags and cover into an MP3 file.

        The old code never tagged MP3 files, so every song that fell back to
        MP3 was sent without title, artist or cover.
        """
        try:
            tags = ID3(str(audio_path))
        except ID3NoHeaderError:
            tags = ID3()

        if self.title:
            tags.add(TIT2(encoding=3, text=self.title))

        if self.artist:
            tags.add(TPE1(encoding=3, text=self.artist))

        cover = self._get_cover()

        if cover:
            tags.delall("APIC")
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=cover,
                )
            )

        tags.save(str(audio_path), v2_version=3)

    def write_tags(self, audio_path) -> bool:
        """Pick the right tag writer for the file extension.

        Returns ``False`` when the format is not supported.
        """
        suffix = Path(audio_path).suffix.lower()

        if suffix in (".m4a", ".mp4"):
            self.updateMetaData(audio_path)
        elif suffix == ".flac":
            self.updateFlacCover(audio_path)
        elif suffix == ".mp3":
            self.updateMp3Meta(audio_path)
        else:
            return False

        return True