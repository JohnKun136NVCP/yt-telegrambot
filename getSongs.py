import os
import sys
import shutil
import os.path
import ssl
import re
import sqlite3
from datetime import datetime,timedelta
from mutagen.mp4 import MP4
from mutagen.id3 import ID3, TIT2, TPE1, error
from pytubefix import YouTube
from pytubefix.cli import on_progress



class downloadSongsYb:
    def __init__(self, url):
        self.url = url
        self.path = "Songs/"
        self.regex =  r'(?:\?v=|\/)([a-zA-Z0-9_-]{11})'
        self.regexArtist = r'^(.*) - Topic$'
        self.id_url = None
        self.thumbalImg = str
        self.httpUrl = "http://youtube.com/watch?v="
        self.completeUrl = str
        self.title = str
        self.artist = str
    def __updateTitle(self,title):
        self.title = title
        return self.title
    def __updateArtist(self,artist):
        self.artist = artist
        return self.artist
    def __updateThumbalImg(self,thumbalImg):
        self.thumbalImg = self.thumbalImg
        return self.thumbalImg
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
        match = re.search(self.regexArtist, self.artist)
        if match:
            self.artist = match.group(1)
            return self.artist
        else:
            return self.artist
    def __addMetaData(self,downloaded_File):
        streams = YouTube(self.completeUrl,on_complete_callback=on_progress)
        title = u"{}".format(streams.title)
        artist = u"{}".format(streams.author)
        self.__updateTitle(title)
        self.__updateArtist(artist)
        self.__cleanNameArtist()
        self.__updateThumbalImg(streams.thumbnail_url)
        file_path = downloaded_File if downloaded_File.endswith(".m4a") else f"{downloaded_File}.m4a"
        targetNmae = MP4(file_path)
        targetNmae.delete()
        targetNmae["\xa9nam"] = self.title
        targetNmae["\xa9ART"] = self.artist
        targetNmae.save()
    def movedFile(self):
        """
        Move downloaded audio files to the specified directory.
        """
        try:
            current_path = os.getcwd()  # Get the current working directory
            new_dir_path = os.path.join(current_path, self.path)  # Create a new directory path
            if not os.path.exists(self.path):
                os.makedirs(self.path)  # Create the directory if it doesn't exist
            for filename in os.listdir(current_path):
                if filename.endswith('.m4a'):
                    source_file = os.path.join(current_path, filename)  # Define the source file path
                    dest_file = os.path.join(new_dir_path, filename)  # Define the destination file path
                    shutil.move(source_file, dest_file)  # Move the file to the new directory
        except Exception as e:pass
    def download(self):
        yt =  YouTube(self.completeUrl,on_progress_callback=on_progress)
        ys = yt.streams.get_audio_only()
        downloaded_File = ys.download()
        self.__addMetaData(downloaded_File)
        self.movedFile()


class dataBase():
    def __init__(self):
        self.connect = sqlite3.connect("idSongs.db")
        self.cursor = self.connect.cursor()
        self.db_create_query = '''CREATE TABLE IF NOT EXISTS songs (
        id INTEGER PRIMARY KEY,
        name TEXT,
        channel TEXT,
        uri TEXT
        );'''
        self.cursor.execute(self.db_create_query)
    def isOntheDatabase(self,uri):
        self.cursor.execute('SELECT * FROM songs WHERE uri = ?',(uri,))
        result = self.cursor.fetchone()
        if result:
            return True
        else:
            return False
    def insertData(self,title,artist,id_url):
        self.cursor.execute('''
        SELECT * FROM songs WHERE name = ? AND channel = ? AND uri = ?''', (title,artist,id_url))
        result = self.cursor.fetchone()
        if result:
            return True
        else:
            self.cursor.execute('''
            INSERT INTO songs (name,channel,uri) VALUES (?,?,?)''',(title,artist,id_url))
            self.connect.commit()
            return False
    def verifyURL(self,id_url):
        self.cursor.execute('SELECT * FROM songs WHERE uri = ?',(id_url,))
        result = self.cursor.fetchone()
        if result:return result
        else:return None
    def deletingDatabase(self):
        self.cursor.execute('SELECT * FROM songs WHERE id = 40')
        result = self.cursor.fetchone() 
        if result:
            self.cursor.execute('DELETE FROM songs')
            self.connect.commit()
        else:pass