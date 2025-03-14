import os
import sys
import shutil
import os.path
import ssl
import re
import sqlite3
import requests
from datetime import datetime,timedelta
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, TIT2, TPE1, error
from pytubefix import YouTube
from pytubefix.cli import on_progress
from metaSong import songsData



class downloadSongsYb:
    def __init__(self, url):
        self.url = url
        self.path = "Songs/"
        self.regex =  r'(?:\?v=|\/)([a-zA-Z0-9_-]{11})'
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
        streams = YouTube(self.completeUrl,on_complete_callback=on_progress)
        title = u"{}".format(streams.title)
        artist = u"{}".format(streams.author)
        self.songsData.updateTitle(self.__cleanUpdate(title))
        self.songsData.updateArtist(self.__cleanUpdate(artist))
        self.__cleanNameArtist()
        self.songsData.updateThumbalImg(streams.thumbnail_url)
        file_path = downloaded_File if downloaded_File.endswith(".m4a") else f"{downloaded_File}.m4a"
        self.songsData.updateMetaData(file_path)
    def download_thumbnail(self,url_thumbnail):
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        channel TEXT,
        uri TEXT,
        duration INTEGER,
        thumbnail_url TEXT
        );'''
        self.cursor.execute(self.db_create_query)
    def isOntheDatabase(self,uri):
        self.cursor.execute('SELECT * FROM songs WHERE uri = ?',(uri,))
        result = self.cursor.fetchone()
        if result:
            return True
        else:
            return False
    def insertData(self,title,artist,id_url,duration,thumbalImg):
        self.cursor.execute('''
        SELECT * FROM songs WHERE name = ? AND channel = ? AND uri = ? AND duration = ? AND thumbnail_url = ?''', (title,artist,id_url,duration,thumbalImg))
        result = self.cursor.fetchone()
        if result:
            return True
        else:
            title = title.encode('utf-8').decode('utf-8')
            artist = artist.encode('utf-8').decode('utf-8')
            self.cursor.execute('''
            INSERT INTO songs (name,channel,uri,duration,thumbnail_url) VALUES (?,?,?,?,?)''',(title,artist,id_url,duration,thumbalImg))
            self.connect.commit()
            return False
    def verifyURL(self,id_url):
        self.cursor.execute('SELECT * FROM songs WHERE uri = ?',(id_url,))
        result = self.cursor.fetchone()
        if result:return (True,result)
        else:return (False,False)
    def updateSong(self, song_id, duration, thumbnail_url):
        update_query = '''UPDATE songs SET duration = ?, thumbnail_url = ? WHERE id = ?'''
        self.cursor.execute(update_query, (duration, thumbnail_url, song_id))
        self.connect.commit()
    def deletingDatabase(self):
        self.cursor.execute('SELECT * FROM songs WHERE id = 40')
        result = self.cursor.fetchone() 
        if result:
            self.cursor.execute('DELETE FROM songs')
            self.connect.commit()
        else:pass