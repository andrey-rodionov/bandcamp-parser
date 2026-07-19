#!/usr/bin/env python3
"""Run parsing task once immediately."""
import asyncio
import sys
import logging
import warnings
from pathlib import Path

# Suppress urllib3 OpenSSL warning on macOS
warnings.filterwarnings('ignore', message='.*urllib3.*OpenSSL.*', category=UserWarning)

sys.path.insert(0, str(Path(__file__).parent))

from src.config import config
from src.parser import BandcampParser
from src.database import Database
from src.telegram_bot import TelegramBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)


async def run_once():
    """Run parsing task once."""
    # Initialize components
    db = Database(db_path=config.database.db_path)
    parser = BandcampParser(
        user_agent=config.parser.user_agent,
        request_delay=config.parser.request_delay
    )
    telegram = TelegramBot(
        bot_token=config.telegram.bot_token,
        chat_id=config.telegram.chat_id,
        max_description_length=config.telegram.max_description_length
    )

    logger.info("Starting one-time parsing...")
    logger.info(f"Tags: {', '.join(config.tags)}")
    if config.blacklist_tags:
        logger.info(f"Blacklist: {', '.join(config.blacklist_tags)}")

    try:
        # Process blacklist tags first
        blacklisted = 0
        if config.blacklist_tags:
            logger.info("=" * 50)
            logger.info("Processing blacklist tags...")

            for tag in config.blacklist_tags:
                logger.info(f"Blacklist tag: {tag}")
                releases = parser.get_releases_by_tag(tag)

                for release in releases:
                    if db.exists(release.url):
                        continue

                    if db.add(
                        release_url=release.url,
                        title=release.title,
                        artist=release.artist,
                        tags=release.tags,
                        cover_url=release.cover_url
                    ):
                        db.mark_sent(release.url)
                        blacklisted += 1

            logger.info(f"Blacklisted {blacklisted} releases")

        # Process main tags
        logger.info("=" * 50)
        logger.info("Processing main tags...")

        blacklist_slugs = {t.strip().lower().replace(' ', '-') for t in config.blacklist_tags}
        sent = 0
        failed = 0
        skipped_old = 0

        for tag in config.tags:
            logger.info(f"Processing tag: {tag}")
            releases = parser.get_releases_by_tag(tag)

            for release in releases:
                if db.exists(release.url):
                    continue

                # Bandcamp's "new" feed isn't strictly chronological and
                # can surface older catalog items - skip fetching real tags
                # for those entirely and just record them without sending.
                if release.is_older_than_days(config.max_release_age_days):
                    if db.add(
                        release_url=release.url,
                        title=release.title,
                        artist=release.artist,
                        tags=release.tags,
                        cover_url=release.cover_url
                    ):
                        db.mark_sent(release.url)
                        skipped_old += 1
                    continue

                # Fill in the release's full real tag list - the discover
                # API only tells us it matched the one tag we searched for.
                real_tags = parser.fetch_release_tags(release.url)
                if real_tags:
                    release.tags = real_tags

                # A release found under a main tag can also carry a
                # blacklisted tag that its own search never surfaced (e.g.
                # buried deep in a high-volume feed) - catch it here using
                # the real tag list instead of relying solely on the
                # blacklist pre-pass above.
                if blacklist_slugs & {t.strip().lower().replace(' ', '-') for t in release.tags}:
                    if db.add(
                        release_url=release.url,
                        title=release.title,
                        artist=release.artist,
                        tags=release.tags,
                        cover_url=release.cover_url
                    ):
                        db.mark_sent(release.url)
                        blacklisted += 1
                        logger.info(f"Blacklisted (real tag match): {release.title}")
                    continue

                # Add to DB first (even if sending fails) so a failed send
                # isn't silently dropped - the long-running service's retry
                # loop will pick it up (sent_at stays NULL until it succeeds).
                if not db.add(
                    release_url=release.url,
                    title=release.title,
                    artist=release.artist,
                    tags=release.tags,
                    cover_url=release.cover_url
                ):
                    continue

                success = await telegram.send_release(release)

                if success:
                    db.mark_sent(release.url)
                    sent += 1
                    logger.info(f"Sent: {release.title} by {release.artist}")
                    await asyncio.sleep(2)
                else:
                    failed += 1
                    logger.warning(f"Failed to send: {release.title} (saved to DB for retry)")

        # Summary
        logger.info(
            f"Sent {sent} new releases ({failed} failed, will retry, "
            f"{blacklisted} blacklisted, {skipped_old} too old)"
        )

        if sent > 0:
            await telegram.send_message(f"✅ Found and sent {sent} new release(s)")
        else:
            logger.info("No new releases found")
            await telegram.send_message("ℹ️ No new releases found")

        logger.info("Parsing completed!")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await telegram.send_message(f"❌ Error: {e}")

    finally:
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        parser.session.close()


if __name__ == "__main__":
    asyncio.run(run_once())
