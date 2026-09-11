import os
import shutil
import sys
import sqlite3
from datetime import date, datetime
from pathlib import Path

def get_default_db_path():
    if sys.platform == 'win32':
        # Store in user's Windows AppData folder to avoid WSL network share locking
        app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        db_dir = Path(app_data) / "Narrowgate"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "narrowgate.db"

        # One-time migration: this app used to be called FocusTracker, and
        # earlier builds stored their database under that name. Without
        # this, upgrading to a build made after the rename would look like
        # all your tracked history and limits had vanished -- they'd still
        # be sitting on disk under the old folder, just never read again.
        # Best-effort: a fresh database is an acceptable fallback if this
        # fails for any reason (e.g. no old install ever existed).
        if not db_path.exists():
            old_db_path = Path(app_data) / "FocusTracker" / "focus_tracker.db"
            if old_db_path.exists():
                try:
                    shutil.copy2(old_db_path, db_path)
                except OSError:
                    pass

        return str(db_path)
    return "narrowgate.db"

class TimeTrackerDB:
    def __init__(self, db_path=None):
        self.db_path = db_path if db_path else get_default_db_path()
        self._create_tables()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        return conn

    def _create_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_usage (
                    date TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    duration_seconds INTEGER DEFAULT 0,
                    PRIMARY KEY (date, target_name)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS limits (
                    target_name TEXT PRIMARY KEY,
                    limit_seconds INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS focus_history (
                    target_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    last_used TEXT NOT NULL,
                    PRIMARY KEY (target_name, kind)
                )
            """)
            conn.commit()

    def add_time_sample(self, target_name: str, target_type: str, seconds: int = 1):
        today = date.today().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_usage (date, target_name, target_type, duration_seconds)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date, target_name) DO UPDATE SET
                    duration_seconds = duration_seconds + excluded.duration_seconds
            """, (today, target_name, target_type, seconds))
            conn.commit()

    def get_daily_summary(self, target_date: str = None):
        if target_date is None:
            target_date = date.today().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT target_name, target_type, duration_seconds
                FROM daily_usage
                WHERE date = ?
                ORDER BY duration_seconds DESC
            """, (target_date,))
            return cursor.fetchall()

    def get_all_dates(self):
        """All dates that have at least one recorded sample, newest first."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT date FROM daily_usage ORDER BY date DESC
            """)
            return [row[0] for row in cursor.fetchall()]

    # --- Limits -----------------------------------------------------------
    # Limits are keyed by the same lowercase target_name used in daily_usage
    # (a lowercase process name like "discord.exe", or a lowercase domain
    # like "youtube.com") so lookups in LimitEnforcer are always exact
    # case-sensitive matches against what actually gets logged.

    def get_limits(self):
        """Returns {target_name: limit_seconds} for every configured limit."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT target_name, limit_seconds FROM limits")
            return {name: seconds for name, seconds in cursor.fetchall()}

    def set_limit(self, target_name: str, limit_seconds: int):
        target_name = target_name.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO limits (target_name, limit_seconds)
                VALUES (?, ?)
                ON CONFLICT(target_name) DO UPDATE SET
                    limit_seconds = excluded.limit_seconds
            """, (target_name, int(limit_seconds)))
            conn.commit()

    def delete_limit(self, target_name: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM limits WHERE target_name = ?", (target_name.strip().lower(),))
            conn.commit()

    def seed_default_limits(self, defaults: dict):
        """Insert each default limit only if that target has no limit yet,
        so it never clobbers a value the user already edited."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR IGNORE INTO limits (target_name, limit_seconds)
                VALUES (?, ?)
            """, [(name.strip().lower(), int(seconds)) for name, seconds in defaults.items()])
            conn.commit()

    # --- Focus Session history ---------------------------------------------
    # Remembers every app/domain that's ever been added to a Focus Session's
    # allow-list, so the Focus tab can offer them back as checkboxes instead
    # of making you retype them every time. `kind` is "APP" or "DOMAIN".
    # This is independent of FocusSession itself (which stays in-memory only
    # per session) -- only the *names* persist, not whether a session is
    # currently running.

    def add_focus_history(self, target_name: str, kind: str):
        target_name = target_name.strip().lower()
        kind = kind.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO focus_history (target_name, kind, last_used)
                VALUES (?, ?, ?)
                ON CONFLICT(target_name, kind) DO UPDATE SET
                    last_used = excluded.last_used
            """, (target_name, kind, datetime.now().isoformat()))
            conn.commit()

    def get_focus_history(self, kind: str):
        """Target names for this kind, most-recently-used first."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT target_name FROM focus_history
                WHERE kind = ?
                ORDER BY last_used DESC
            """, (kind.strip().upper(),))
            return [row[0] for row in cursor.fetchall()]

    def delete_focus_history(self, target_name: str, kind: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM focus_history WHERE target_name = ? AND kind = ?",
                (target_name.strip().lower(), kind.strip().upper()),
            )
            conn.commit()