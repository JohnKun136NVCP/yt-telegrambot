import logging
import re
import shutil
import subprocess
import requests
from pathlib import Path
from typing import Callable
from mutagen import File

from pytubefix import YouTube

from src.yb.authClients import AuthClient
from src.yb.meta import songsData


logger = logging.getLogger(__name__)

if not logger.handlers:

    logger.setLevel(logging.INFO)

    handler = logging.FileHandler(
        "logs/songs.log"
    )

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    )

    handler.setFormatter(
        formatter
    )

    logger.addHandler(
        handler
    )


class DownloadYB:
    """
    Download YouTube audio and process metadata.
    """

    YOUTUBE_ID_RE = re.compile(
        r"(?:v=|youtu\.be/|youtube\.com/shorts/)"
        r"([A-Za-z0-9_-]{11})"
    )

    INVALID_FILENAME_RE = re.compile(
        r'[<>:"/\\|?*]'
    )

    SPACES_RE = re.compile(
        r"\s+"
    )

    TOPIC_RE = re.compile(
        r"^(.*) - Topic$"
    )

    MAX_SIZE_MB = 49.9

    def __init__(
        self,
        url: str,
        output_dir: str | Path = "Songs"
    ):

        self.url = url
        self.progress_callback: Callable[[float], None] | None = None

        self.output_dir = Path(
            output_dir
        )

        self.video_id: str | None = None
        self.completeUrl: str | None = None

        self.yt = None
        self.client: str | None = None
        self.audio_stream = None

        self.songs_data = songsData()

    # =========================================================
    # URL
    # =========================================================
    def _on_progress(
        self,
        stream,
        chunk,
        bytes_remaining
    ):
        """
        Callback de progreso de pytubefix.
        Envía el porcentaje de descarga al bot.
        """

        try:
            total_size = stream.filesize

            if not total_size:
                return

            downloaded = total_size - bytes_remaining

            percentage = (
                downloaded / total_size
            ) * 100

            percentage = max(
                0.0,
                min(100.0, percentage)
            )

            if self.progress_callback:
                self.progress_callback(
                    percentage
                )

        except Exception as e:
            logger.debug(
                "Could not calculate download progress: %s",
                e
            )


    def regexUrl(self):

        match = self.YOUTUBE_ID_RE.search(
            self.url
        )

        if not match:
            raise ValueError(
                f"Invalid YouTube URL: {self.url}"
            )

        self.video_id = (
            match.group(1)
        )

        return self.video_id

    def generateYbUrl(self):

        if not self.video_id:
            self.regexUrl()

        self.completeUrl = (
            "https://www.youtube.com/watch?v="
            f"{self.video_id}"
        )

        return self.completeUrl

    # =========================================================
    # YouTube client
    # =========================================================

    def initialize_youtube(self):

        if not self.completeUrl:
            self.generateYbUrl()

        logger.info(
            "Searching for compatible YouTube client..."
        )

        auth_client = AuthClient(
            self.completeUrl
        )

        result = auth_client.check_clients()

        if not result:
            raise RuntimeError(
                "No compatible YouTube client found."
            )

        (
            self.yt,
            self.audio_stream,
            self.client,
        ) = result

        logger.info(
            "Using client: %s",
            self.client
        )

        logger.info(
            "Audio stream: %s",
            self.audio_stream
        )

<<<<<<< Updated upstream
        logger.info(
            "Audio bitrate: %s",
            self.audio_stream.abr
        )

=======
        self.yt = YouTube(
        self.completeUrl,
        self.client,
        on_progress_callback=self._on_progress
        )


        # Use the stream already discovered
        # by AuthClient.
        for stream in streams:

            if (
                stream.mime_type.startswith("audio/")
                and not stream.is_sabr
            ):

                self.audio_stream = stream
                break

        if self.audio_stream is None:
            raise RuntimeError(
                "No compatible audio stream found."
            )
>>>>>>> Stashed changes

    # =========================================================
    # Metadata
    # =========================================================

    @classmethod
    def clean_filename(
        cls,
        filename: str | None
    ):

        if not filename:
            return "Unknown"

        filename = (
            cls.INVALID_FILENAME_RE.sub(
                "",
                filename
            )
        )

        filename = (
            cls.SPACES_RE.sub(
                " ",
                filename
            )
        )

        return filename.strip()[:100]

    def clean_artist(
        self,
        artist: str
    ):

        return self.TOPIC_RE.sub(
            r"\1",
            artist
        )

    def save_youtube_metadata(self):

        if self.yt is None:
            raise RuntimeError(
                "YouTube has not been initialized."
            )

        title = self.clean_filename(
            self.yt.title
        )

        artist = self.clean_filename(
            self.yt.author
        )

        artist = self.clean_artist(
            artist
        )

        self.songs_data.updateTitle(
            title
        )

        self.songs_data.updateArtist(
            artist
        )

        self.songs_data.updateThumbalImg(
            getattr(
                self.yt,
                "thumbnail_url",
                None
            )
        )

        logger.info(
            "Title: %s",
            title
        )

        logger.info(
            "Artist: %s",
            artist
        )

        logger.info(
            "Thumbnail: %s",
            self.songs_data.thumbalImg
        )

    # =========================================================
    # Download
    # =========================================================

    def download_audio(self) -> Path:

        if self.audio_stream is None:
            raise RuntimeError(
                "Audio stream has not been selected."
            )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        downloaded = (
            self.audio_stream.download(
                output_path=str(
                    self.output_dir
                )
            )
        )

        downloaded_path = Path(
            downloaded
        )

        if not downloaded_path.exists():
            raise FileNotFoundError(
                f"Downloaded file does not exist: "
                f"{downloaded_path}"
            )

        logger.info(
            "Downloaded: %s",
            downloaded_path
        )

        return downloaded_path

    # =========================================================
    # FFmpeg
    # =========================================================

    @staticmethod
    def run_ffmpeg(
        input_file: Path,
        output_file: Path,
        *args: str
    ):

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_file),
            *args,
            str(output_file)
        ]

        logger.debug(
            "FFmpeg command: %s",
            " ".join(command)
        )

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if not output_file.exists():

            raise FileNotFoundError(
                f"FFmpeg did not create: "
                f"{output_file}"
            )

    def convert_to_mp3(
        self,
        input_file: Path,
        sample_rate: int = 44100,
        bitrate: str = "320k"
    ) -> Path:

        output_file = (
            input_file.with_suffix(".mp3")
        )

        self.run_ffmpeg(
            input_file,
            output_file,
            "-ar",
            str(sample_rate),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate
        )

        return output_file


    def convert_to_flac(
        self,
        input_file: Path
    ) -> Path:

        output_file = (
            input_file.with_suffix(".flac")
        )

        self.run_ffmpeg(
            input_file,
            output_file,
            "-f",
            "flac"
        )

        return output_file

    # =========================================================
    # File processing
    # =========================================================

    @staticmethod
    def size_mb(
        file_path: Path
    ) -> float:

        return (
            file_path.stat().st_size
            / (1024 * 1024)
        )

    def process_audio(
        self,
        audio_file: Path
    ) -> Path:

        size = self.size_mb(
            audio_file
        )

        logger.info(
            "Initial file size: %.2f MB",
            size
        )

        # -----------------------------------------------------
        # Try FLAC directly when possible
        # -----------------------------------------------------

        if size < self.MAX_SIZE_MB:

            flac = self.convert_to_flac(
                audio_file
            )

            flac_size = self.size_mb(
                flac
            )

            logger.info(
                "FLAC size: %.2f MB",
                flac_size
            )

            if flac_size < self.MAX_SIZE_MB:

                audio_file.unlink(
                    missing_ok=True
                )

                return flac

            flac.unlink(
                missing_ok=True
            )

        # -----------------------------------------------------
        # Fallback to MP3
        # -----------------------------------------------------

        mp3 = self.convert_to_mp3(
            audio_file,
            sample_rate=44100
        )

        audio_file.unlink(
            missing_ok=True
        )

        return mp3


    # =========================================================
    # Metadata
    # =========================================================

    def process_metadata(
        self,
        final_file: Path
    ):

        suffix = final_file.suffix.lower()

        logger.info(
        "Processing metadata: %s",
        final_file
    )

        if suffix in (".m4a", ".mp4"):

            self.songs_data.updateMetaData(
                str(final_file)
            )

        elif suffix == ".flac":

            self.songs_data.updateFlacCover(
                str(final_file)
            )

        else:

            logger.warning(
                "No metadata processor for: %s",
                suffix
            )
            
    def get_final_duration(
        self,
        audio_path: Path
    ) -> int:

        try:

            audio = File(
                str(audio_path)
            )

            if audio and audio.info:

                duration = int(
                    audio.info.length
                )

                logger.info(
                    "Final duration: %s seconds",
                    duration
                )

                self.songs_data.duration = duration

                return duration

        except Exception as e:

            logger.warning(
                "Could not determine audio duration: %s",
                e
            )

        self.songs_data.duration = 0

        return 0

    # =========================================================
    # Move
    # =========================================================

    def move_file(
        self,
        file_path: Path
    ) -> Path:

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        # If the file is already inside output_dir,
        # don't move it.
        try:

            if (
                file_path.parent.resolve()
                == self.output_dir.resolve()
            ):

                return file_path

        except FileNotFoundError:
            pass

        destination = (
            self.output_dir
            / file_path.name
        )

        shutil.move(
            str(file_path),
            str(destination)
        )

        logger.info(
            "Moved: %s -> %s",
            destination
        )

        return destination
    def download_thumbnail(
        self,
        url_thumbnail: str | None,
        video_id: str
    ) -> Path | None:

        if not url_thumbnail:
            return None

        if not url_thumbnail.startswith(
            "https://"
        ):
            return None

        try:

            temp_dir = Path(
                "thumbimg"
            )

            temp_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            image_path = (
                temp_dir
                / f"{video_id}.jpg"
            )

            if image_path.exists():
                return image_path

            response = requests.get(
                url_thumbnail,
                timeout=20
            )

            response.raise_for_status()

            image_path.write_bytes(
                response.content
            )

            return image_path

        except requests.RequestException as e:

            logger.error(
                "Error downloading thumbnail: %s",
                e
            )

            return None


    # =========================================================
    # Main
    # =========================================================

    def download(self) -> Path:

        try:

            # -------------------------------------------------
            # 1. URL
            # -------------------------------------------------

            self.regexUrl()
            self.generateYbUrl()

            # -------------------------------------------------
            # 2. Find working client
            # -------------------------------------------------

            self.initialize_youtube()

            logger.info(
                "Cliente seleccionado: %s",
                self.client
            )

            # -------------------------------------------------
            # 3. Download
            # -------------------------------------------------

            downloaded_file = (
                self.download_audio()
            )

            # -------------------------------------------------
            # 4. Save YouTube information
            # -------------------------------------------------

            self.save_youtube_metadata()

            # -------------------------------------------------
            # 5. Process audio
            # -------------------------------------------------

            final_file = (
                self.process_audio(
                    downloaded_file
                )
            )# Read the duration from the final processed file.
            try:

                from mutagen import File

                audio_info = File(
                    str(final_file)
                )

                if audio_info and audio_info.info:

                    self.songs_data.duration = int(
                        audio_info.info.length
                    )

                    logger.info(
                        "Final audio duration: %s seconds",
                        self.songs_data.duration
                    )

            except Exception as e:

                logger.warning(
                    "Could not read final audio duration: %s",
                    e
                )


            # -------------------------------------------------
            # 6. Process metadata
            # -------------------------------------------------

            self.process_metadata(
                final_file
            )

            # -------------------------------------------------
            # 7. Move final file
            # -------------------------------------------------

            final_file = self.move_file(
                final_file
            )

            # -------------------------------------------------
            # 8. Get REAL final duration
            # -------------------------------------------------

            self.get_final_duration(
                final_file
            )

            logger.info(
                "Download completed: %s",
                final_file
            )

            logger.info(
                "Final duration: %s seconds",
                self.songs_data.duration
            )

            return final_file

        except Exception:

            logger.exception(
                "Error downloading %s",
                self.url
            )

            raise
