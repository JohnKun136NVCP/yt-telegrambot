#Testing db and ffmeg (ignore)
import sqlite3
def showDatabase():
        connect = sqlite3.connect("users.db")
        cursor = connect.cursor()
        db_create_query = '''CREATE TABLE IF NOT EXISTS users (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                telegram_id INTEGER UNIQUE,
                                username TEXT);'''
        cursor.execute(db_create_query)
        cursor.execute('SELECT * FROM users')
        result = cursor.fetchall()
        for row in result:
            print(row)
def convertSong():
    path="Songs/WALK AROUND STEREO (sorae mix) (feat. 初音ミク).m4a"
#showDatabase()
convertSong()