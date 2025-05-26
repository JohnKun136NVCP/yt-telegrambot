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
    """
    A class for downloading, cropping, and saving a song thumbnail image.
    Attributes:
        thumbalUlr (str): The URL of the thumbnail image.
        height (int): The height of the downloaded image.
        width (int): The width of the downloaded image.
        __setStringDefault (str): The default string to be replaced in the URL.
        __cropSize (int): The size (in pixels) of the square crop.
        image (np.ndarray): The downloaded image as a NumPy array.
        cropped_image (np.ndarray): The cropped image as a NumPy array.
    Methods:
        replaceString():
            Replaces the default string in the thumbnail URL.
        downloadImage():
            Downloads the image from the thumbnail URL and decodes it into a NumPy array.
        getDimension():
            Returns the dimensions (height, width, channels) of the image.
        calculateCoordinates():
            Calculates the starting coordinates for cropping the image to a square.
        cropImage():
            Crops the image to a square of size __cropSize centered in the image.
        saveImage():
            Saves the cropped image to the "Songs/cropped_image.png" file.
        deleteTemp():
            Deletes the temporary cropped image file.
        run():
            Executes the full pipeline: replaces the URL string, downloads the image,
            gets dimensions, crops, saves, and returns the cropped image.
    """

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
    """
    dataBase class for managing songs and users in SQLite databases.
    This class provides methods to interact with two SQLite databases:
    one for storing song metadata and another for storing user information.
    It supports adding, deleting, updating, and fetching songs and users,
    as well as managing song thumbnails and audio file metadata.
    Attributes:

        connect (sqlite3.Connection): Connection to the songs database.
        cursor (sqlite3.Cursor): Cursor for the songs database.
        connect_usrs (sqlite3.Connection): Connection to the users database.
        cursor_usrs (sqlite3.Cursor): Cursor for the users database.
        db_create_query_usrs (str): SQL query to create the users table.
        db_create_query (str): SQL query to create the songs table.
    Methods:

        closesong():
            Closes the songs database connection.
        closeuser():
            Closes the users database connection.
        cleanString(filename):
            Cleans a filename string by replacing invalid characters.
        showDatabase():
            Displays the contents of the selected database (songs or users).
        deleteById(song_id):
            Deletes a song by its ID from the songs database and removes its audio file.
        addSong(name, channel, uri, thumbnail_url):
            Adds a new song to the songs database with metadata.
        updateDurations():
            Updates the duration field for all songs in the database by reading audio files.
        update_thumbnail():
            Updates thumbnail URLs for all songs or a specific song.
        reorder_ids():
            Reorders the IDs in the songs or users database to be sequential.
        fetch_songs():
            Fetches the name and thumbnail URL of all songs from the database.
        updateThumbnails(directory="/Songs"):
            Updates embedded thumbnails in audio files based on database URLs.
    Private Methods:
    
        __extract_thumbnail(url):
            Extracts the thumbnail image URL from a given string.
        __fetch_thumbnail(song_id):
            Fetches and processes the thumbnail URL for a specific song.
        __update_all_thumbnails():
            Updates all thumbnail URLs in the songs database.
    """

    def __init__(self):
        self.connect = sqlite3.connect("idSongs.db")
        self.cursor = self.connect.cursor()
        self.connect_usrs = sqlite3.connect("users.db")
        self.cursor_usrs = self.connect_usrs.cursor()
        self.db_create_query_usrs = '''CREATE TABLE IF NOT EXISTS users (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                telegram_id INTEGER UNIQUE,
                                username TEXT);'''
    
        self.cursor_usrs.execute(self.db_create_query_usrs)
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
    def closesong(self):
        """Closes the database connection."""
        self.cursor.close()
        self.connect.close()
    def closeuser(self):
        """Closes the database connection."""
        self.cursor_usrs.close()
        self.connect_usrs.close()

    def cleanString(self, filename):
        return re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    def showDatabase(self):
        db_select = int(input("Select the database to show: 1. songs\n 2. Users IDs\n"))
        if db_select == 1:
            self.cursor.execute('SELECT * FROM songs')
            result = self.cursor.fetchall()
            for row in result:
                print(row)
        elif db_select == 2:
            self.cursor_usrs.execute("SELECT * FROM users")
            result = self.cursor_usrs.fetchall()
            for row in result:
                print(row)
        else:
            print("Invalid selection")
    
    def deleteById(self, song_id):
        print("Only for Songs database")
        self.cursor.execute('SELECT * FROM songs WHERE id = ?', (song_id,))
        results = self.cursor.fetchone()
        if results:
            self.cursor.execute('DELETE FROM songs WHERE id = ?', (song_id,))
            self.connect.commit()
            song_title = results[1]
            current_path = os.getcwd()
            file_path = os.path.join(current_path, "Songs/", self.cleanString(song_title) + ".m4a")

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
    def __extract_thumbnail(self, url):
        pattern = r"^(.*?\.jpg)"
        match = re.match(pattern, url)
        return match.group(1) if match else url
    def __fetch_thumbnail(self, song_id):
        self.cursor.execute("SELECT thumbnail_url FROM songs WHERE id = ?", (song_id,))
        result = self.cursor.fetchone()
        if result:
            return self.__extract_thumbnail(result[0])
        return None
    def __update_all_thumbnails(self):
        self.cursor.execute("SELECT id, thumbnail_url FROM songs")
        songs = self.cursor.fetchall()
        if not songs:
            print("No songs found in the database.")
            return
        for song_id, thumbnail_url in songs:
            if thumbnail_url:
                cleaned_url = self.__extract_thumbnail(thumbnail_url)
                update_query = '''UPDATE songs SET thumbnail_url = ? WHERE id = ?'''
                self.cursor.execute(update_query, (cleaned_url, song_id))
        
        self.connect.commit()
        print(f"Updated {len(songs)} thumbnail URLs successfully!")
    def update_thumbnail(self):
        option = int(input("Choose all songs to update thumbnails: 1. All songs\n2. Specific song\n"))
        if option == 1:
            print("Updating thumbnails for all songs...")
            self.__update_all_thumbnails()
            print("All thumbnails updated successfully!")
        elif option == 2:
            self.cursor.execute('SELECT * FROM songs')
            result = self.cursor.fetchall()
            for row in result:
                print(row)
            song_id = int(input("Enter the id of the song you want to update thumbnail: "))
            print("Updating thumbnail for song ID:", song_id)
            thumbnail_url = self.__fetch_thumbnail(song_id)
            if thumbnail_url:
                update_query = '''UPDATE songs SET thumbnail_url = ? WHERE id = ?'''
                self.cursor.execute(update_query, (thumbnail_url, song_id))
                self.connect.commit()
                print(f"Thumbnail URL updated to: {thumbnail_url} for song ID {song_id}")
            else:
                print(f"No thumbnail found for song ID {song_id}, update skipped.")
    def reorder_ids(self):
        option = input("Choose the database to reorder IDs: 1. songs\n2. Users IDs\n")
        if option == "1":
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
        else:
            # Eliminar la tabla temporal si ya existe
            self.cursor_usrs.execute('DROP TABLE IF EXISTS temp_users')
            # Create a new temporary table with AUTOINCREMENT for id
            self.cursor_usrs.execute('''
                CREATE TABLE temp_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    username TEXT
                );
            ''')
            self.cursor_usrs.execute('''
                INSERT INTO temp_users (telegram_id, username)
                SELECT telegram_id, username
                FROM users;
            ''')
            self.cursor_usrs.execute('DROP TABLE users')
            self.cursor_usrs.execute('ALTER TABLE temp_users RENAME TO users')
    def fetch_songs(self):
        # Fetch title and thumbnail_url from the database
        fetch_query = "SELECT name, thumbnail_url FROM songs"
        self.cursor.execute(fetch_query)
        return self.cursor.fetchall()

    def updateThumbnails(self, directory="/Songs"):
        songs_db = self.fetch_songs()
        try:
            current_path = os.getcwd()
            new_dir_path = os.path.join(current_path, "Songs/")

            # List of supported formats
            supported_formats = [".flac", ".mp3", ".m4a"]

            for title, url in songs_db:
                for root, dirs, files in os.walk(new_dir_path):
                    for file in files:
                        if any(file.endswith(ext) for ext in supported_formats) and title in file:
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

                        elif sm(None, str(file), str(title)).ratio() > 0.9 or sm(None, str(file), str(title)).ratio() > 0.75:
                            temp_title = file
                            if any(temp_title.endswith(ext) for ext in supported_formats):
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

        except Exception as e:
            print(f"Failed to download cover for '{title}': {e}")
def main():
    """
    Main command-line interface loop for managing the song database.
    This function provides an interactive CLI for performing various operations on the song database,
    including displaying the database, reordering IDs, deleting songs, adding new songs, updating
    thumbnail images, updating song durations, and quitting the program.
    Commands:

        showdb         - Display the current database.
        reorderid      - Reorder the IDs of the songs in the database.
        delete         - Delete a song by its ID.
        add            - Add a new song to the database.
        upthum         - Update all thumbnail images in the database.
        updatedurations- Update the durations of all songs.
        thumbup        - Update the thumbnail image for a specific song.
        q              - Quit the CLI.
    The function reads commands from standard input and executes the corresponding database operations.
    """

    dbs = dataBase()
    print("Show database: showdb\nReorderIDS: reorderid\nDelete song: delete\nAdd song: add\nUpdate thumbal images: upthum\nUpdate durations: updatedurations\nUpdate ThumbalImg: thumbup\nQuit: q")
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
            dbs.updateThumbnails()
            print("Thumbnails updated")
        elif 'updatedurations' == line.rstrip():
            dbs.updateDurations()
            print("Durations updated")
        elif 'thumbup' == line.rstrip():
            try:
                dbs.update_thumbnail()
                print("Thumbnail updated")
            except:
                print("Invalid input")
        print("Show database: showdb\nReorderIDS: reorderid\nDelete song: delete\nAdd song: add\nUpdate thumbal images: upthum\nUpdate durations: updatedurations\nUpdate ThumbalImg: thumbup\nQuit: q")


if __name__ == "__main__":
    main()
