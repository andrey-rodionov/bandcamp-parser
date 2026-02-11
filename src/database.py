"""Database module for storing and tracking releases."""
import sqlite3
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
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
    
    # Alias for backwards compatibility
    def release_exists(self, release_url: str) -> bool:
        return self.exists(release_url)
    
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
    
    # Alias for backwards compatibility
    def add_release(
        self,
        release_url: str,
        title: str,
        artist: str,
        tags: Optional[List[str]] = None,
        cover_url: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        return self.add(release_url, title, artist, tags, cover_url, description)
    
    def mark_sent(self, release_url: str) -> None:
        """Mark release as sent."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE releases SET sent_at = ? WHERE release_url = ?",
                (datetime.now(), release_url)
            )
            conn.commit()
    
    # Alias for backwards compatibility
    def mark_as_sent(self, release_url: str) -> None:
        self.mark_sent(release_url)
    
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
    
    # Alias for backwards compatibility
    def cleanup_old_records(self, days: int = 90) -> None:
        self.cleanup(days)
    
    def get_stats(self) -> DatabaseStats:
        """Get database statistics."""
        with self._connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as total FROM releases")
            total = cursor.fetchone()["total"]
            
            cursor.execute("SELECT COUNT(*) as sent FROM releases WHERE sent_at IS NOT NULL")
            sent = cursor.fetchone()["sent"]
        
        return DatabaseStats(total=total, sent=sent)
    
    # Alias for backwards compatibility  
    def get_statistics(self) -> Dict[str, int]:
        stats = self.get_stats()
        return {"total": stats.total, "sent": stats.sent, "pending": stats.pending}
    
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
