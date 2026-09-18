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
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Capture all logs, including debug
logger.setLevel(logging.INFO)  # Set the logger to capture INFO level and above

logger.addHandler(logging.StreamHandler())  # Log to console
logger.addHandler(logging.FileHandler("logs/database_debug.log"))  # Log to file
logger.addHandler(logging.FileHandler("logs/database_info.log"))  # Log to file for INFO level
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
<<<<<<< Updated upstream

    # =========================================================
    # CONFIGURATION
    # =========================================================

    FREE_USER_DAILY_LIMIT = 1

    # Maximum FREE downloads shared by ALL free users.
    GLOBAL_FREE_DAILY_LIMIT = 2

    # =========================================================
    # INIT
    # =========================================================

    def __init__(self, db_path="database/users.db"):

        self.connect = sqlite3.connect(
            db_path
        )

=======
    def __init__(self, db_path="database/users.db"):
        self.connect = sqlite3.connect(db_path)
>>>>>>> Stashed changes
        self.cursor = self.connect.cursor()

        # -----------------------------------------------------
        # Users
        # -----------------------------------------------------

<<<<<<< Updated upstream
=======
        # Tabla para el registro del último reset
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS reset_log (
            id INTEGER PRIMARY KEY,
            last_reset TEXT
        );''')

        self.connect.commit()

    def add_user(self, id_user, username, songs_by_day=0, premium=False, type_user='unsubscribed'):
        """
        Add a user only if they do not already exist.

        IMPORTANT:
        Existing users are never modified here.
        This prevents accidentally removing premium/admin
        permissions when /start or a download is executed.
        """

        self.cursor.execute(
            '''
            SELECT telegram_id
            FROM users
            WHERE telegram_id = ?
            ''',
            (id_user,)
        )

        result = self.cursor.fetchone()

        if result:
            # User already exists.
            # Do NOT modify premium/type_user/songs_by_day.
            return False

        self.cursor.execute(
            '''
            INSERT INTO users (
                telegram_id,
                username,
                songs_by_day,
                premium,
                type_user
            )
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                id_user,
                username,
                songs_by_day,
                int(bool(premium)),
                type_user
            )
        )

        self.connect.commit()

        return True
    def registerTimeRequest(self,id_user):
        """Register the time of the last request for a user."""
        now = datetime.now().isoformat()
        self.cursor.execute('UPDATE users SET last_request_time = ? WHERE telegram_id = ?', (now, id_user))
        self.connect.commit()

    def can_request_song(self, id_user):
        """
        Check whether a user can request a song.

        Admins and premium/subscribed users have unlimited access.
        Normal users are limited to one song per reset period.
        """

        self.cursor.execute(
            '''
            SELECT
                songs_by_day,
                premium,
                type_user
            FROM users
            WHERE telegram_id = ?
            ''',
            (id_user,)
        )

        result = self.cursor.fetchone()

        if not result:
            return False, "User not found in database."

        songs_by_day, premium, type_user = result

        # Normalize values from SQLite.
        premium_value = bool(premium)

        user_type = (
            str(type_user).strip().lower()
            if type_user is not None
            else ""
        )

        # =====================================================
        # PREMIUM / ADMIN
        # =====================================================

        if (
            premium_value
            or user_type in {
                "admin",
                "administrator",
                "subscribed",
                "premium"
            }
        ):
            return True, "Unlimited requests allowed."

        # =====================================================
        # FREE USER
        # =====================================================

        if songs_by_day >= 1:
            return (
                False,
                "Daily song limit reached. "
                "Please wait until the next reset "
                "or upgrade to premium."
            )

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
>>>>>>> Stashed changes
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                songs_by_day INTEGER DEFAULT 0,
                premium BOOLEAN DEFAULT 0,
                type_user TEXT DEFAULT 'unsubscribed',
                last_request_time TEXT
            );
            """
        )

        # -----------------------------------------------------
        # Global free download counter
        # -----------------------------------------------------

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS global_free_downloads (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                downloads INTEGER DEFAULT 0,
                period_start TEXT
            );
            """
        )

        self.connect.commit()

    # =========================================================
    # USERS
    # =========================================================

    def add_user(
        self,
        id_user,
        username,
        songs_by_day=0,
        premium=False,
        type_user="unsubscribed"
    ):
        """
        Add a user if they don't already exist.
        """

        self.cursor.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE telegram_id = ?
            """,
            (id_user,)
        )

        result = self.cursor.fetchone()

        if result:
            return False

        self.cursor.execute(
            """
            INSERT INTO users (
                telegram_id,
                username,
                songs_by_day,
                premium,
                type_user
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                id_user,
                username,
                songs_by_day,
                premium,
                type_user
            )
        )

        self.connect.commit()

        return True

    # =========================================================
    # USER TYPE
    # =========================================================

    def _is_unlimited_user(
        self,
        premium,
        type_user
    ):
        """
        Determine whether a user has unlimited downloads.
        """

        premium = bool(premium)

        type_user = str(
            type_user or ""
        ).strip().lower()

        return (
            premium
            or type_user in {
                "admin",
                "subscribed",
                "premium"
            }
        )

    # =========================================================
    # USER REQUEST TIME
    # =========================================================

    def registerTimeRequest(
        self,
        id_user
    ):
        """
        Register the time of the last request.
        """

        now = datetime.now().isoformat()

        self.cursor.execute(
            """
            UPDATE users
            SET last_request_time = ?
            WHERE telegram_id = ?
            """,
            (
                now,
                id_user
            )
        )

        self.connect.commit()

    # =========================================================
    # GLOBAL FREE LIMIT
    # =========================================================

    def _reset_global_counter_if_needed(self):
        """
        Reset the global free-download counter after 24 hours.
        """

        now = datetime.now()

        self.cursor.execute(
            """
            SELECT downloads, period_start
            FROM global_free_downloads
            WHERE id = 1
            """
        )

        result = self.cursor.fetchone()

        # No global period exists yet.
        if not result:

            self.cursor.execute(
                """
                INSERT INTO global_free_downloads (
                    id,
                    downloads,
                    period_start
                )
                VALUES (1, 0, ?)
                """,
                (
                    now.isoformat(),
                )
            )

            self.connect.commit()

            return

        downloads, period_start = result

        if not period_start:
            self.cursor.execute(
                """
                UPDATE global_free_downloads
                SET downloads = 0,
                    period_start = ?
                WHERE id = 1
                """,
                (
                    now.isoformat(),
                )
            )

            self.connect.commit()

            return

        try:

            start = datetime.fromisoformat(
                period_start
            )

        except ValueError:

            logger.warning(
                "Invalid global period_start: %s",
                period_start
            )

            self.cursor.execute(
                """
                UPDATE global_free_downloads
                SET downloads = 0,
                    period_start = ?
                WHERE id = 1
                """,
                (
                    now.isoformat(),
                )
            )

            self.connect.commit()

            return

        if now - start >= timedelta(hours=24):

            logger.info(
                "Resetting global free download counter."
            )

            self.cursor.execute(
                """
                UPDATE global_free_downloads
                SET downloads = 0,
                    period_start = ?
                WHERE id = 1
                """,
                (
                    now.isoformat(),
                )
            )

            self.connect.commit()

    def get_global_free_downloads(self):
        """
        Return the number of free downloads used
        during the current 24-hour period.
        """

        self._reset_global_counter_if_needed()

        self.cursor.execute(
            """
            SELECT downloads
            FROM global_free_downloads
            WHERE id = 1
            """
        )

        result = self.cursor.fetchone()

        if not result:
            return 0

        return int(
            result[0] or 0
        )

    def can_global_free_download(self):
        """
        Check whether the global free limit is available.
        """

        downloads = (
            self.get_global_free_downloads()
        )

        remaining = (
            self.GLOBAL_FREE_DAILY_LIMIT
            - downloads
        )

        if remaining <= 0:

            return (
                False,
                "The bot has reached its daily free download limit. "
                "Please try again later or subscribe to premium."
            )

        return (
            True,
            f"{remaining} free download(s) remaining."
        )

    def register_global_free_download(self):
        """
        Register one successful free download globally.

        Premium/admin/subscribed users should NEVER call this.
        """

        self._reset_global_counter_if_needed()

        now = datetime.now()

        self.cursor.execute(
            """
            SELECT downloads
            FROM global_free_downloads
            WHERE id = 1
            """
        )

        result = self.cursor.fetchone()

        if not result:

            self.cursor.execute(
                """
                INSERT INTO global_free_downloads (
                    id,
                    downloads,
                    period_start
                )
                VALUES (1, 1, ?)
                """,
                (
                    now.isoformat(),
                )
            )

        else:

            self.cursor.execute(
                """
                UPDATE global_free_downloads
                SET downloads = downloads + 1
                WHERE id = 1
                """
            )

        self.connect.commit()

        logger.info(
            "Global free download registered."
        )

        return True

    # =========================================================
    # CHECK USER REQUEST
    # =========================================================

    def can_request_song(
        self,
        id_user
    ):
        """
        Check whether a user can request a song.

        Unlimited:
            - premium = 1
            - type_user = admin
            - type_user = subscribed
            - type_user = premium

        Free:
            - 1 song every 24 hours per user
            - maximum 2 free downloads globally every 24 hours
        """

        self.cursor.execute(
            """
            SELECT
                COALESCE(songs_by_day, 0),
                COALESCE(premium, 0),
                COALESCE(type_user, ''),
                last_request_time
            FROM users
            WHERE telegram_id = ?
            """,
            (
                id_user,
            )
        )

        result = self.cursor.fetchone()

        if not result:

            return (
                False,
                "User not found in database."
            )

        (
            songs_by_day,
            premium,
            type_user,
            last_request_time
        ) = result

        songs_by_day = int(
            songs_by_day or 0
        )

        type_user = str(
            type_user or ""
        ).strip().lower()

        logger.info(
            "User %s | songs=%s | premium=%s | "
            "type_user=%r | last_request=%r",
            id_user,
            songs_by_day,
            premium,
            type_user,
            last_request_time
        )

        # =====================================================
        # UNLIMITED USER
        # =====================================================

        if self._is_unlimited_user(
            premium,
            type_user
        ):

            logger.info(
                "User %s -> unlimited (%s, premium=%s)",
                id_user,
                type_user,
                premium
            )

            return (
                True,
                "Unlimited requests allowed."
            )

        # =====================================================
        # FREE USER - INDIVIDUAL LIMIT
        # =====================================================

        if songs_by_day >= self.FREE_USER_DAILY_LIMIT:

            return (
                False,
                "Daily song limit reached. "
                "Please wait 24 hours or upgrade to premium."
            )

        # =====================================================
        # FREE USER - GLOBAL LIMIT
        # =====================================================

        global_allowed, global_message = (
            self.can_global_free_download()
        )

        if not global_allowed:

            return (
                False,
                global_message
            )

        # =====================================================
        # ALLOWED
        # =====================================================

        return (
            True,
            "Song request allowed."
        )

    # =========================================================
    # REGISTER REQUEST
    # =========================================================

    def request_song(
        self,
        id_user
    ):
        """
        Register a successful song request.

        IMPORTANT:
        Call this ONLY after the song has actually
        been successfully sent to the user.
        """

        # -----------------------------------------------------
        # Get user
        # -----------------------------------------------------

        self.cursor.execute(
            """
            SELECT
                COALESCE(premium, 0),
                COALESCE(type_user, '')
            FROM users
            WHERE telegram_id = ?
            """,
            (
                id_user,
            )
        )

        result = self.cursor.fetchone()

        if not result:

            return (
                False,
                "User not found in database."
            )

        premium, type_user = result

        type_user = str(
            type_user or ""
        ).strip().lower()

        unlimited = self._is_unlimited_user(
            premium,
            type_user
        )

        # -----------------------------------------------------
        # Increment user's personal counter
        # -----------------------------------------------------

        self.cursor.execute(
            """
            UPDATE users
            SET songs_by_day = COALESCE(songs_by_day, 0) + 1
            WHERE telegram_id = ?
            """,
            (
                id_user,
            )
        )

        # -----------------------------------------------------
        # Register request time
        # -----------------------------------------------------

        now = datetime.now().isoformat()

        self.cursor.execute(
            """
            UPDATE users
            SET last_request_time = ?
            WHERE telegram_id = ?
            """,
            (
                now,
                id_user
            )
        )

        # -----------------------------------------------------
        # Global counter
        #
        # ONLY FREE USERS consume it.
        # -----------------------------------------------------

        if not unlimited:

            self.register_global_free_download()

        self.connect.commit()

        logger.info(
            "Request registered | user=%s | unlimited=%s",
            id_user,
            unlimited
        )

        return (
            True,
            "Song request successful."
        )

    # =========================================================
    # RESET OLD USERS
    # =========================================================

    def auto_reset_old_users(self):
        """
        Reset songs_by_day for users whose last request
        was more than 24 hours ago.
        """

        now = datetime.now()

        self.cursor.execute(
            """
            SELECT
                telegram_id,
                username,
                last_request_time
            FROM users
            """
        )

        users = self.cursor.fetchall()

        for (
            user_id,
            username,
            last_time
        ) in users:

            if not last_time:
                continue

            try:

                last_request = (
                    datetime.fromisoformat(
                        last_time
                    )
                )

            except ValueError:

                logger.warning(
                    "Invalid last_request_time "
                    "for user %s: %s",
                    user_id,
                    last_time
                )

                continue

            if (
                now - last_request
                >= timedelta(hours=24)
            ):

                self.cursor.execute(
                    """
                    UPDATE users
                    SET songs_by_day = 0
                    WHERE telegram_id = ?
                    """,
                    (
                        user_id,
                    )
                )

                logger.info(
                    "Reset songs_by_day for user %s",
                    user_id
                )

        self.connect.commit()

    # =========================================================
    # INDIVIDUAL RESET
    # =========================================================

    def reset_daily_song_counts(
        self,
        id_user,
        username
    ):
        """
        Reset the user's individual limit after 24 hours.

        This DOES NOT reset the global free limit.
        The global limit has its own 24-hour period.
        """

        now = datetime.now()

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reset_log_user (
                telegram_id INTEGER PRIMARY KEY,
                last_reset TEXT
            );
            """
        )

        self.cursor.execute(
            """
            SELECT last_reset
            FROM reset_log_user
            WHERE telegram_id = ?
            """,
            (
                id_user,
            )
        )

        result = self.cursor.fetchone()

        # -----------------------------------------------------
        # First time
        # -----------------------------------------------------

        if not result:

            self.cursor.execute(
                """
                INSERT INTO reset_log_user (
                    telegram_id,
                    last_reset
                )
                VALUES (?, ?)
                """,
                (
                    id_user,
                    now.isoformat()
                )
            )

            self.connect.commit()

            return (
                False,
                f"Reset log initialized for user {username}."
            )

        # -----------------------------------------------------
        # Check 24 hours
        # -----------------------------------------------------

        try:

            last_reset = datetime.fromisoformat(
                result[0]
            )

        except ValueError:

            last_reset = now

        if (
            now - last_reset
            < timedelta(hours=24)
        ):

            return (
                False,
                f"User {username} last reset was at "
                f"{last_reset}. Less than 24 hours ago."
            )

        # -----------------------------------------------------
        # Reset individual count
        # -----------------------------------------------------

        self.cursor.execute(
            """
            UPDATE users
            SET songs_by_day = 0
            WHERE telegram_id = ?
            """,
            (
                id_user,
            )
        )

        self.cursor.execute(
            """
            UPDATE reset_log_user
            SET last_reset = ?
            WHERE telegram_id = ?
            """,
            (
                now.isoformat(),
                id_user
            )
        )

        self.connect.commit()

        return (
            True,
            f"User {username} daily count reset."
        )

    # =========================================================
    # CLOSE
    # =========================================================

    def close(self):

        try:
            self.cursor.close()
        finally:
            self.connect.close()
class ytdatabase:
    def __init__(self):
        self.connect = sqlite3.connect("database/idSongs.db")
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