"""Main application module."""
import asyncio
import logging
import signal
import sys
import time
import warnings
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bandcamp_bot.log'),
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
        
        # Parser
        self.parser = BandcampParser(
            user_agent=config.parser.user_agent,
            request_delay=config.parser.request_delay
        )
        
        # Telegram bot
        self.telegram = TelegramBot(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
            max_description_length=config.telegram.max_description_length
        )
        
        # Scheduler
        self.scheduler = TaskScheduler(
            times=config.schedule.times,
            timezone=config.schedule.timezone
        )
        self.scheduler.set_task(self.run_parsing)
    
    async def _process_release(
        self, 
        release: Release, 
        send_to_telegram: bool = True
    ) -> bool:
        """Process a single release. Returns True if sent/added."""
        # Check if exists
        if self.db.exists(release.url):
            return False
        
        if send_to_telegram:
            # Send to Telegram
            success = await self.telegram.send_release(release)
            if not success:
                logger.warning(f"Failed to send: {release.title}")
                return False
        
        # Add to database
        self.db.add(
            release_url=release.url,
            title=release.title,
            artist=release.artist,
            tags=release.tags,
            cover_url=release.cover_url,
            description=release.description
        )
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
            logger.info(f"Processing tag: {tag}")
            releases = self.parser.get_releases_by_tag(tag)
            tag_sent = 0
            
            for release in releases:
                # Check if exists
                if self.db.exists(release.url):
                    continue
                
                # Send to Telegram
                success = await self.telegram.send_release(release)
                
                if success:
                    self.db.add(
                        release_url=release.url,
                        title=release.title,
                        artist=release.artist,
                        tags=release.tags,
                        cover_url=release.cover_url
                    )
                    self.db.mark_sent(release.url)
                    result.sent += 1
                    tag_sent += 1
                    logger.info(f"Sent: {release.title} by {release.artist}")
                    await asyncio.sleep(2)  # Rate limiting
                else:
                    result.failed += 1
            
            if tag_sent == 0:
                logger.info(f"No new releases for '{tag}'")
            else:
                logger.info(f"Tag '{tag}': sent {tag_sent}")
        
        return result
    
    async def run_parsing(self) -> None:
        """Main parsing task."""
        logger.info("Starting parsing task...")
        
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
            
            logger.info("Parsing task completed")
            
        except Exception as e:
            logger.error(f"Error in parsing: {e}", exc_info=True)
            try:
                await asyncio.wait_for(
                    self.telegram.send_message(f"❌ Parsing error: {e}"),
                    timeout=30.0
                )
            except Exception:
                pass
    
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
    
    def _cleanup(self) -> None:
        """Cleanup resources."""
        # Suppress urllib3 warnings during shutdown
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        
        if self.parser.driver:
            try:
                self.parser.driver.quit()
                self.parser.driver = None
                logger.info("Selenium driver closed")
            except Exception:
                pass
        
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
        
        # Send startup message
        try:
            asyncio.run(self._send_startup_message())
        except Exception as e:
            logger.warning(f"Could not send startup message: {e}")
        
        # Signal handlers
        def handle_signal(sig, frame):
            logger.info("Shutting down...")
            self.scheduler.stop()
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
                        logger.error("Scheduler stopped unexpectedly!")
                        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.scheduler.stop()
            self._cleanup()
            logger.info("Application stopped")


# Backwards compatibility
BandcampBotApp = BandcampBot


def main():
    """Main entry point."""
    try:
        bot = BandcampBot()
        bot.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
