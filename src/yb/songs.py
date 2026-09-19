"""Download YouTube audio, convert it and tag it."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from mutagen import File as MutagenFile

from src.logging_utils import get_file_logger
from src.yb.authClients import AuthClient
from src.yb.meta import songsData, tagsong

logger = get_file_logger(__name__, "songs.log")


class AudioTooLargeError(Exception):
    """The audio cannot fit in Telegram's 50 MB upload limit."""


class DownloadYB:
    """Download YouTube audio and process its metadata.

    Final files are stored as ``<output_dir>/<video_id>.<ext>``. Using the
    video ID as file name makes lookups exact (the old title-based names could
    never be found again) and avoids collisions between different videos with
    the same title.
    """

    YOUTUBE_ID_RE = re.compile(
        r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})"
    )
    INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')
    SPACES_RE = re.compile(r"\s+")
    TOPIC_RE = re.compile(r"^(.*) - Topic$")

    # Telegram bots can upload up to 50 MB.
    MAX_SIZE_MB = 49.9

    # True: convert to FLAC when it fits. False: keep the original M4A (no
    # transcoding, much faster, and it plays in Telegram's music player).
    PREFER_FLAC = True

    # MP3 fallback bitrates, tried from best to smallest until the file fits.
    MP3_BITRATES = ("320k", "192k", "128k")

    def __init__(
        self,
        url: str,
        output_dir: str | Path = "Songs",
        temp_dir: str | Path = "tmp_downloads",
        thumb_dir: str | Path = "thumbimg",
    ):
        self.url = url
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir)
        self.thumb_dir = Path(thumb_dir)

        # Receives the download percentage (0-100). It is called from the
        # worker thread that runs ``download()``.
        self.progress_callback: Callable[[float], None] | None = None
        self._last_reported = -1

        self.video_id: str | None = None
        self.completeUrl: str | None = None

        self.yt = None
        self.client: str | None = None
        self.audio_stream = None

        self.songs_data = songsData()

    # =========================================================================
    # URL
    # =========================================================================

    def regexUrl(self) -> str:
        match = self.YOUTUBE_ID_RE.search(self.url)

        if not match:
            raise ValueError(f"Invalid YouTube URL: {self.url}")

        self.video_id = match.group(1)
        return self.video_id

    def generateYbUrl(self) -> str:
        if not self.video_id:
            self.regexUrl()

        self.completeUrl = f"https://www.youtube.com/watch?v={self.video_id}"
        return self.completeUrl

    # =========================================================================
    # Download progress
    # =========================================================================

    def _on_progress(self, stream, chunk, bytes_remaining) -> None:
        """pytubefix callback: forward the percentage when it changes."""
        total = stream.filesize

        if not total or self.progress_callback is None:
            return

        percentage = (total - bytes_remaining) / total * 100
        percentage = max(0.0, min(100.0, percentage))

        # pytubefix calls this for every chunk; only report whole-percent steps.
        if int(percentage) == self._last_reported:
            return

        self._last_reported = int(percentage)

        try:
            self.progress_callback(percentage)
        except Exception as error:
            logger.debug("Progress callback failed: %s", error)

    # =========================================================================
    # YouTube client
    # =========================================================================

    def initialize_youtube(self) -> None:
        if not self.completeUrl:
            self.generateYbUrl()

        logger.info("Searching for compatible client...")

        # BUG FIX: the progress callback used to be defined but never
        # registered, so no progress was ever reported. It has to be passed to
        # YouTube(...) through AuthClient.
        result = AuthClient(
            self.completeUrl,
            on_progress=self._on_progress,
        ).check_clients()

        if not result:
            raise RuntimeError("No compatible YouTube client found.")

        self.yt, self.audio_stream, self.client = result

        logger.info(
            "Using client %s, stream %s (%s)",
            self.client,
            self.audio_stream,
            self.audio_stream.abr,
        )

    # =========================================================================
    # Metadata
    # =========================================================================

    @classmethod
    def clean_filename(cls, filename: str | None) -> str:
        """Make ``filename`` safe to use as a file name."""
        if not filename:
            return "Unknown"

        filename = cls.INVALID_FILENAME_RE.sub("", filename)
        filename = cls.SPACES_RE.sub(" ", filename)

        return filename.strip()[:100] or "Unknown"

    def clean_artist(self, artist: str) -> str:
        """Remove the ' - Topic' suffix of auto-generated YouTube channels."""
        return self.TOPIC_RE.sub(r"\1", artist)

    def save_youtube_metadata(self) -> None:
        if self.yt is None:
            raise RuntimeError("YouTube has not been initialized.")

        # Tags may contain any character; only file names need sanitizing.
        title = self.SPACES_RE.sub(" ", self.yt.title or "").strip() or "Unknown"
        artist = self.clean_artist(
            self.SPACES_RE.sub(" ", self.yt.author or "").strip()
        ) or "Unknown"

        self.songs_data.updateTitle(title)
        self.songs_data.updateArtist(artist)
        self.songs_data.updateThumbalImg(getattr(self.yt, "thumbnail_url", None))

        logger.info(
            "Title: %s | Artist: %s | Thumbnail: %s",
            title,
            artist,
            self.songs_data.thumbalImg,
        )

    # =========================================================================
    # Download
    # =========================================================================

    def download_audio(self) -> Path:
        """Download the selected stream into the temporary directory."""
        if self.audio_stream is None:
            raise RuntimeError("Audio stream has not been selected.")

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._last_reported = -1

        extension = (
            "m4a" if self.audio_stream.subtype == "mp4" else self.audio_stream.subtype
        )

        downloaded = Path(
            self.audio_stream.download(
                output_path=str(self.temp_dir),
                filename=f"{self.video_id}.{extension}",
            )
        )

        if not downloaded.exists():
            raise FileNotFoundError(f"Downloaded file does not exist: {downloaded}")

        logger.info("Downloaded: %s", downloaded)
        return downloaded

    # =========================================================================
    # FFmpeg
    # =========================================================================

    @staticmethod
    def run_ffmpeg(input_file: Path, output_file: Path, *args: str) -> None:
        command = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-i", str(input_file),
            "-vn",  # audio only
            *args,
            str(output_file),
        ]

        logger.debug("FFmpeg command: %s", " ".join(command))

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                errors="replace",
            )
        except subprocess.CalledProcessError as error:
            # The real reason used to be thrown away with DEVNULL.
            logger.error("FFmpeg failed: %s", (error.stderr or "").strip()[-500:])
            output_file.unlink(missing_ok=True)
            raise

        if not output_file.exists():
            raise FileNotFoundError(f"FFmpeg did not create: {output_file}")

    def convert_to_mp3(
        self,
        input_file: Path,
        output_file: Path,
        sample_rate: int = 44100,
        bitrate: str = "320k",
    ) -> Path:
        self.run_ffmpeg(
            input_file, output_file,
            "-ar", str(sample_rate),
            "-c:a", "libmp3lame",
            "-b:a", bitrate,
        )
        return output_file

    def convert_to_flac(self, input_file: Path, output_file: Path) -> Path:
        self.run_ffmpeg(input_file, output_file, "-c:a", "flac")
        return output_file

    # =========================================================================
    # File processing
    # =========================================================================

    @staticmethod
    def size_mb(file_path: Path) -> float:
        return file_path.stat().st_size / (1024 * 1024)

    def _target_path(self, suffix: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / f"{self.video_id}{suffix}"

    def process_audio(self, audio_file: Path) -> Path:
        """Convert the downloaded file into its final format inside ``output_dir``."""
        size = self.size_mb(audio_file)
        logger.info("Initial file size: %.2f MB", size)

        if size < self.MAX_SIZE_MB:

            if self.PREFER_FLAC:
                flac = self.convert_to_flac(audio_file, self._target_path(".flac"))
                logger.info("FLAC size: %.2f MB", self.size_mb(flac))

                if self.size_mb(flac) < self.MAX_SIZE_MB:
                    audio_file.unlink(missing_ok=True)
                    return flac

                flac.unlink(missing_ok=True)

            elif audio_file.suffix.lower() == ".m4a":
                target = self._target_path(".m4a")
                shutil.move(str(audio_file), str(target))
                return target

        # Fallback: MP3, lowering the bitrate until it fits.
        for bitrate in self.MP3_BITRATES:
            mp3 = self.convert_to_mp3(
                audio_file, self._target_path(".mp3"), bitrate=bitrate
            )

            if self.size_mb(mp3) < self.MAX_SIZE_MB:
                audio_file.unlink(missing_ok=True)
                return mp3

            mp3.unlink(missing_ok=True)

        audio_file.unlink(missing_ok=True)
        raise AudioTooLargeError(
            f"Audio is larger than {self.MAX_SIZE_MB} MB even at {self.MP3_BITRATES[-1]}."
        )

    def process_metadata(self, final_file: Path) -> None:
        """Tag the file. A tagging failure must not lose the download."""
        logger.info("Processing metadata: %s", final_file)

        try:
            if not self.songs_data.write_tags(final_file):
                logger.warning("No metadata processor for: %s", final_file.suffix)
        except Exception as error:
            logger.warning("Could not write metadata: %s", error)

    @staticmethod
    def audio_duration(audio_path: Path) -> int:
        """Real duration of an audio file in seconds (0 if unknown)."""
        try:
            audio = MutagenFile(str(audio_path))

            if audio and audio.info:
                return int(audio.info.length)

        except Exception as error:
            logger.warning("Could not determine audio duration: %s", error)

        return 0

    def get_final_duration(self, audio_path: Path) -> int:
        """Read the real duration from the final file and store it."""
        self.songs_data.duration = self.audio_duration(audio_path)
        logger.info("Final duration: %s seconds", self.songs_data.duration)
        return self.songs_data.duration

    # =========================================================================
    # Thumbnail for Telegram
    # =========================================================================

    def download_thumbnail(
        self,
        url_thumbnail: str | None,
        video_id: str,
    ) -> Path | None:
        """Return a cached JPEG thumbnail that Telegram will accept."""
        if not url_thumbnail or not url_thumbnail.startswith("https://"):
            return None

        # "_tg" avoids reusing old, oversized files that Telegram ignored.
        image_path = self.thumb_dir / f"{video_id}_tg.jpg"

        if image_path.exists():
            return image_path

        try:
            self.thumb_dir.mkdir(parents=True, exist_ok=True)
            return tagsong(url_thumbnail).save_telegram_thumbnail(image_path)

        except Exception as error:
            logger.warning("Could not create Telegram thumbnail: %s", error)
            return None

    # =========================================================================
    # Main
    # =========================================================================

    def _cleanup_temp(self) -> None:
        """Remove leftovers of a failed download."""
        if self.video_id and self.temp_dir.exists():
            for leftover in self.temp_dir.glob(f"{self.video_id}.*"):
                leftover.unlink(missing_ok=True)

    def download(self) -> Path:
        """Run the whole pipeline. Blocking: run it in a worker thread."""
        try:
            self.regexUrl()
            self.generateYbUrl()

            self.initialize_youtube()
            self.save_youtube_metadata()

            downloaded_file = self.download_audio()
            final_file = self.process_audio(downloaded_file)

            self.process_metadata(final_file)
            self.get_final_duration(final_file)

            logger.info("Download completed: %s", final_file)
            return final_file

        except Exception:
            logger.exception("Error downloading %s", self.url)
            self._cleanup_temp()
            raise