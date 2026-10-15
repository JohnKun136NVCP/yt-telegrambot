"""SQLite-backed storage for users, cached songs and Telegram Stars payments.

Two database files are used:
    database/users.db   -> users, reset_log_user, global_free_downloads, payments
    database/idSongs.db -> songs (cached downloads, keyed by YouTube video id)

Everything here is synchronous (stdlib ``sqlite3``). Callers on the asyncio
event loop MUST wrap calls in ``asyncio.to_thread`` -- see ``src/bot.py``.

NOTE ON A PREVIOUS BUG: this module used to contain the ``usrdatabase`` class
body twice (two ``__init__``, two ``add_user``, two ``can_request_song``...).
Python silently kept only the *last* definition of each method, which hid two
serious issues: the ``users`` table was only ever created inside
``reset_daily_song_counts`` (so a fresh install crashed with
"no such table: users" the moment anyone ran ``/start`` before downloading a
song), and ``self.GLOBAL_FREE_DAILY_LIMIT`` / ``self.FREE_USER_DAILY_LIMIT``
were read in ``can_request_song`` but never assigned anywhere, so every quota
check raised ``AttributeError``. Both are fixed below: the table is created in
``__init__`` and the limits are real class attributes.
"""

import logging
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# type_user values that bypass the free daily quota.
UNLIMITED_TYPES = {"admin", "subscribed", "premium"}

# type_user values whose access expires (checked against premium_until).
# "admin" is intentionally excluded: admin status never expires on its own.
EXPIRING_TYPES = {"subscribed", "premium"}


class usrdatabase:
    """User accounts, daily download quotas and premium subscriptions."""

    FREE_USER_DAILY_LIMIT = 1
    GLOBAL_FREE_DAILY_LIMIT = 2

    def __init__(self, db_path: str = "database/users.db"):
        self.connect = sqlite3.connect(db_path, timeout=30)

        # WAL lets the long-running bot process and the `dbcli.py` admin tool
        # touch the database at the same time without "database is locked".
        self.connect.execute("PRAGMA journal_mode=WAL")
        self.connect.execute("PRAGMA synchronous=NORMAL")

        self.cursor = self.connect.cursor()
        self._create_schema()

    # =========================================================================
    # Schema
    # =========================================================================

    def _create_schema(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                songs_by_day INTEGER NOT NULL DEFAULT 0,
                premium BOOLEAN NOT NULL DEFAULT 0,
                type_user TEXT NOT NULL DEFAULT 'unsubscribed',
                last_request_time TEXT,
                premium_until TEXT
            );
            """
        )

        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_telegram_id "
            "ON users(telegram_id);"
        )

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
            CREATE TABLE IF NOT EXISTS global_free_downloads (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                downloads INTEGER NOT NULL DEFAULT 0,
                period_start TEXT
            );
            """
        )

        # Telegram Stars payments. `charge_id` is the Bot API
        # `telegram_payment_charge_id`: it is unique per payment, so this
        # table doubles as the idempotency guard against processing the same
        # successful_payment update twice (Telegram's delivery is
        # at-least-once).
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                charge_id TEXT UNIQUE NOT NULL,
                plan_code TEXT NOT NULL,
                stars INTEGER NOT NULL,
                days INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                refunded BOOLEAN NOT NULL DEFAULT 0
            );
            """
        )

        self.connect.commit()

        # Migration safety net for databases created by an older version of
        # the bot, which did not have this column.
        self._ensure_column("users", "premium_until", "TEXT")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        existing = {
            row[1]
            for row in self.cursor.execute(f"PRAGMA table_info({table})")
        }

        if column not in existing:
            self.cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
            self.connect.commit()

    # =========================================================================
    # Users
    # =========================================================================

    def add_user(
        self,
        id_user,
        username,
        songs_by_day: int = 0,
        premium: bool = False,
        type_user: str = "unsubscribed",
    ) -> bool:
        """
        Add a user only if they do not already exist.

        Existing users are never modified here: this prevents accidentally
        wiping premium/admin status or the song counter every time someone
        runs /start or sends a link.

        Returns True if a new row was inserted.
        """
        self.cursor.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?",
            (id_user,),
        )

        if self.cursor.fetchone():
            return False

        self.cursor.execute(
            """
            INSERT INTO users (
                telegram_id, username, songs_by_day, premium, type_user
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (id_user, username, songs_by_day, int(bool(premium)), type_user),
        )

        self.connect.commit()
        return True

    def get_user(self, id_user) -> dict | None:
        """Return a dict with this user's full record, or ``None``."""
        self.cursor.execute(
            """
            SELECT telegram_id, username, songs_by_day, premium, type_user,
                   last_request_time, premium_until
            FROM users
            WHERE telegram_id = ?
            """,
            (id_user,),
        )

        row = self.cursor.fetchone()

        if not row:
            return None

        (
            telegram_id, username, songs_by_day, premium, type_user,
            last_request_time, premium_until,
        ) = row

        return {
            "telegram_id": telegram_id,
            "username": username,
            "songs_by_day": int(songs_by_day or 0),
            "premium": bool(premium),
            "type_user": str(type_user or "unsubscribed"),
            "last_request_time": last_request_time,
            "premium_until": premium_until,
            "unlimited": self._is_unlimited(premium, type_user, premium_until),
        }

    def registerTimeRequest(self, id_user) -> None:
        """Register the time of the user's last request."""
        now = datetime.now().isoformat()

        self.cursor.execute(
            "UPDATE users SET last_request_time = ? WHERE telegram_id = ?",
            (now, id_user),
        )

        self.connect.commit()

    # =========================================================================
    # Tier / premium status
    # =========================================================================

    def _is_unlimited(self, premium, type_user, premium_until) -> bool:
        """Whether a user currently bypasses the free daily quota."""
        type_user = str(type_user or "").strip().lower()

        if type_user == "admin":
            return True

        if not (bool(premium) or type_user in UNLIMITED_TYPES):
            return False

        # Subscribed/premium access can expire; NULL premium_until means
        # "no expiry" (e.g. granted manually with no time limit).
        if type_user in EXPIRING_TYPES and premium_until:
            try:
                if datetime.fromisoformat(premium_until) <= datetime.now():
                    return False
            except ValueError:
                logger.warning("Invalid premium_until for a user: %r", premium_until)

        return True

    def is_unlimited(self, id_user) -> bool:
        """Public, single-user version of ``_is_unlimited``."""
        user = self.get_user(id_user)
        return bool(user and user["unlimited"])

    def set_premium(
        self,
        id_user,
        type_user: str = "premium",
        days: int | None = None,
    ) -> bool:
        """
        Grant or extend premium access.

        ``days=None`` means no expiry (used for admin grants). Otherwise the
        expiry is ``days`` from now, or extended from the current expiry if
        the user already has active premium (so stacking two purchases adds
        up instead of the second one overwriting the first).
        """
        user = self.get_user(id_user)

        if user is None:
            return False

        base = datetime.now()

        if days is not None and user["unlimited"] and user["premium_until"]:
            try:
                current_expiry = datetime.fromisoformat(user["premium_until"])
                if current_expiry > base:
                    base = current_expiry
            except ValueError:
                pass

        premium_until = (base + timedelta(days=days)).isoformat() if days else None

        self.cursor.execute(
            """
            UPDATE users
            SET premium = 1, type_user = ?, premium_until = ?
            WHERE telegram_id = ?
            """,
            (type_user, premium_until, id_user),
        )

        self.connect.commit()
        return True

    def revoke_premium(self, id_user) -> bool:
        """Downgrade a user back to the free tier."""
        self.cursor.execute(
            """
            UPDATE users
            SET premium = 0, type_user = 'unsubscribed', premium_until = NULL
            WHERE telegram_id = ?
            """,
            (id_user,),
        )

        self.connect.commit()
        return self.cursor.rowcount > 0

    def ensure_admin(self, id_user) -> None:
        """Make sure a bot-operator (from ADMIN_IDS) has admin status in the DB.

        Safe to call on every /start: it is a no-op once the user is already
        an admin.
        """
        self.cursor.execute(
            "SELECT type_user FROM users WHERE telegram_id = ?",
            (id_user,),
        )

        row = self.cursor.fetchone()

        if row is not None and str(row[0]).strip().lower() == "admin":
            return

        self.cursor.execute(
            """
            UPDATE users
            SET premium = 1, type_user = 'admin', premium_until = NULL
            WHERE telegram_id = ?
            """,
            (id_user,),
        )

        self.connect.commit()

    def expire_old_premium(self) -> int:
        """
        Downgrade every user whose premium_until is in the past.

        Returns the number of users downgraded. Called once a day; individual
        quota checks also self-correct via ``_is_unlimited``, this just keeps
        the stored fields (and anything that reads them directly, like the
        daily-quote broadcast) in sync.
        """
        now = datetime.now().isoformat()

        self.cursor.execute(
            """
            UPDATE users
            SET premium = 0, type_user = 'unsubscribed', premium_until = NULL
            WHERE type_user IN ('premium', 'subscribed')
              AND premium_until IS NOT NULL
              AND premium_until <= ?
            """,
            (now,),
        )

        self.connect.commit()
        return self.cursor.rowcount

    # =========================================================================
    # Global free-tier limit (bot-wide, resets every 24h)
    # =========================================================================

    def _reset_global_counter_if_needed(self) -> None:
        now = datetime.now()

        self.cursor.execute(
            "SELECT downloads, period_start FROM global_free_downloads WHERE id = 1"
        )
        result = self.cursor.fetchone()

        if not result:
            self.cursor.execute(
                """
                INSERT INTO global_free_downloads (id, downloads, period_start)
                VALUES (1, 0, ?)
                """,
                (now.isoformat(),),
            )
            self.connect.commit()
            return

        _, period_start = result
        expired = True

        if period_start:
            try:
                expired = now - datetime.fromisoformat(period_start) >= timedelta(hours=24)
            except ValueError:
                logger.warning("Invalid global period_start: %s", period_start)

        if expired:
            self.cursor.execute(
                """
                UPDATE global_free_downloads
                SET downloads = 0, period_start = ?
                WHERE id = 1
                """,
                (now.isoformat(),),
            )
            self.connect.commit()

    def get_global_free_downloads(self) -> int:
        """Free downloads used during the current 24-hour period, bot-wide."""
        self._reset_global_counter_if_needed()

        self.cursor.execute("SELECT downloads FROM global_free_downloads WHERE id = 1")
        result = self.cursor.fetchone()

        return int(result[0]) if result else 0

    def can_global_free_download(self) -> tuple[bool, str]:
        remaining = self.GLOBAL_FREE_DAILY_LIMIT - self.get_global_free_downloads()

        if remaining <= 0:
            return (
                False,
                "The bot has reached its daily free download limit. "
                "Please try again later or subscribe to premium.",
            )

        return True, f"{remaining} free download(s) remaining."

    def register_global_free_download(self) -> None:
        """Register one successful free download, bot-wide.

        Premium/admin/subscribed users must never call this.
        """
        self._reset_global_counter_if_needed()

        self.cursor.execute(
            """
            UPDATE global_free_downloads
            SET downloads = downloads + 1
            WHERE id = 1
            """
        )

        self.connect.commit()
        logger.info("Global free download registered.")

    # =========================================================================
    # Per-user daily quota
    # =========================================================================

    def can_request_song(self, id_user) -> tuple[bool, str]:
        """
        Check whether a user can request a song.

        Unlimited (admin / active premium / active subscribed): always allowed.
        Free users: 1 song every 24h per user, AND at most
        ``GLOBAL_FREE_DAILY_LIMIT`` free downloads bot-wide every 24h.
        """
        self.cursor.execute(
            """
            SELECT COALESCE(songs_by_day, 0), COALESCE(premium, 0),
                   COALESCE(type_user, ''), premium_until
            FROM users
            WHERE telegram_id = ?
            """,
            (id_user,),
        )

        result = self.cursor.fetchone()

        if not result:
            return False, "User not found in database."

        songs_by_day, premium, type_user, premium_until = result
        songs_by_day = int(songs_by_day or 0)

        if self._is_unlimited(premium, type_user, premium_until):
            return True, "Unlimited requests allowed."

        if songs_by_day >= self.FREE_USER_DAILY_LIMIT:
            return (
                False,
                "Daily song limit reached. "
                "Please wait 24 hours or upgrade to premium with /premium.",
            )

        return self.can_global_free_download()

    def request_song(self, id_user) -> tuple[bool, str]:
        """
        Register a successful song request.

        Call this ONLY after the song has actually been sent to the user.
        """
        self.cursor.execute(
            "SELECT COALESCE(premium, 0), COALESCE(type_user, ''), premium_until "
            "FROM users WHERE telegram_id = ?",
            (id_user,),
        )

        result = self.cursor.fetchone()

        if not result:
            return False, "User not found in database."

        premium, type_user, premium_until = result
        unlimited = self._is_unlimited(premium, type_user, premium_until)

        self.cursor.execute(
            """
            UPDATE users
            SET songs_by_day = COALESCE(songs_by_day, 0) + 1,
                last_request_time = ?
            WHERE telegram_id = ?
            """,
            (datetime.now().isoformat(), id_user),
        )

        if not unlimited:
            self.register_global_free_download()

        self.connect.commit()
        logger.info("Request registered | user=%s | unlimited=%s", id_user, unlimited)

        return True, "Song request successful."

    def reset_daily_song_counts(self, id_user, username) -> tuple[bool, str]:
        """Reset a user's individual counter once 24h have passed since the
        last reset. Does NOT touch the global free counter, which has its own
        independent 24h period."""
        now = datetime.now()

        self.cursor.execute(
            "SELECT last_reset FROM reset_log_user WHERE telegram_id = ?",
            (id_user,),
        )
        result = self.cursor.fetchone()

        if not result:
            self.cursor.execute(
                "INSERT INTO reset_log_user (telegram_id, last_reset) VALUES (?, ?)",
                (id_user, now.isoformat()),
            )
            self.connect.commit()
            return False, f"Reset log initialized for user {username}."

        try:
            last_reset = datetime.fromisoformat(result[0])
        except ValueError:
            last_reset = now

        if now - last_reset < timedelta(hours=24):
            return (
                False,
                f"User {username} last reset was at {last_reset}. "
                "Less than 24 hours ago.",
            )

        self.cursor.execute(
            "UPDATE users SET songs_by_day = 0 WHERE telegram_id = ?",
            (id_user,),
        )
        self.cursor.execute(
            "UPDATE reset_log_user SET last_reset = ? WHERE telegram_id = ?",
            (now.isoformat(), id_user),
        )
        self.connect.commit()

        return True, f"User {username} daily count reset."

    def auto_reset_old_users(self) -> None:
        """Reset songs_by_day for every user whose last request was >24h ago."""
        now = datetime.now()

        self.cursor.execute(
            "SELECT telegram_id, last_request_time FROM users"
        )
        users = self.cursor.fetchall()

        for user_id, last_time in users:
            if not last_time:
                continue

            try:
                last_request = datetime.fromisoformat(last_time)
            except ValueError:
                logger.warning("Invalid last_request_time for user %s", user_id)
                continue

            if now - last_request >= timedelta(hours=24):
                self.cursor.execute(
                    "UPDATE users SET songs_by_day = 0 WHERE telegram_id = ?",
                    (user_id,),
                )

        self.connect.commit()

    # =========================================================================
    # Payments (Telegram Stars)
    # =========================================================================

    def record_payment(
        self,
        telegram_id,
        charge_id: str,
        plan_code: str,
        stars: int,
        days: int,
    ) -> bool:
        """
        Record a successful Stars payment.

        Returns True if this is a NEW payment (premium should be granted),
        False if ``charge_id`` was already recorded (duplicate Telegram
        update -- do NOT grant premium again).
        """
        try:
            self.cursor.execute(
                """
                INSERT INTO payments (
                    telegram_id, charge_id, plan_code, stars, days, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id, charge_id, plan_code, stars, days,
                    datetime.now().isoformat(),
                ),
            )
            self.connect.commit()
            return True

        except sqlite3.IntegrityError:
            logger.info("Duplicate payment charge_id ignored: %s", charge_id)
            return False

    def get_payment(self, charge_id: str) -> dict | None:
        self.cursor.execute(
            """
            SELECT telegram_id, charge_id, plan_code, stars, days,
                   created_at, refunded
            FROM payments
            WHERE charge_id = ?
            """,
            (charge_id,),
        )
        row = self.cursor.fetchone()

        if not row:
            return None

        keys = (
            "telegram_id", "charge_id", "plan_code", "stars", "days",
            "created_at", "refunded",
        )
        return dict(zip(keys, row))

    def last_payment(self, telegram_id) -> dict | None:
        """Most recent, not-yet-refunded payment for a user (for /refund)."""
        self.cursor.execute(
            """
            SELECT telegram_id, charge_id, plan_code, stars, days,
                   created_at, refunded
            FROM payments
            WHERE telegram_id = ? AND refunded = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (telegram_id,),
        )
        row = self.cursor.fetchone()

        if not row:
            return None

        keys = (
            "telegram_id", "charge_id", "plan_code", "stars", "days",
            "created_at", "refunded",
        )
        return dict(zip(keys, row))

    def mark_refunded(self, charge_id: str) -> None:
        self.cursor.execute(
            "UPDATE payments SET refunded = 1 WHERE charge_id = ?",
            (charge_id,),
        )
        self.connect.commit()

    # =========================================================================
    # Stats (for the admin /stats command)
    # =========================================================================

    def stats(self) -> dict:
        self.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.cursor.fetchone()[0]

        self.cursor.execute(
            "SELECT COUNT(*) FROM users WHERE type_user = 'admin'"
        )
        admins = self.cursor.fetchone()[0]

        self.cursor.execute(
            "SELECT COUNT(*) FROM users "
            "WHERE premium = 1 OR type_user IN ('premium', 'subscribed')"
        )
        premium_flagged = self.cursor.fetchone()[0]

        self.cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(stars), 0) FROM payments WHERE refunded = 0"
        )
        payment_count, stars_total = self.cursor.fetchone()

        return {
            "total_users": total_users,
            "admins": admins,
            "premium_flagged": premium_flagged,
            "free_downloads_today": self.get_global_free_downloads(),
            "payment_count": payment_count,
            "stars_total": int(stars_total or 0),
        }

    # =========================================================================
    # Close
    # =========================================================================

    def close(self) -> None:
        try:
            self.cursor.close()
        finally:
            self.connect.close()


class ytdatabase:
    """Cache of already-downloaded songs, keyed by YouTube video id."""

    def __init__(self, db_path: str = "database/idSongs.db"):
        self.connect = sqlite3.connect(db_path, timeout=30)
        self.connect.execute("PRAGMA journal_mode=WAL")
        self.connect.execute("PRAGMA synchronous=NORMAL")

        self.cursor = self.connect.cursor()

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                channel TEXT,
                uri TEXT,
                duration INTEGER,
                thumbnail_url TEXT
            );
            """
        )

        # A plain index already existed implicitly through linear scans; a
        # UNIQUE index both speeds up lookups and makes a concurrent double
        # insert of the same video fail safely instead of duplicating rows.
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_songs_uri ON songs(uri);"
        )

        self.connect.commit()

    def isOntheDatabase(self, uri) -> bool:
        self.cursor.execute("SELECT 1 FROM songs WHERE uri = ?", (uri,))
        return self.cursor.fetchone() is not None

    def insertData(self, title, artist, id_url, duration, thumbalImg) -> bool:
        """Insert a song if it is not already cached.

        Returns True if the song already existed, False if it was inserted
        (kept for backward compatibility with existing call sites).
        """
        try:
            self.cursor.execute(
                """
                INSERT INTO songs (name, channel, uri, duration, thumbnail_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title, artist, id_url, duration, thumbalImg),
            )
            self.connect.commit()
            return False

        except sqlite3.IntegrityError:
            # Another request cached this video_id first -- not an error.
            return True

    def verifyURL(self, id_url):
        self.cursor.execute("SELECT * FROM songs WHERE uri = ?", (id_url,))
        result = self.cursor.fetchone()
        return (True, result) if result else (False, False)

    def updateSong(self, song_id, duration, thumbnail_url) -> None:
        self.cursor.execute(
            "UPDATE songs SET duration = ?, thumbnail_url = ? WHERE id = ?",
            (duration, thumbnail_url, song_id),
        )
        self.connect.commit()

    def close(self) -> None:
        try:
            self.cursor.close()
        finally:
            self.connect.close()
