import cv2
import numpy as np
import requests
import os
from io import BytesIO
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, TIT2, TPE1, error, APIC
class tagsong:
    def __init__(self, thumbalUlr):
        self.thumbalUlr = thumbalUlr
        self.__setStringDefault = "sddefault.jpg"
        self.__setStringMax = "maxresdefault.jpg"
        self.height = int
        self.width = int
        self.__cropSize = 720
    def replaceString(self):
        return self.thumbalUlr.replace(self.__setStringDefault, self.__setStringMax)
    def downloadImage(self):
        response = requests.get(self.thumbalUlr)
        image_np = np.asarray(bytearray(response.content), dtype=np.uint8)
        return cv2.imdecode(image_np, cv2.IMREAD_COLOR)
    def getDimension(self):
        return self.image.shape
    def calculateCoordinates(self):
        return (self.width - self.__cropSize) // 2, (self.height - self.__cropSize) // 2
    def cropImage(self):
        x_start, y_start = self.calculateCoordinates()
        return self.image[y_start:y_start + self.__cropSize, x_start:x_start + self.__cropSize]
    def saveImage(self):
        return cv2.imwrite("cropped_image.png", self.cropped_image)
    def deleteTemp(self):
        temp_dir = os.path.join(os.getcwd(), "cropped_image.png")
        os.remove(temp_dir)
    def run(self):
        self.thumbalUlr = self.replaceString()
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
