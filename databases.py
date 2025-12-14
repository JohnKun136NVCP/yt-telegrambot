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
from datetime import datetime, timedelta
"""
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
        #This method verify if the element exist into the table. If it does not, then it will insert into the table

        self.cursor.execute('SELECT * FROM users WHERE telegram_id = ? AND username  = ?',(self.idUser,self.userName))
        result = self.cursor.fetchone()
        if not result:
            self.cursor.execute('''INSERT  INTO users (telegram_id,username) VALUES (?,?)''',(self.idUser,self.userName))
            self.connect.commit()
    def reorderIdUserTable(self):
        
        #This method reorder the id of the table
        # Delete temporary table
        self.cursor.execute('DROP TABLE IF EXISTS temp_users')
        self.cursor.execute('''
                CREATE TABLE temp_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    username TEXT
                );
            ''')
        self.cursor.execute('''
                INSERT INTO temp_users (telegram_id, username)
                SELECT telegram_id, username
                FROM users;
            ''')
        self.cursor.execute('DROP TABLE users')
        self.cursor.execute('ALTER TABLE temp_users RENAME TO users')
       
    def close(self):
        #Closes the database connection.
        self.cursor.close()
        self.connect.close()
"""
class usrdatabase:
    def __init__(self, db_path="users.db"):
        self.connect = sqlite3.connect(db_path)
        self.cursor = self.connect.cursor()

        # Crear tabla principal
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            songs_by_day INTEGER DEFAULT 0,
            premium BOOLEAN DEFAULT 0,
            type_user TEXT DEFAULT 'unsubscribed',
            last_request_time TEXT
        );''')

        # Tabla para el registro del último reset
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS reset_log (
            id INTEGER PRIMARY KEY,
            last_reset TEXT
        );''')

        self.connect.commit()

    def add_user(self, id_user, username, songs_by_day=0, premium=False, type_user='unsubscribed'):
        """Add a user to the database."""
        self.cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (id_user,))
        result = self.cursor.fetchone()
        if not result:
            self.cursor.execute('''
                INSERT INTO users (telegram_id, username, songs_by_day, premium, type_user)
                VALUES (?, ?, ?, ?, ?)
            ''', (id_user, username, songs_by_day, premium, type_user))
            self.connect.commit()
    def registerTimeRequest(self,id_user):
        """Register the time of the last request for a user."""
        now = datetime.now().isoformat()
        self.cursor.execute('UPDATE users SET last_request_time = ? WHERE telegram_id = ?', (now, id_user))
        self.connect.commit()

    def can_request_song(self, id_user):
        """Check if the user can request a song based on their daily limit and subscription status."""
        self.cursor.execute('SELECT songs_by_day, premium, type_user FROM users WHERE telegram_id = ?', (id_user,))
        result = self.cursor.fetchone()

        if not result:
            return False, "User not found in database."

        songs_by_day, premium, type_user = result

        # Premium o admin: ilimitado
        if type_user.lower() in ["admin", "subscribed"] or premium:
            return True, "Unlimited requests allowed."

        # No premium: máximo 3 canciones
        if songs_by_day >= 1:
            return False, "Daily song limit reached. Please wait until the next reset or upgrade to premium."

        return True, "Song request allowed."

    def request_song(self, id_user):
        """Increment the song request count for the user."""
        allowed, message = self.can_request_song(id_user)
        if not allowed:
            return False, message

        self.cursor.execute('UPDATE users SET songs_by_day = songs_by_day + 1 WHERE telegram_id = ?', (id_user,))
        self.registerTimeRequest(id_user)
        self.connect.commit()
        return True, "Song request successful."
    def auto_reset_old_users(self):
        """
        Recorre todos los usuarios y reinicia songs_by_day si
        han pasado 24 horas desde su última actividad.
        """
        now = datetime.now()
        self.cursor.execute('SELECT telegram_id, username, last_request_time FROM users')
        users = self.cursor.fetchall()

        for user_id, username, last_time in users:
            if not last_time:
                continue  # new users without requests yet

            last_request = datetime.fromisoformat(last_time)
            if now - last_request >= timedelta(hours=24):
                self.cursor.execute('UPDATE users SET songs_by_day = 0 WHERE telegram_id = ?', (user_id,))

        self.connect.commit()

    def reset_daily_song_counts(self, id_user,username):
        """Reset the daily song request count for a user if 24 hours have passed since the last reset."""
        now = datetime.now()

        # Create reset log table for individual users if it doesn't exist
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS reset_log_user (
            telegram_id INTEGER PRIMARY KEY,
            last_reset TEXT
        );''')

        # Verify last reset time for the user
        self.cursor.execute('SELECT last_reset FROM reset_log_user WHERE telegram_id = ?', (id_user,))
        result = self.cursor.fetchone()

        if result:
            last_reset = datetime.fromisoformat(result[0])
            if now - last_reset < timedelta(hours=24):
                return False, f"User {username} last reset was at {last_reset}. Less than 24 hours ago."
        else:
            # If no record exists, create one
            self.cursor.execute(
                'INSERT INTO reset_log_user (telegram_id, last_reset) VALUES (?, ?)',
                (id_user, now.isoformat())
            )
            self.connect.commit()
            return False, f"Reset log initialized for user {username}."

        # Reset the song count
        self.cursor.execute('UPDATE users SET songs_by_day = 0 WHERE telegram_id = ?', (id_user,))

        # Update the last reset time
        self.cursor.execute(
            'UPDATE reset_log_user SET last_reset = ? WHERE telegram_id = ?',
            (now.isoformat(), id_user)
        )

        self.connect.commit()
        return True, f"User {username} daily count reset."
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