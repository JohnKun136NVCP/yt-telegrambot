import os
import re
from pathlib import Path

import cv2
import numpy as np
import requests

from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, APIC
from mutagen.mp4 import MP4, MP4Cover


class tagsong:
    """
    Download and process YouTube thumbnail images.
    """

    DEFAULT_THUMBNAIL = "sddefault.jpg"
    MAXRES_THUMBNAIL = "maxresdefault.jpg"
    HQ_THUMBNAIL = "hqdefault.jpg"

    def __init__(self, thumbnail_url: str | None):
        self.thumbnail_url = thumbnail_url

        self.height = 0
        self.width = 0

        self.cropped_image = None
        self.image = None

        self.crop_size = 0

    # =========================================================
    # Thumbnail size
    # =========================================================

    def _set_crop_size(self) -> int:

        if not self.thumbnail_url:
            return 0

        if self.thumbnail_url.endswith(
            self.DEFAULT_THUMBNAIL
        ):
            self.crop_size = 350

        elif self.thumbnail_url.endswith(
            self.MAXRES_THUMBNAIL
        ):
            self.crop_size = 720

        elif self.thumbnail_url.endswith(
            self.HQ_THUMBNAIL
        ):
            self.crop_size = 480

        else:
            self.crop_size = 750

        return self.crop_size

    # =========================================================
    # Image processing
    # =========================================================

    @staticmethod
    def _trim_black_borders(
        img: np.ndarray,
        tolerance: int = 10
    ) -> np.ndarray:

        non_black = (
            img > tolerance
        ).any(axis=2)

        rows = np.where(
            non_black.any(axis=1)
        )[0]

        cols = np.where(
            non_black.any(axis=0)
        )[0]

        if rows.size and cols.size:

            y1, y2 = rows[0], rows[-1]
            x1, x2 = cols[0], cols[-1]

            return img[
                y1:y2 + 1,
                x1:x2 + 1
            ]

        return img

    def download_image(self):

        if not self.thumbnail_url:
            raise ValueError(
                "Thumbnail URL is empty."
            )

        response = requests.get(
            self.thumbnail_url,
            timeout=20
        )

        response.raise_for_status()

        image_np = np.asarray(
            bytearray(response.content),
            dtype=np.uint8
        )

        image = cv2.imdecode(
            image_np,
            cv2.IMREAD_COLOR
        )

        if image is None:
            raise ValueError(
                "Could not decode thumbnail image."
            )

        return image

    def get_dimension(self):

        if self.image is None:
            raise ValueError(
                "Image has not been loaded."
            )

        return self.image.shape

    def calculate_coordinates(self):

        self._set_crop_size()

        x = (
            self.width - self.crop_size
        ) // 2

        y = (
            self.height - self.crop_size
        ) // 2

        return x, y

    def crop_image(self):

        self._set_crop_size()

        # If image is smaller than requested crop,
        # don't attempt an invalid crop.
        if (
            self.crop_size <= 0
            or self.width < self.crop_size
            or self.height < self.crop_size
        ):
            return self.image

        x_start, y_start = (
            self.calculate_coordinates()
        )

        return self.image[
            y_start:y_start + self.crop_size,
            x_start:x_start + self.crop_size
        ]

    def save_image(
        self,
        output_path: str | Path = "cropped_image.png"
    ) -> Path:

        output_path = Path(output_path)

        if self.cropped_image is None:
            raise ValueError(
                "There is no processed image to save."
            )

        success = cv2.imwrite(
            str(output_path),
            self.cropped_image
        )

        if not success:
            raise IOError(
                f"Could not save image: {output_path}"
            )

        return output_path

    def delete_temp(
        self,
        path: str | Path = "cropped_image.png"
    ):

        Path(path).unlink(
            missing_ok=True
        )

    # =========================================================
    # Main
    # =========================================================

    def run(
        self,
        output_path: str | Path = "cropped_image.png"
    ):

        if not self.thumbnail_url:
            return None

        self.image = self.download_image()

        self.height, self.width, _ = (
            self.get_dimension()
        )

        if not self.thumbnail_url.endswith(
            self.HQ_THUMBNAIL
        ):
            self.cropped_image = (
                self.crop_image()
            )

        else:
            self.cropped_image = (
                self._trim_black_borders(
                    self.image
                )
            )

        return self.save_image(
            output_path
        )


class songsData:
    """
    Handle song metadata and album artwork.
    """

    THUMBNAIL_RE = re.compile(
        r"^(.*?\.jpg)",
        re.IGNORECASE
    )

    def __init__(self):

        # IMPORTANT:
        # None instead of str/int classes.
        self.thumbalImg: str | None = None
        self.title: str = ""
        self.artist: str = ""
        self.duration: int = 0

    # =========================================================
    # Basic metadata
    # =========================================================

    def updateTitle(self, title):

        self.title = title or ""

        return self.title

    def updateArtist(self, artist):

        self.artist = artist or ""

        return self.artist

    # =========================================================
    # Thumbnail
    # =========================================================

    def _cleanThumbalImg(
        self,
        thumbnail_url: str | None
    ):

        # This is the important fix.
        if not thumbnail_url:
            return None

        if not isinstance(
            thumbnail_url,
            str
        ):
            return None

        match = self.THUMBNAIL_RE.match(
            thumbnail_url
        )

        if match:
            return match.group(1)

        # If YouTube gives us a valid URL
        # that doesn't match the regex,
        # keep it instead of returning None.
        return thumbnail_url

    def updateThumbalImg(
        self,
        thumbnail_url
    ):

        self.thumbalImg = (
            self._cleanThumbalImg(
                thumbnail_url
            )
        )

        return self.thumbalImg

    # =========================================================
    # Duration
    # =========================================================

    def updateDuration(
        self,
        song_duration
    ):

        try:

            duration = int(
                song_duration.info.length
            )

        except (
            AttributeError,
            TypeError,
            ValueError
        ):

            duration = 0

        self.duration = duration

        return self.duration

    # =========================================================
    # Thumbnail embedding
    # =========================================================

    def _create_cover(
        self,
        output_path: str | Path = "cropped_image.png"
    ):

        if not self.thumbalImg:
            return None

        image = tagsong(
            self.thumbalImg
        )

        try:

            image_path = image.run(
                output_path
            )

            return image_path

        except Exception as e:

            print(
                f"Warning: could not process thumbnail: {e}"
            )

            return None

    # =========================================================
    # MP4 / M4A metadata
    # =========================================================

    def updateMetaData(
        self,
        audio_path
    ):

        audio_path = Path(
            audio_path
        )

        target = MP4(
            str(audio_path)
        )

        self.updateDuration(
            target
        )

        target.delete()

        target["\xa9nam"] = (
            self.title
        )

        target["\xa9ART"] = (
            self.artist
        )

        image_path = self._create_cover()

        if image_path:

            try:

                with open(
                    image_path,
                    "rb"
                ) as albumart:

                    target.tags["covr"] = [
                        MP4Cover(
                            albumart.read(),
                            imageformat=(
                                MP4Cover.FORMAT_PNG
                            )
                        )
                    ]

            finally:

                Path(
                    image_path
                ).unlink(
                    missing_ok=True
                )

        target.save()

    # =========================================================
    # FLAC metadata
    # =========================================================

    def updateFlacCover(
        self,
        audio_path
    ):

        audio_path = Path(
            audio_path
        )

        target = FLAC(
            str(audio_path)
        )

        image_path = self._create_cover()

        if not image_path:

            # No thumbnail = don't fail the
            # entire download.
            target.save()
            return

        try:

            with open(
                image_path,
                "rb"
            ) as albumart:

                image_data = (
                    albumart.read()
                )

            image = Picture()

            image.data = image_data
            image.type = 3
            image.mime = "image/png"

            target.clear_pictures()
            target.add_picture(
                image
            )

            target.save()

        finally:

            Path(
                image_path
            ).unlink(
                missing_ok=True
            )
