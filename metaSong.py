"""
This module provides functionality for handling song metadata and thumbnail images.
It includes two classes: `tagsong` for processing thumbnail images and `songsData`
for managing and updating song metadata.

Classes:
    tagsong:
        A class for downloading, cropping, and saving thumbnail images.

        Methods:
            __init__(thumbalUlr):
                Initializes the `tagsong` object with a thumbnail URL.
            replaceString():
                Replaces the default string in the thumbnail URL.
            downloadImage():
                Downloads the image from the thumbnail URL.
            getDimension():
                Retrieves the dimensions of the downloaded image.
            calculateCoordinates():
                Calculates the coordinates for cropping the image.
            cropImage():
                Crops the image to a predefined size.
            saveImage():
                Saves the cropped image to a file.
            deleteTemp():
                Deletes the temporary cropped image file.
            run():
                Executes the full process of downloading, cropping, and saving the image.

    songsData(tagsong):
        A subclass of `tagsong` for managing song metadata, including title, artist,
        duration, and album art.

        Methods:
            __init__():
                Initializes the `songsData` object with default metadata attributes.
            updateTitle(title):
                Updates the title of the song.
            updateArtist(artist):
                Updates the artist of the song.
            updateThumbalImg(thumbalImg):
                Updates the thumbnail image URL.
            updateDuration(song_duration):
                Updates the duration of the song based on its audio file.
            updateMetaData(audio_path):
                Updates the metadata of an MP4 audio file, including title, artist,
                and album art.
            updateFlacCover(audio_path):
                Updates the album art of a FLAC audio file.

"""
import cv2
import numpy as np
import requests
import os
from io import BytesIO
from mutagen.mp4 import MP4, MP4Cover
from mutagen import File
from mutagen.flac import Picture, FLAC
from mutagen.id3 import ID3, TIT2, TPE1, error, APIC
class tagsong:
    def __init__(self, thumbalUlr):
        self.thumbalUlr = thumbalUlr
        self.__defaultThumbal = "sddefault.jpg"
        self.__maxdefault = "maxresdefault.jpg"
        self.__hqdefault = "hqdefault.jpg"
        self.height = int
        self.width = int
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
        #self.thumbalUlr = self.replaceString()
        self.image = self.downloadImage()
        self.height, self.width, _ = self.getDimension()
        self.cropped_image = self.cropImage()
        self.saveImage()
        return self.cropped_image
class songsData(tagsong):
    def __init__(self):
        self.thumbalImg = str
        self.title = str
        self.artist = str
        self.duration = int
    def updateTitle(self,title):
        self.title = title
        return self.title
    def updateArtist(self,artist):
        self.artist = artist
        return self.artist
    def updateThumbalImg(self,thumbalImg):
        self.thumbalImg = thumbalImg
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
