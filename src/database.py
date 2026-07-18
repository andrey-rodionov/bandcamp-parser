"""Database module for storing and tracking releases."""
import shutil
import sqlite3
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class ReleaseRecord:
    """Database release record."""
    id: int
    release_url: str
    title: str
    artist: str
    tags: Optional[str]
    cover_url: Optional[str]
    description: Optional[str]
    created_at: datetime
    sent_at: Optional[datetime]


@dataclass
class DatabaseStats:
    """Database statistics."""
    total: int
    sent: int
    
    @property
    def pending(self) -> int:
        return self.total - self.sent


class Database:
    """Database manager for tracking releases."""
    
    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            tags TEXT,
            cover_url TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP
        )
    """
    
    _INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_release_url ON releases(release_url)",
        "CREATE INDEX IF NOT EXISTS idx_created_at ON releases(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sent_at ON releases(sent_at)",
    ]
    
    def __init__(self, db_path: str = "bandcamp_releases.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._SCHEMA)
            for index_sql in self._INDEXES:
                cursor.execute(index_sql)
            conn.commit()
        logger.info(f"Database initialized at {self.db_path}")
    
    @contextmanager
    def _connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def exists(self, release_url: str) -> bool:
        """Check if release already exists in database."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM releases WHERE release_url = ? LIMIT 1",
                (release_url,)
            )
            return cursor.fetchone() is not None
    
    def add(
        self,
        release_url: str,
        title: str,
        artist: str,
        tags: Optional[List[str]] = None,
        cover_url: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """Add new release to database. Returns True if added, False if exists."""
        if self.exists(release_url):
            return False
        
        with self._connection() as conn:
            cursor = conn.cursor()
            tags_str = ",".join(tags) if tags else None
            cursor.execute(
                """INSERT INTO releases 
                   (release_url, title, artist, tags, cover_url, description)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (release_url, title, artist, tags_str, cover_url, description)
            )
            conn.commit()
        
        logger.debug(f"Added release: {title} by {artist}")
        return True
    
    def mark_sent(self, release_url: str) -> None:
        """Mark release as sent."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE releases SET sent_at = ? WHERE release_url = ?",
                (datetime.now(), release_url)
            )
            conn.commit()
    
    def cleanup(self, days: int = 90) -> int:
        """Remove records older than specified days. Returns count of deleted."""
        if days <= 0:
            return 0
        
        cutoff_date = datetime.now() - timedelta(days=days)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM releases WHERE created_at < ?",
                (cutoff_date,)
            )
            deleted = cursor.rowcount
            conn.commit()
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old records")
        return deleted
    
    def disk_usage_percent(self) -> float:
        """Percent of disk space used on the filesystem holding the database."""
        usage = shutil.disk_usage(self.db_path.parent)
        return (usage.used / usage.total) * 100 if usage.total else 0.0

    def cleanup_by_disk_pressure(
        self,
        threshold_percent: float = 85.0,
        target_percent: float = 75.0,
        batch_fraction: float = 0.1,
        max_iterations: int = 8
    ) -> int:
        """Emergency cleanup for when disk space is running low, independent
        of the age-based cleanup() retention window. If the disk holding the
        database is at or above threshold_percent full, repeatedly deletes
        the oldest slice of records and VACUUMs (SQLite doesn't reclaim
        space from DELETE alone) until usage drops back to target_percent,
        there's nothing left to delete, or max_iterations is hit. Returns
        the total number of records deleted."""
        if threshold_percent <= 0:
            return 0

        if self.disk_usage_percent() < threshold_percent:
            return 0

        logger.warning(
            f"Disk usage at {self.disk_usage_percent():.1f}% "
            f"(>= {threshold_percent}% threshold) - freeing space by "
            f"deleting the oldest database records"
        )

        total_deleted = 0
        for _ in range(max_iterations):
            with self._connection() as conn:
                cursor = conn.cursor()
                total_rows = cursor.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
                if total_rows == 0:
                    break
                batch_size = max(1, int(total_rows * batch_fraction))
                cursor.execute(
                    """DELETE FROM releases WHERE id IN (
                           SELECT id FROM releases ORDER BY created_at ASC LIMIT ?
                       )""",
                    (batch_size,)
                )
                deleted = cursor.rowcount
                conn.commit()

            total_deleted += deleted

            with self._connection() as conn:
                conn.execute("VACUUM")

            current_usage = self.disk_usage_percent()
            logger.warning(
                f"Disk pressure cleanup: deleted {deleted} oldest records "
                f"(disk usage now {current_usage:.1f}%)"
            )
            if deleted == 0 or current_usage < target_percent:
                break

        return total_deleted

    def get_stats(self) -> DatabaseStats:
        """Get database statistics."""
        with self._connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as total FROM releases")
            total = cursor.fetchone()["total"]
            
            cursor.execute("SELECT COUNT(*) as sent FROM releases WHERE sent_at IS NOT NULL")
            sent = cursor.fetchone()["sent"]
        
        return DatabaseStats(total=total, sent=sent)
    
    def get_recent(self, limit: int = 100) -> List[ReleaseRecord]:
        """Get recent releases."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM releases 
                   ORDER BY created_at DESC 
                   LIMIT ?""",
                (limit,)
            )
            rows = cursor.fetchall()
        
        return [
            ReleaseRecord(
                id=row["id"],
                release_url=row["release_url"],
                title=row["title"],
                artist=row["artist"],
                tags=row["tags"],
                cover_url=row["cover_url"],
                description=row["description"],
                created_at=row["created_at"],
                sent_at=row["sent_at"]
            )
            for row in rows
        ]
    
    def get_unsent_releases(self) -> List[ReleaseRecord]:
        """Get all releases that haven't been sent yet (sent_at IS NULL)."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM releases 
                   WHERE sent_at IS NULL
                   ORDER BY created_at ASC"""
            )
            rows = cursor.fetchall()
        
        return [
            ReleaseRecord(
                id=row["id"],
                release_url=row["release_url"],
                title=row["title"],
                artist=row["artist"],
                tags=row["tags"],
                cover_url=row["cover_url"],
                description=row["description"],
                created_at=row["created_at"],
                sent_at=row["sent_at"]
            )
            for row in rows
        ]
