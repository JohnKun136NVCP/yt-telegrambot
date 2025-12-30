import os
import sys
import shutil
import os.path
import re
import requests
import subprocess
import logging
from pytubefix import YouTube
from pytubefix.cli import on_progress
from metaSong import songsData


# Configure logging for errors
error_handler = logging.FileHandler("errors.log")
error_handler.setLevel(logging.ERROR)
error_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
error_handler.setFormatter(error_format)

logger = logging.getLogger("getSongs")
logger.setLevel(logging.DEBUG)  # Capture all logs, including debug
logger.addHandler(error_handler)

class downloadSongsYb:
    """
    A class to handle downloading songs from YouTube, extracting metadata, converting audio formats,
    reducing audio quality, managing file sizes, and handling thumbnails.
    Attributes:
        url (str): The YouTube video URL.
        path (str): Directory where songs are stored.
        regex (str): Regex pattern to extract YouTube video ID.
        regexArtist (str): Regex pattern to clean artist names.
        id_url (str): Extracted YouTube video ID.
        httpUrl (str): Base YouTube URL.
        completeUrl (str): Complete YouTube video URL.
        songsData (songsData): Object to store and update song metadata.
    Methods:
    
        __cleanUpdate(filename): Cleans a filename by removing invalid characters.
        regexUrl(): Extracts and returns the YouTube video ID from the URL.
        generateYbUrl(): Generates and returns the complete YouTube video URL.
        __cleanNameArtist(): Cleans the artist name using a regex pattern.
        __addMetaData(downloaded_File): Extracts and updates metadata for the downloaded file.
        __convertToFlac(audio_path): Converts an audio file to FLAC format using ffmpeg.
        __reduce_audio_quality(input_file, output_file, bitrate="128k", sample_rate="44100"):
            Reduces the quality of an audio file using ffmpeg.
        __sizeOfFile(file_path): Checks the file size and converts formats to ensure size constraints.
        download_thumbnail(url_thumbnail): Downloads a thumbnail image from a URL.
        cleanTempdir(img_path): Cleans up the temporary directory used for thumbnails.
        movedFile(): Moves downloaded audio files to the specified directory.
        download(): Downloads the audio from YouTube, processes metadata, checks file size, and moves the file.
    Raises:
        Exception: Logs errors encountered during file operations, downloads, conversions, or metadata extraction.
    """

    def __init__(self, url):
        self.url = url
        self.path = "Songs/"
        self.regex =  r'(?:\?v=|\/)([a-zA-Z0-9_-]{11})'
        self.regexSiToken = r'^.*youtu\.be/([^?]+).*$', r'\1'
        self.regexArtist = r'^(.*) - Topic$'
        self.id_url = None
        self.httpUrl = "http://youtube.com/watch?v="
        self.completeUrl = str
        self.songsData = songsData()
    def __cleanUpdate(self,filename):
        return re.sub(r'[\\/*?:"<>|]',"",filename)
    def regexUrl(self):
        match = re.search(self.regex, self.url)
        if match:
            self.id_url = match.group(1)
            return self.id_url
        else:
            self.id_url = ''
            return self.id_url
    def generateYbUrl(self):
        self.completeUrl = self.httpUrl + self.id_url
        return self.completeUrl
    def __cleanNameArtist(self):
        match = re.search(self.regexArtist, self.songsData.artist)
        if match:
            self.songsData.artist = match.group(1)
            return self.songsData.artist
        else:
            return self.songsData.artist
    def __addMetaData(self,downloaded_File):
        streams = YouTube(self.completeUrl,'WEB')
        title = u"{}".format(streams.title)
        artist = u"{}".format(streams.author)
        self.songsData.updateTitle(self.__cleanUpdate(title))
        self.songsData.updateArtist(self.__cleanUpdate(artist))
        self.__cleanNameArtist()
        self.songsData.updateThumbalImg(streams.thumbnail_url)
        file_path = downloaded_File if downloaded_File.endswith(".m4a") else f"{downloaded_File}.m4a"
        self.songsData.updateMetaData(file_path)
    def __convertToFlac(self, audio_path):
        """
        Convert the audio file to FLAC format using ffmpeg.
        """
        try:
            flac_data = audio_path.replace(".mp3", ".flac")
            if sys.platform == "linux" or sys.platform == "linux2" or sys.platform == "win32" or sys.platform == "darwin":
                subprocess.run(["ffmpeg","-i",audio_path,"-f","flac","{}.flac".format(self.songsData.title)],stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.songsData.updateFlacCover(flac_data)
        except Exception as e:
            logger.error(f"Error converting to FLAC: {e}")

    def __reduce_audio_quality(input_file, output_file, bitrate="128k", sample_rate="44100"):
        """ Reduce the quality of an MP3 or M4A file using ffmpeg. """
        try:
            command = [
                "ffmpeg", "-i", input_file,
                "-b:a", bitrate, "-ar", sample_rate,
                "-c:a", "aac" if input_file.endswith(".m4a") else "libmp3lame",
                "-y", output_file  # Overwrite existing file
            ]
            subprocess.run(command, check=True)
            print(f"Compressed file saved as: {output_file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error reducing audio quality: {e}")


    def __sizeOfFile(self,file_path):
        """
        Get the size of the file in bytes.
        """
        try:
            if os.path.exists(file_path):
                #Default file .m4a
                mb_m4a_size = os.path.getsize(file_path) / (1024 * 1024)
                if mb_m4a_size < 49.9:
                    mp3_path = file_path.replace(".m4a",".mp3")
                    subprocess.run(["ffmpeg","-i",file_path,"-ar","44100","{}.mp3".format(self.songsData.title)],stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    mb_mp3_size = os.path.getsize(mp3_path) / (1024 * 1024)
                    if  mb_mp3_size < 49.9:
                        # Convert to flac
                        self.__convertToFlac(mp3_path)
                        flac_data = mp3_path.replace(".mp3", ".flac")
                        flac_mb_size = os.path.getsize(flac_data) / (1024 * 1024)
                        if flac_mb_size < 49.9:
                            os.remove(mp3_path)
                            os.remove(file_path)
                        else:
                            os.remove(file_path)
                            os.remove(flac_data)
                elif mb_m4a_size > 49.9:
                    # Convert to mp3
                    mp3_path = file_path.replace(".m4a",".mp3")
                    subprocess.run(["ffmpeg","-i",file_path,"-ar","22050","{}.mp3".format(self.songsData.title)],stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    mb_mp3_size = os.path.getsize(mp3_path) / (1024 * 1024)
                    os.remove(file_path)
                else:
                    # Convert to mp3
                    mp3_path = file_path.replace(".m4a",".mp3")
                    self.reduce_audio_quality(file_path, mp3_path, bitrate="96k", sample_rate="32000")
                    mb_mp3_size = os.path.getsize(mp3_path) / (1024 * 1024)
                    if mb_mp3_size> 50:
                        print("File size is greater than 50MB")
                        print("Error: File size is greater than 50MB")
                    else:
                        os.remove(file_path)
        except Exception as e:
            logger.error(f"Error getting file size: {e}")

    def download_thumbnail(self,url_thumbnail):
        try:
            if url_thumbnail is not None:
                temp_dir = os.path.join(os.getcwd(), "temp")
                os.makedirs(temp_dir, exist_ok=True)
                img_path = os.path.join(temp_dir, "thumb.jpg")
                response = requests.get(url_thumbnail)
                if response.status_code == 200:
                    with open(img_path, "wb") as img:
                        img.write(response.content)
                    return img_path
                else:
                    shutil.rmtree(temp_dir)
                    return None
            else:return None    
        except Exception as e:
            logger.error(f"Error downloading thumbnail: {e}")
            return None
    def cleanTempdir(self,img_path):
        if img_path:
            temp_dir = os.path.join(os.getcwd(), "temp")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
    def movedFile(self):
        """
        Move downloaded audio files to the specified directory.
        """
        try:
            current_path = os.getcwd()  # Get the current working directory
            new_dir_path = os.path.join(current_path, self.path)  # Create a new directory path
            if not os.path.exists(self.path):
                os.makedirs(self.path)  # Create the directory if it doesn't exist
            # List of supported file extensions
            supported_formats = [".m4a", ".mp3", ".flac"]
            for filename in os.listdir(current_path):
                if any(filename.endswith(ext) for ext in supported_formats): 
                    source_file = os.path.join(current_path, filename)
                    dest_file = os.path.join(new_dir_path, filename)
                    shutil.move(source_file, dest_file)
        except Exception as e:logger.error(f"Error moving file: {e}")  
    def download(self):
        try:
            yt =  YouTube(self.completeUrl)
            ys = yt.streams.get_audio_only()
            downloaded_File = ys.download()
            self.__addMetaData(downloaded_File)
            self.__sizeOfFile(downloaded_File)
            self.movedFile()
        except Exception as e:logger.error(f"Error downloading video: {e}")