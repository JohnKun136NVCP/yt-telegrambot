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
"""
TOKEN = "YOUR_BOT_TOKEN"

# Connect to SQLite database
conn = sqlite3.connect("user_data.db")
cursor = conn.cursor()

# Create table if it doesn't exist
cursor.execute("""""")
conn.commit()

def start(update: Update, context: CallbackContext):
    telegram_id = update.message.chat_id

    # Insert user ID if not already present
    cursor.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (telegram_id,))
    conn.commit()
    
    update.message.reply_text("You have been registered!")

def check_and_send(update: Update, context: CallbackContext):
    file_path = "message.txt"

    # Check if the file exists and is not empty
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, "r") as file:
            message = file.read().strip()

        if message:
            update.message.reply_text(message)
    else:
        update.message.reply_text("No message to send.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("check", check_and_send))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
"""
