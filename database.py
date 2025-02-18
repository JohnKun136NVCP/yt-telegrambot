import sqlite3
import os
import re
import sys
from mutagen.mp4 import MP4  # or use the appropriate file type

class dataBase:
    def __init__(self):
        self.connect = sqlite3.connect("idSongs.db")
        self.cursor = self.connect.cursor()
        # Update schema to include duration and thumbnail_url
        self.db_create_query = '''CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY,
            name TEXT,
            channel TEXT,
            uri TEXT,
            duration INTEGER,
            thumbnail_url TEXT
        );'''
        self.cursor.execute(self.db_create_query)
        # Update existing table if it doesn't have the new columns
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
            file_path = os.path.join(current_path, "Songs/", self.cleanString(song_title) + ".m4a")

            if os.path.exists(file_path):
                os.remove(file_path)
        else:
            print("No song found with that id")

    def addSong(self, name, channel, uri, thumbnail_url):
        audio = MP4(uri)  # or use the appropriate function for your file type
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
                    # Extract song title to find corresponding database entry
                    song_title = os.path.splitext(file)[0]
                    song_title = self.cleanString(song_title)
                    # Update the database with the new duration
                    self.cursor.execute("UPDATE songs SET duration = ? WHERE name = ?", (duration, song_title))
        self.connect.commit()

def main():
    dbs = dataBase()
    print("Show database: showdb\nDelete song: delete\nAdd song: add\nUpdate durations: updatedurations\nQuit: q")
    for line in sys.stdin:
        if 'q' == line.rstrip():
            break
        elif 'showdb' == line.rstrip():
            dbs.showDatabase()
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
        elif 'updatedurations' == line.rstrip():
            dbs.updateDurations()
            print("Durations updated")
        
        print("Show database: showdb\nDelete song: delete\nAdd song: add\nUpdate durations: updatedurations\nQuit: q")

if __name__ == "__main__":
    main()
