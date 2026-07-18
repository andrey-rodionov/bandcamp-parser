"""Main application module."""
import asyncio
import logging
import signal
import sys
import time
import threading
import warnings
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Suppress urllib3 OpenSSL warning on macOS
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*', category=UserWarning)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.parser import BandcampParser, Release
from src.database import Database
from src.telegram_bot import TelegramBot
from src.scheduler import TaskScheduler
from src.admin_bot import AdminBot

# Configure logging - rotate daily, keep 4 weeks of history
_file_handler = TimedRotatingFileHandler(
    'bandcamp_bot.log', when='midnight', interval=1, backupCount=28, encoding='utf-8'
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        _file_handler,
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


@dataclass
class ParsingResult:
    """Result of a parsing run."""
    blacklisted: int = 0
    sent: int = 0
    failed: int = 0


class BandcampBot:
    """Main application class."""
    
    def __init__(self):
        """Initialize application components."""
        # Database
        self.db = Database(db_path=config.database.db_path)

        # Signaled on SIGTERM/SIGINT so in-flight parsing stops instead of
        # racing the shutdown cleanup (see _cleanup / handle_signal).
        self._shutdown_event = threading.Event()

        # Set while run_parsing() is executing; used to wait for the
        # currently running job to actually finish before shutting down.
        self._task_done = threading.Event()
        self._task_done.set()

        # Timestamp of the last successfully completed parsing run, exposed
        # via the admin bot's /status command.
        self._last_run_at: Optional[datetime] = None

        # Parser
        self.parser = BandcampParser(
            user_agent=config.parser.user_agent,
            request_delay=config.parser.request_delay,
            shutdown_event=self._shutdown_event,
            genre_fallback=config.genre_fallback
        )

        # Telegram bot
        self.telegram = TelegramBot(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
            max_description_length=config.telegram.max_description_length
        )

        # Admin bot - Telegram commands for editing tags/blacklist/schedule/
        # genre-fallback mappings without SSH access.
        self.admin_bot = AdminBot(self)
        
        # Scheduler
        self.scheduler = TaskScheduler(
            times=config.schedule.times,
            timezone=config.schedule.timezone,
            jitter_seconds=config.schedule.jitter_minutes * 60
        )
        self.scheduler.set_task(self.run_parsing)
        
        # Retry task control
        self._retry_running = False
        self._retry_thread: Optional[threading.Thread] = None
    
    async def _process_release(
        self, 
        release: Release, 
        send_to_telegram: bool = True
    ) -> bool:
        """Process a single release. Returns True if sent/added."""
        # Check if exists
        if self.db.exists(release.url):
            return False

        # Refine the generic genre label (assigned via GENRE_FALLBACK) with
        # the release's actual applied tags, fetched from its own page -
        # confirms a specific subgenre tag (e.g. "hardcore-punk") is
        # genuinely present rather than just inferred from the broader
        # parent-genre feed it was fetched from.
        real_tags = self.parser.fetch_release_tags(release.url)
        if real_tags:
            release.tags = real_tags

        # Add to database first (even if sending fails)
        added = self.db.add(
            release_url=release.url,
            title=release.title,
            artist=release.artist,
            tags=release.tags,
            cover_url=release.cover_url,
            description=release.description
        )
        
        if not added:
            return False
        
        if send_to_telegram:
            # Send to Telegram
            success = await self.telegram.send_release(release)
            if success:
                self.db.mark_sent(release.url)
                return True
            else:
                logger.warning(f"Failed to send: {release.title} (saved to DB for retry)")
                return False
        else:
            # For blacklist, mark as sent immediately
            self.db.mark_sent(release.url)
            return True
    
    async def _process_blacklist(self) -> int:
        """Process blacklist tags. Returns count of blacklisted."""
        blacklist_tags = config.blacklist_tags
        if not blacklist_tags:
            return 0
        
        logger.info("=" * 50)
        logger.info("Processing blacklist tags...")
        
        count = 0
        
        for tag in blacklist_tags:
            if self._shutdown_event.is_set():
                logger.info("Shutdown requested, stopping blacklist processing")
                break

            logger.info(f"Blacklist tag: {tag}")
            releases = self.parser.get_releases_by_tag(tag)
            
            for release in releases:
                if await self._process_release(release, send_to_telegram=False):
                    count += 1
                    logger.debug(f"Blacklisted: {release.title}")
        
        logger.info(f"Blacklisted {count} releases")
        return count
    
    async def _process_main_tags(self) -> ParsingResult:
        """Process main tags. Returns parsing result."""
        result = ParsingResult()
        
        logger.info("=" * 50)
        logger.info("Processing main tags...")
        
        for tag in config.tags:
            if self._shutdown_event.is_set():
                logger.info("Shutdown requested, stopping tag processing")
                break

            logger.info(f"Processing tag: {tag}")
            releases = self.parser.get_releases_by_tag(tag)
            tag_sent = 0
            
            for release in releases:
                # Check if exists
                if self.db.exists(release.url):
                    continue

                # Refine the generic genre label with the release's actual
                # applied tags - see _process_release for why.
                real_tags = self.parser.fetch_release_tags(release.url)
                if real_tags:
                    release.tags = real_tags

                # Add to database first (even if sending fails)
                added = self.db.add(
                    release_url=release.url,
                    title=release.title,
                    artist=release.artist,
                    tags=release.tags,
                    cover_url=release.cover_url
                )
                
                if not added:
                    continue
                
                # Send to Telegram
                success = await self.telegram.send_release(release)
                
                if success:
                    self.db.mark_sent(release.url)
                    result.sent += 1
                    tag_sent += 1
                    logger.info(f"Sent: {release.title} by {release.artist}")
                    await asyncio.sleep(2)  # Rate limiting
                else:
                    result.failed += 1
                    logger.warning(f"Failed to send: {release.title} (saved to DB, sent_at=NULL)")
            
            if tag_sent == 0:
                logger.info(f"No new releases for '{tag}'")
            else:
                logger.info(f"Tag '{tag}': sent {tag_sent}")
        
        return result
    
    async def _retry_failed_releases(self) -> None:
        """Retry sending releases that failed to send (sent_at IS NULL)."""
        unsent_releases = self.db.get_unsent_releases()
        
        if not unsent_releases:
            logger.debug("No unsent releases to retry")
            return
        
        logger.info(f"Retrying {len(unsent_releases)} unsent release(s)...")
        
        retried_count = 0
        success_count = 0
        
        for record in unsent_releases:
            # Convert ReleaseRecord to Release object
            tags_list = []
            if record.tags:
                tags_list = [tag.strip() for tag in record.tags.split(",") if tag.strip()]
            
            release = Release(
                url=record.release_url,
                title=record.title,
                artist=record.artist,
                tags=tags_list,
                cover_url=record.cover_url,
                description=record.description
            )
            
            # Try to send
            success = await self.telegram.send_release(release)
            retried_count += 1
            
            if success:
                self.db.mark_sent(release.url)
                success_count += 1
                logger.info(f"Successfully sent (retry): {release.title} by {release.artist}")
                await asyncio.sleep(2)  # Rate limiting
            else:
                logger.warning(f"Retry failed: {release.title} (will retry again in 20 minutes)")
        
        if success_count > 0:
            logger.info(f"Retry completed: {success_count}/{retried_count} releases sent successfully")
        else:
            logger.info(f"Retry completed: {retried_count} releases still pending")
    
    async def run_parsing(self) -> None:
        """Main parsing task."""
        logger.info("Starting parsing task...")
        self._task_done.clear()

        try:
            # Process blacklist first
            blacklisted = await self._process_blacklist()
            
            # Process main tags
            result = await self._process_main_tags()
            result.blacklisted = blacklisted
            
            # Log summary
            logger.info(f"Sent {result.sent} new releases")
            
            # Send summary to Telegram
            if result.sent > 0:
                await self.telegram.send_message(
                    f"✅ Found and sent {result.sent} new release(s)"
                )
            else:
                logger.info("No new releases found")
            
            # Cleanup old records
            if config.database.cleanup_days > 0:
                self.db.cleanup(config.database.cleanup_days)

            # Emergency cleanup if disk space is running low, independent
            # of the age-based retention window above.
            if config.database.disk_usage_threshold_percent > 0:
                self.db.cleanup_by_disk_pressure(
                    threshold_percent=config.database.disk_usage_threshold_percent,
                    target_percent=config.database.disk_usage_target_percent
                )

            logger.info("Parsing task completed")
            self._last_run_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error in parsing: {e}", exc_info=True)
            try:
                await asyncio.wait_for(
                    self.telegram.send_message(f"❌ Parsing error: {e}"),
                    timeout=30.0
                )
            except Exception:
                pass
        finally:
            self._task_done.set()

    async def _send_startup_message(self) -> None:
        """Send startup notification."""
        await asyncio.sleep(2)
        stats = self.db.get_stats()
        
        blacklist_info = ""
        if config.blacklist_tags:
            blacklist_info = f"\n🚫 Blacklist: {', '.join(config.blacklist_tags)}"
        
        message = (
            f"🤖 Bandcamp Parser Bot started!\n\n"
            f"📊 Database: {stats.total} releases ({stats.sent} sent)\n"
            f"🏷️ Tags: {', '.join(config.tags)}"
            f"{blacklist_info}\n"
            f"⏰ Schedule: {', '.join(config.schedule.times)}"
        )
        await self.telegram.send_message(message)
    
    def _retry_loop(self) -> None:
        """Background loop for retrying failed releases every 20 minutes."""
        RETRY_INTERVAL = 20 * 60  # 20 minutes in seconds
        
        logger.info("Retry task started (runs every 20 minutes)")
        
        # Run immediately on startup, then every 20 minutes
        first_run = True
        
        while self._retry_running:
            try:
                # Run retry task
                asyncio.run(self._retry_failed_releases())
            except Exception as e:
                logger.error(f"Error in retry task: {e}", exc_info=True)
            
            # Wait 20 minutes before next retry (skip wait on first run)
            if self._retry_running:
                if first_run:
                    first_run = False
                    # Small delay after first run to avoid immediate retry
                    time.sleep(5)
                else:
                    # Wait 20 minutes before next retry
                    for _ in range(RETRY_INTERVAL):
                        if not self._retry_running:
                            break
                        time.sleep(1)
        
        logger.info("Retry task stopped")
    
    def _start_retry_task(self) -> None:
        """Start the background retry task."""
        if self._retry_running:
            return
        
        self._retry_running = True
        self._retry_thread = threading.Thread(
            target=self._retry_loop,
            daemon=True,
            name="RetryTask"
        )
        self._retry_thread.start()
        logger.info("Started retry task for failed releases (every 20 minutes)")
    
    def _stop_retry_task(self) -> None:
        """Stop the background retry task."""
        if not self._retry_running:
            return
        
        self._retry_running = False
        if self._retry_thread:
            self._retry_thread.join(timeout=5)
        logger.info("Stopped retry task")
    
    def _cleanup(self) -> None:
        """Cleanup resources."""
        # Stop the admin bot's polling thread first - it has nothing to do
        # with _task_done (it's not a parsing task), but must be told to
        # stop explicitly or it can hang the process past the systemd
        # TimeoutStopSec safety net on every restart.
        self.admin_bot.stop()

        # Stop retry task
        self._stop_retry_task()

        # Suppress urllib3 warnings during shutdown
        logging.getLogger('urllib3').setLevel(logging.ERROR)

        if self.parser.session:
            try:
                self.parser.session.close()
                logger.info("HTTP session closed")
            except Exception:
                pass
    
    def run(self) -> None:
        """Run the application."""
        logger.info("Starting Bandcamp Parser Bot...")
        logger.info(f"Tags: {', '.join(config.tags)}")
        if config.blacklist_tags:
            logger.info(f"Blacklist: {', '.join(config.blacklist_tags)}")
        logger.info(f"Schedule: {', '.join(config.schedule.times)} ({config.schedule.timezone})")
        
        # Start scheduler
        self.scheduler.start()
        
        # Start retry task for failed releases
        self._start_retry_task()

        # Start the admin command bot
        self.admin_bot.start()

        # Send startup message
        try:
            asyncio.run(self._send_startup_message())
        except Exception as e:
            logger.warning(f"Could not send startup message: {e}")
        
        # Signal handlers
        def handle_signal(sig, frame):
            logger.info("Shutting down...")
            # Tell any in-flight parsing task to stop between tags.
            self._shutdown_event.set()
            self.scheduler.stop()

            if not self._task_done.is_set():
                logger.info("Waiting for in-flight parsing task to stop...")
                if not self._task_done.wait(timeout=60):
                    logger.warning(
                        "Parsing task did not stop within 60s, proceeding with cleanup anyway"
                    )

            self._cleanup()
            logger.info("Application stopped")
            sys.exit(0)
        
        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except (AttributeError, ValueError):
            pass  # Windows
        
        # Main loop
        logger.info("Application running. Press Ctrl+C to stop.")

        try:
            last_check = 0
            while True:
                time.sleep(1)
                now = time.time()
                
                # Health check every 60 seconds
                if now - last_check >= 60:
                    last_check = now
                    if not self.scheduler.is_running:
                        logger.error("Scheduler stopped unexpectedly! Triggering application restart.")
                        raise RuntimeError("Scheduler stopped unexpectedly")

                    # Check retry task health
                    if self._retry_running and (not self._retry_thread or not self._retry_thread.is_alive()):
                        logger.error("Retry task thread stopped unexpectedly! Triggering application restart.")
                        raise RuntimeError("Retry task thread stopped unexpectedly")

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self._shutdown_event.set()
            self.scheduler.stop()

            if not self._task_done.is_set():
                logger.info("Waiting for in-flight parsing task to stop...")
                if not self._task_done.wait(timeout=60):
                    logger.warning(
                        "Parsing task did not stop within 60s, proceeding with cleanup anyway"
                    )

            self._cleanup()
            logger.info("Application stopped")


def main():
    """Main entry point with watchdog restart loop."""
    # Backoff time before restarting after unexpected fatal errors
    restart_delay_seconds = 10

    while True:
        try:
            bot = BandcampBot()
            bot.run()
            # Normal shutdown (e.g. via signal) - do not restart
            break
        except SystemExit:
            # Respect explicit sys.exit() calls
            raise
        except Exception as e:
            logger.error(f"Fatal error in BandcampBot.run(): {e}", exc_info=True)
            logger.info(f"Restarting BandcampBot in {restart_delay_seconds} seconds...")
            try:
                time.sleep(restart_delay_seconds)
            except KeyboardInterrupt:
                # Allow immediate stop during backoff
                break


if __name__ == "__main__":
    main()
