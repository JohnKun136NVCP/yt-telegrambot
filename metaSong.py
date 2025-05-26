import cv2
import numpy as np
import requests
import os
import re
from io import BytesIO
from mutagen.mp4 import MP4, MP4Cover
from mutagen import File
from mutagen.flac import Picture, FLAC
from mutagen.id3 import ID3, TIT2, TPE1, error, APIC
class tagsong:
    """
    A class for handling YouTube thumbnail images, including downloading, cropping, and saving.
    The class supports different thumbnail resolutions and can trim black borders for high-quality images.
    Attributes:

        thumbalUlr (str): URL of the thumbnail image.
        height (int): Height of the image.
        width (int): Width of the image.
        cropped_image (np.ndarray): Cropped or processed image.
        image (np.ndarray): Original downloaded image.

    Methods:

        __init__(thumbalUlr):
            Initializes the tagsong object with the given thumbnail URL.
        __setSizeDefault():
            Determines the crop size based on the thumbnail type.
        __trim_black_borders(img: np.ndarray, tol: int = 10) -> np.ndarray:
            Trims black borders from the image using a tolerance value.
        downloadImage():
            Downloads the image from the provided URL and decodes it as a NumPy array.
        getDimension():
            Returns the dimensions (height, width, channels) of the image.
        calculateCoordinates():
            Calculates the starting coordinates for cropping the image to the desired size.
        cropImage():
            Crops the image to the determined size based on the thumbnail type.
        saveImage():
            Saves the cropped image as "cropped_image.png" in the current directory.
        deleteTemp():
            Deletes the temporary cropped image file from the current directory.
        run():
            Main method to process the image: downloads, crops or trims, saves, and returns the processed image.
    """
    def __init__(self, thumbalUlr):
        self.thumbalUlr = thumbalUlr
        self.__defaultThumbal = "sddefault.jpg"
        self.__maxdefault = "maxresdefault.jpg"
        self.__hqdefault = "hqdefault.jpg"
        self.height = int
        self.width = int
        self.cropped_image = None
        self.image = None
        self.__cropSize = int #350 sddefault; 720 maxresdefault; 480 hqdefault;
    def __setSizeDefault(self):
        if self.thumbalUlr.endswith(self.__defaultThumbal):
            self.__cropSize = 350
        elif self.thumbalUlr.endswith(self.__maxdefault):
            self.__cropSize = 720
        elif self.thumbalUlr.endswith(self.__hqdefault):
            self.__cropSize = 480
        else:
            self.__cropSize = 750
        return self.__cropSize
    def __trim_black_borders(self, img: np.ndarray, tol: int = 10) -> np.ndarray:
        non_black = (img > tol).any(axis=2)
        rows = np.where(non_black.any(axis=1))[0]
        cols = np.where(non_black.any(axis=0))[0]
        if rows.size and cols.size:
            y1, y2 = rows[0], rows[-1]
            x1, x2 = cols[0], cols[-1]
            return img[y1:y2+1, x1:x2+1]
        return img
    def downloadImage(self):
        response = requests.get(self.thumbalUlr)
        image_np = np.asarray(bytearray(response.content), dtype=np.uint8)
        return cv2.imdecode(image_np, cv2.IMREAD_COLOR)
    def getDimension(self):
        return self.image.shape
    def calculateCoordinates(self):
        self.__setSizeDefault()
        return (self.width - self.__cropSize) // 2, (self.height - self.__cropSize) // 2
    def cropImage(self):
        self.__setSizeDefault()
        x_start, y_start = self.calculateCoordinates()
        return self.image[y_start:y_start + self.__cropSize, x_start:x_start + self.__cropSize]
    def saveImage(self):
        return cv2.imwrite("cropped_image.png", self.cropped_image)
    def deleteTemp(self):
        temp_dir = os.path.join(os.getcwd(), "cropped_image.png")
        os.remove(temp_dir)
    def run(self):
        """
        Executes the main image processing workflow.
        Downloads an image, checks if the thumbnail URL ends with a specific suffix,
        and processes the image accordingly. If the URL does not end with the expected
        suffix, the image is cropped and saved after retrieving its dimensions.
        Otherwise, black borders are trimmed from the image before saving.
        Returns:
            np.ndarray: The processed (cropped or trimmed) image.
        """
        self.image = self.downloadImage()
        if not self.thumbalUlr.endswith(self.__hqdefault):
            self.height, self.width, _ = self.getDimension()
            self.cropped_image = self.cropImage()
            self.saveImage()
        else:
            self.cropped_image = self.__trim_black_borders(self.image)
            self.saveImage()
        return self.cropped_image

class songsData(tagsong):
    """
    songsData class for managing and updating song metadata and cover images.
    Inherits from:
        tagsong
    Attributes:
        thumbalImg (str): Path or URL to the song's thumbnail image.
        title (str): Title of the song.
        artist (str): Artist of the song.
        duration (int): Duration of the song in seconds.
        __regexThumbalImage (str): Regular expression for extracting image filename.
    Methods:
    
        __init__():
            Initializes the songsData object with default values.
        updateTitle(title):
            Updates the song's title.
            Args:
                title (str): The new title of the song.
            Returns:
                str: The updated title.
        updateArtist(artist):
            Updates the song's artist.
            Args:
                artist (str): The new artist of the song.
            Returns:
                str: The updated artist.
        __cleanThumbalImg(thumbalImg):
            Cleans the thumbnail image filename using a regex.
            Args:
                thumbalImg (str): The thumbnail image filename or path.
            Returns:
                str: The cleaned image filename if matched, else None.
        updateThumbalImg(thumbalImg):
            Updates the thumbnail image after cleaning.
            Args:
                thumbalImg (str): The new thumbnail image filename or path.
            Returns:
                str: The updated thumbnail image filename.
        updateDuration(song_duration):
            Updates the duration of the song.
            Args:
                song_duration: An object with an 'info.length' attribute representing duration in seconds.
            Returns:
                int: The updated duration.
        updateMetaData(audio_path):
            Updates the metadata (title, artist, cover image) of an MP4 audio file.
            Args:
                audio_path (str): Path to the MP4 audio file.
        updateFlacCover(audio_path):
            Updates the cover image of a FLAC audio file.
            Args:
                audio_path (str): Path to the FLAC audio file.
    """
    def __init__(self):
        self.thumbalImg = str
        self.title = str
        self.artist = str
        self.duration = int
        self.__regexThumbalImage = r"^(.*?\.jpg)"
    def updateTitle(self,title):
        self.title = title
        return self.title
    def updateArtist(self,artist):
        self.artist = artist
        return self.artist
    def __cleanThumbalImg(self,thumbalImg):
        match = re.match(self.__regexThumbalImage, thumbalImg)
        if match:
            result = match.group(1)
            return result
    def updateThumbalImg(self,thumbalImg):
        self.thumbalImg = self.__cleanThumbalImg(thumbalImg)
        return self.thumbalImg
    def updateDuration(self,song_duration):
        song_duration = song_duration.info.length
        duration = int(song_duration)
        self.duration = duration
        return self.duration
    def updateMetaData(self,audio_path):
        targetNmae = MP4(audio_path)
        self.updateDuration(targetNmae)
        targetNmae.delete()
        self.title = self.title.encode('utf-8').decode('utf-8')
        self.artist = self.artist.encode('utf-8').decode('utf-8')
        targetNmae["\xa9nam"] = self.title
        targetNmae["\xa9ART"] = self.artist
        self.updateThumbalImg(self.thumbalImg)
        image_photo = tagsong(self.thumbalImg)
        image_photo.run()
        path_img = os.path.join(os.getcwd(), "cropped_image.png")
        with open(path_img, 'rb') as albumart:
            targetNmae.tags['covr'] = [MP4Cover(albumart.read(), imageformat=MP4Cover.FORMAT_PNG)]
        targetNmae.save()
        image_photo.deleteTemp()
    def updateFlacCover(self,audio_path):
        target = File(audio_path)
        self.updateThumbalImg(self.thumbalImg)
        image_photo = tagsong(self.thumbalImg)
        image_photo.run()
        path_img = os.path.join(os.getcwd(), "cropped_image.png")
        with open(path_img, 'rb') as albumart:
                image_data = albumart.read()
        img = Picture()
        img.data = image_data
        img.type = 3
        img.mime = "image/png"
        target.add_picture(img)
        target.save()
        image_photo.deleteTemp()
