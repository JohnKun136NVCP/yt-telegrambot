import sqlite3
import os
import re
import sys
import cv2
import numpy as np
import requests
import os
import subprocess
from io import BytesIO
from mutagen.mp4 import MP4, MP4Cover
from mutagen import File
from mutagen.flac import Picture, FLAC
from mutagen.id3 import ID3, TIT2, TPE1, error, APIC
from difflib import SequenceMatcher as sm
class tagsong:
    def __init__(self, thumbalUlr):
        self.thumbalUlr = thumbalUlr
        self.__setStringDefault = "sddefault.jpg"
        self.height = int
        self.width = int
        self.__cropSize = 350
    def replaceString(self):
        return self.thumbalUlr.replace(self.__setStringDefault, self.__setStringDefault)
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
        return cv2.imwrite("Songs/cropped_image.png", self.cropped_image)
    def deleteTemp(self):
        temp_dir = os.path.join(os.getcwd(), "Songs/cropped_image.png")
        os.remove(temp_dir)
    def run(self):
        self.thumbalUlr = self.replaceString()
        self.image = self.downloadImage()
        self.height, self.width, _ = self.getDimension()
        self.cropped_image = self.cropImage()
        self.saveImage()
        return self.cropped_image
class dataBase:
    def __init__(self):
        self.connect = sqlite3.connect("idSongs.db")
        self.cursor = self.connect.cursor()
        self.db_create_query = '''CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY,
            name TEXT,
            channel TEXT,
            uri TEXT,
            duration INTEGER,
            thumbnail_url TEXT
        );'''
        self.cursor.execute(self.db_create_query)
        self.cursor.execute('PRAGMA table_info(songs)')
        columns = [col[1] for col in self.cursor.fetchall()]
        if 'duration' not in columns:
            self.cursor.execute('ALTER TABLE songs ADD COLUMN duration REAL')
        if 'thumbnail_url' not in columns:
            self.cursor.execute('ALTER TABLE songs ADD COLUMN thumbnail_url TEXT')
        self.connect.commit()

    def cleanString(self, filename):
        return re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    def showDatabase(self):
        self.cursor.execute('SELECT * FROM songs')
        result = self.cursor.fetchall()
        for row in result:
            print(row)
    
    def deleteById(self, song_id):
        self.cursor.execute('SELECT * FROM songs WHERE id = ?', (song_id,))
        results = self.cursor.fetchone()
        if results:
            self.cursor.execute('DELETE FROM songs WHERE id = ?', (song_id,))
            self.connect.commit()
            song_title = results[1]
            current_path = os.getcwd()
            file_path = os.path.join(current_path, "Songs/", self.cleanString(song_title) + ".flac")

            if os.path.exists(file_path):
                os.remove(file_path)

            # Reorder the IDs
            self.reorderIds()
            print("Song deleted and IDs reordered")
        else:
            print("No song found with that id")
    def addSong(self, name, channel, uri, thumbnail_url):
        audio = MP4(uri)
        duration = audio.info.length
        insert_query = '''INSERT INTO songs (name, channel, uri, duration, thumbnail_url) 
                          VALUES (?, ?, ?, ?, ?);'''
        self.cursor.execute(insert_query, (name, channel, uri, duration, thumbnail_url))
        self.connect.commit()
    
    def updateDurations(self):
        current_path = os.getcwd()
        songs_dir = os.path.join(current_path, "Songs/")
        for root, dirs, files in os.walk(songs_dir):
            for file in files:
                if file.endswith(".m4a"):
                    file_path = os.path.join(root, file)
                    audio = MP4(file_path)
                    duration = audio.info.length
                    duration = int(duration)
                    song_title = os.path.splitext(file)[0]
                    song_title = self.cleanString(song_title)
                    self.cursor.execute("UPDATE songs SET duration = ? WHERE name = ?", (duration, song_title))
        self.connect.commit()
    def reorder_ids(self):
        # Eliminar la tabla temporal si ya existe
        self.cursor.execute('DROP TABLE IF EXISTS temp_songs')
        # Create a new temporary table with AUTOINCREMENT for id
        self.cursor.execute('''
            CREATE TABLE temp_songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                channel TEXT,
                uri TEXT,
                duration INTEGER,
                thumbnail_url TEXT
            );
        ''')
        self.cursor.execute('''
            INSERT INTO temp_songs (name, channel, uri, duration, thumbnail_url)
            SELECT name, channel, uri, duration, thumbnail_url
            FROM songs;
        ''')
        self.cursor.execute('DROP TABLE songs')
        self.cursor.execute('ALTER TABLE temp_songs RENAME TO songs')
    def fetch_songs(self):
        # Fetch title and thumbnail_url from the database
        fetch_query = "SELECT name, thumbnail_url FROM songs"
        self.cursor.execute(fetch_query)
        return self.cursor.fetchall()
    def updateThumbnails(self,directory="/Songs"):
        songs_db = self.fetch_songs()
        try:
            current_path = os.getcwd()
            new_dir_path = os.path.join(current_path, "Songs/")
            for title, url in songs_db:
                for root, dirs, files in os.walk(new_dir_path):
                    for file in files:
                        if file.endswith(".flac") and title in file:
                                coverImage = tagsong(url)
                                coverImage.run()
                                song_path = os.path.join(os.getcwd(), f"Songs/{file}")
                                target = File(song_path)
                                path_img = os.path.join(os.getcwd(), "Songs/cropped_image.png")
                                img = Picture()
                                img.type = 3
                                with open(path_img, 'rb') as albumart:
                                        img.data = albumart.read()
                                target.add_picture(img)
                                target.save()
                                coverImage.deleteTemp()
                        elif sm(None,str(file),str(title)).ratio()>0.9 or sm(None,str(file),str(title)).ratio()>0.75:
                            temp_title = file
                            if file.endswith(".flac") and temp_title in file:
                                coverImage = tagsong(url)
                                coverImage.run()
                                song_path = os.path.join(os.getcwd(), f"Songs/{file}")
                                target = File(song_path)
                                path_img = os.path.join(os.getcwd(), "Songs/cropped_image.png")
                                img = Picture()
                                img.type = 3
                                with open(path_img, 'rb') as albumart:
                                        img.data = albumart.read()
                                target.add_picture(img)
                                target.save()
                                coverImage.deleteTemp()
                                coverImage.deleteTemp()
        except Exception as e:
            print(f"Failed to download cover for '{title}': {e}")
    def m4aToFlac(self, directory="/Songs"):
        for filename in os.listdir(directory):
            if filename.endswith(".m4a"):
                audio_path = os.path.join(directory, filename)
                flac_data = audio_path.replace(".m4a", ".flac")
                try:
                    if sys.platform == "linux" or sys.platform == "linux2" or sys.platform == "win32" or sys.platform == "darwin":
                        subprocess.run(["ffmpeg", "-i", audio_path, "-f", "flac", flac_data], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self.updateThumbnails()
                except Exception as e:
                    print(f"Error converting {audio_path} to FLAC: {e}")
                    print("Please check if ffmpeg is installed and available in your PATH.")
                    continue
                os.remove(audio_path)  # Delete original .m4a file
def main():
    dbs = dataBase()
    print("Show database: showdb\nReorderIDS: reorderid\nDelete song: delete\nAdd song: add\nUpdate thumbal images: upthum\nUpdate durations: updatedurations\nUpdate to Flac: flc\nQuit: q")
    for line in sys.stdin:
        if 'q' == line.rstrip():
            break
        elif 'showdb' == line.rstrip():
            dbs.showDatabase()
        elif 'reorderid' == line.rstrip():
            dbs.reorder_ids()
            print("IDs reordered")
        elif 'delete' == line.rstrip():
            try:
                dbs.showDatabase()
                id_input = int(input("Enter the id of the song you want to delete: "))
                dbs.deleteById(id_input)
                print("Song deleted")
            except:
                print("Invalid input")
        elif 'add' == line.rstrip():
            try:
                name = input("Enter the name of the song: ")
                channel = input("Enter the channel name: ")
                uri = input("Enter the path to the song file: ")
                thumbnail_url = input("Enter the thumbnail URL: ")
                dbs.addSong(name, channel, uri, thumbnail_url)
                print("Song added")
            except:
                print("Invalid input")
        elif 'upthum' == line.rstrip():
            try:
                dbs.updateThumbnails()
                print("Thumbnails updated")
            except:
                print("Invalid input")
        elif 'updatedurations' == line.rstrip():
            dbs.updateDurations()
            print("Durations updated")
        elif 'flc' == line.rstrip():
            dbs.m4aToFlac()
            print("Converted to FLAC")
        print("Show database: showdb\nReorderIDS: reorderid\nDelete song: delete\nAdd song: add\nUpdate thumbal images: upthum\nUpdate durations: updatedurations\nUpdate to Flac: flc\nQuit: q")

if __name__ == "__main__":
    main()
