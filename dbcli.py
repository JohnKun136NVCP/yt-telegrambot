import sqlite3
import sys
from datetime import datetime
class usersdb:
    def __init__(self,db_path="users.db"):
        self.connect = sqlite3.connect(db_path)
        self.cursor = self.connect.cursor()

        # Create main table
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            songs_by_day INTEGER DEFAULT 0,
            premium BOOLEAN DEFAULT 0,
            type_user TEXT DEFAULT 'unsubscribed',
            last_request_time TEXT
        );''')

        # Last reset log table
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS reset_log (
            id INTEGER PRIMARY KEY,
            last_reset TEXT
        );''')
    def print_all_users(self):
        """print all users in the database for debugging purposes"""
        self.__reorderIDs()
        self.cursor.execute('SELECT * FROM users')
        users = self.cursor.fetchall()
        for user in users:
            print(user)
    def updateDb(self):
        """Update the database schema to add new columns if they don't exist."""
        columns_to_add = [
            ("telegram_id", "INTEGER UNIQUE"),
            ("songs_by_day", "INTEGER DEFAULT 0"),
            ("premium", "BOOLEAN DEFAULT 0"),
            ("type_user", "TEXT DEFAULT 'unsubscribed'"),
            ("last_request_time", "TEXT")
        ]
        for column, definition in columns_to_add:
            try:
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
                print(f"Column '{column}' added.")
            except sqlite3.OperationalError:
                print(f"Column '{column}' already exists, skipped.")
        self.__reorderIDs()
        self.connect.commit()
    def addUserManual(self, id_user, username, songs_by_day=0, premium=False, type_user='unsubscribed'):
        """Manually add a user to the database."""
        self.cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (id_user,))
        result = self.cursor.fetchone()
        if not result:
            self.cursor.execute('''
                INSERT INTO users (telegram_id, username, songs_by_day, premium, type_user)
                VALUES (?, ?, ?, ?, ?)
            ''', (id_user, username, songs_by_day, premium, type_user))
            self.connect.commit()
        self.connect.commit()
        self.__reorderIDs()
    def changeUserType(self,id_user,premium,type_user):
        """Change user type and premium status."""
        self.cursor.execute('UPDATE users SET premium = ?, type_user = ? WHERE telegram_id = ?', (premium, type_user, id_user))
        self.connect.commit()
        self.__reorderIDs()
    def __reorderIDs(self):
        """Reorder user IDs to be sequential."""
        self.cursor.execute('SELECT telegram_id FROM users ORDER BY id')
        users = self.cursor.fetchall()
        for new_id, (telegram_id,) in enumerate(users, start=1):
            self.cursor.execute('UPDATE users SET id = ? WHERE telegram_id = ?', (new_id, telegram_id))
        self.connect.commit()
    def deleteUser(self, id_user):
        """Delete a user from the database."""
        self.cursor.execute('DELETE FROM users WHERE telegram_id = ?', (id_user,))
        self.connect.commit()
        self.__reorderIDs()
    def forceResetDailyCounts(self,id_user):
        """Force reset the daily song request count for a user."""
        self.cursor.execute('UPDATE users SET songs_by_day = 0 WHERE telegram_id = ?', (id_user,))
        self.connect.commit()
        self.__reorderIDs()
        return True, f"User {id_user} daily count reset."
    def addRegisterTimeRequest(self,id_user):
        """Register the time of the last request for a user."""
        from datetime import datetime
        now = datetime.now().isoformat()
        self.cursor.execute('UPDATE users SET last_request_time = ? WHERE telegram_id = ?', (now, id_user))
        self.connect.commit()
    def registerAllRequestTimes(self):
        """Register the current time as the last request time for all users."""
        now = datetime.now().isoformat()
        self.cursor.execute('UPDATE users SET last_request_time = ?', (now,))
        self.connect.commit()
                    
    def deleteDb(self):
        """Delete the entire database (all users)."""
        self.cursor.execute('DELETE FROM users')
        self.connect.commit()
  
    def close(self):
        self.cursor.close()
        self.connect.close()
class songsdb:
    def __init__(self,db_path="idSongs.db"):
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
    def showidSongs(self):
        """Print all songs in the database for debugging purposes."""
        self.cursor.execute('SELECT * FROM songs')
        songs = self.cursor.fetchall()
        for song in songs:
            print(song)
    def deleteDb(self):
        """Delete the entire songs database."""
        self.cursor.execute('DELETE FROM songs')
        self.connect.commit()
    def close(self):
        self.cursor.close()
        self.connect.close()


def main():
    db_users = usersdb()
    db_songs = songsdb()
    try:
        if sys.argv[1] == '--print-users':
            db_users.print_all_users()
        elif sys.argv[1] == '--update-db':
            db_users.updateDb()
        elif sys.argv[1] == '--change-user':
            id_user = int(sys.argv[2])
            premium = bool(int(sys.argv[3]))
            type_user = sys.argv[4]
            db_users.changeUserType(id_user, premium, type_user)
        elif sys.argv[1] == '--force-song-reset':
            id_user = int(sys.argv[2])
            success, message = db_users.forceResetDailyCounts(id_user)
            print(success,message)
        elif sys.argv[1] == '--force-time-request':
            id_user = int(sys.argv[2])
            db_users.addRegisterTimeRequest(id_user)
        elif sys.argv[1] == '--force-time-request-all':
            db_users.registerAllRequestTimes()
        elif sys.argv[1] == '--print-songs':
            db_songs.showidSongs()
        elif sys.argv[1] == '--delete-users-db':
            db_users.deleteDb()
        elif sys.argv[1] == '--delete-songs-db':
            db_songs.deleteDb()
        elif sys.argv[1] == '--help':
            print("Usage:")
            print("  --print-users                 Print all users in the database.")
            print("  --update-db                   Update the database schema.")
            print("  --change-user <id> <premium> <type_user>  Change user type and premium status.")
            print("  --force-song-reset <id>       Force reset daily song request count for a user.")
            print("  --force-time-request <id>     Register current time as last request time for a user.")
            print("  --force-time-request-all      Register current time as last request time for all users.")
            print("  --print-songs                 Print all songs in the songs database.")
            print("  --delete-users-db             Delete all users from the database.")
            print("  --delete-songs-db             Delete all songs from the songs database.")
        else:
            print("Unknown command. Use --help for usage information.")
    except IndexError:
        print("No command provided. Use --help for usage information.")
    finally:
        db_users.close()
        db_songs.close()
if __name__ == "__main__":
    main()