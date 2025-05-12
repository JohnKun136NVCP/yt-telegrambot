"""
This module provides two classes, `usrdatabase` and `ytdatabase`, for managing SQLite databases.
Classes:
    - usrdatabase: Handles user-related database operations.
    - ytdatabase: Handles YouTube song-related database operations.
Classes and Methods:
    1. usrdatabase:
        - __init__(self, id_user, username):
            Initializes the user database connection and creates the `users` table if it does not exist.
        - isOnTableOrInsert(self):
            Checks if a user exists in the `users` table. If not, inserts the user into the table.
    2. ytdatabase:
        - __init__(self):
            Initializes the song database connection and creates the `songs` table if it does not exist.
        - isOntheDatabase(self, uri):
            Checks if a song with the given URI exists in the `songs` table.
        - insertData(self, title, artist, id_url, duration, thumbalImg):
            Inserts a song into the `songs` table if it does not already exist.
        - verifyURL(self, id_url):
            Verifies if a song with the given URI exists in the `songs` table and returns the result.
        - updateSong(self, song_id, duration, thumbnail_url):
            Updates the duration and thumbnail URL of a song in the `songs` table.
        - deletingDatabase(self):
            Deletes all entries in the `songs` table if an entry with ID 40 exists.
Note:
    - The `users.db` database is used for storing user information.
    - The `idSongs.db` database is used for storing song information.

"""

import sqlite3
class usrdatabase:
    def __init__(self,id_user,username):
        self.idUser = id_user
        self.userName = username
        self.connect = sqlite3.connect("users.db")
        self.cursor = self.connect.cursor()
        self.db_create_query = '''CREATE TABLE IF NOT EXISTS users (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                telegram_id INTEGER UNIQUE,
                                username TEXT);'''
    
        self.cursor.execute(self.db_create_query)
    def isOnTableOrInsert(self):
        """
        This method verify if the element exist into the table. If it does not, then it will insert into the table
        """
        self.cursor.execute('SELECT * FROM users WHERE telegram_id = ? AND username  = ?',(self.idUser,self.userName))
        result = self.cursor.fetchone()
        if not result:
            self.cursor.execute('''INSERT  INTO users (telegram_id,username) VALUES (?,?)''',(self.idUser,self.userName))
            self.connect.commit()
    def reorderIdUserTable(self):
        """
        This method reorder the id of the table
        """
        # Delete temporary table
        self.cursor.execute('DROP TABLE IF EXISTS temp_users')
        self.cursor.execute('''
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
       
    def close(self):
        """Closes the database connection."""
        self.cursor.close()
        self.connect.close()


class ytdatabase:
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
    def close(self):
        """Closes the database connection."""
        self.cursor.close()
        self.connect.close()