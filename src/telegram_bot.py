"""Telegram bot module for sending releases."""
import logging
import asyncio
from typing import Any, Protocol
from telegram import Bot
from telegram.error import TelegramError, TimedOut, NetworkError, RetryAfter
from telegram.request import HTTPXRequest

logger = logging.getLogger(__name__)


class ReleaseProtocol(Protocol):
    """Protocol for release objects."""
    url: str
    title: str
    artist: str
    tags: list
    release_date: Any
    location: Any
    is_preorder: Any


class TelegramBot:
    """Telegram bot for sending release notifications."""
    
    # Timeouts (seconds) - increased for unstable networks
    TIMEOUT = 30.0
    MAX_RETRIES = 5
    
    # Backoff multiplier (seconds)
    BACKOFF_MULTIPLIER = 5
    
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        max_description_length: int = 0
    ):
        """Initialize Telegram bot."""
        request = HTTPXRequest(
            connection_pool_size=8,
            read_timeout=self.TIMEOUT,
            write_timeout=self.TIMEOUT,
            connect_timeout=self.TIMEOUT,
            pool_timeout=self.TIMEOUT
        )
        self._bot = Bot(token=bot_token, request=request)
        self._chat_id = chat_id
        self._max_description_length = max_description_length
    
    @property
    def bot(self) -> Bot:
        """Get bot instance."""
        return self._bot
    
    @property
    def chat_id(self) -> str:
        """Get chat ID."""
        return self._chat_id
    
    @property
    def max_description_length(self) -> int:
        """Get max description length."""
        return self._max_description_length
    
    def _format_release_message(self, release: ReleaseProtocol) -> str:
        """Format release information as Telegram message.

        Field order: artist, title, genre, publish date, location, link,
        preorder status.
        """
        lines = [
            f"👤 <b>{self._escape_html(release.artist)}</b>",
            f"🎵 <b>{self._escape_html(release.title)}</b>",
        ]

        if release.tags:
            tags_str = ", ".join(tag for tag in release.tags if tag)
            if tags_str:
                lines.append(f"🏷️ {self._escape_html(tags_str)}")

        release_date = getattr(release, 'release_date', None)
        if release_date:
            lines.append(f"📅 {release_date.strftime('%d %b %Y %H:%M')}")

        location = getattr(release, 'location', None)
        if location:
            lines.append(f"📍 {self._escape_html(location)}")

        lines.append(f"🔗 <a href='{release.url}'>Open on Bandcamp</a>")

        is_preorder = getattr(release, 'is_preorder', None)
        if is_preorder is not None:
            lines.append(f"⏳ Preorder: {'Yes' if is_preorder else 'No'}")

        return "\n".join(lines)
    
    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
    
    async def _send_with_retry(
        self,
        send_func,
        error_context: str = "message"
    ) -> bool:
        """Send message with retry logic."""
        for attempt in range(self.MAX_RETRIES):
            try:
                await asyncio.wait_for(send_func(), timeout=self.TIMEOUT)
                return True
                
            except (TimedOut, NetworkError, asyncio.TimeoutError) as e:
                wait_time = self.BACKOFF_MULTIPLIER * (attempt + 1)
                logger.warning(
                    f"Timeout sending {error_context} "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
                
                if attempt < self.MAX_RETRIES - 1:
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to send {error_context} after {self.MAX_RETRIES} attempts"
                    )
                    return False
                    
            except RetryAfter as e:
                # Respect Telegram flood control hints where possible
                wait_time = int(getattr(e, "retry_after", self.BACKOFF_MULTIPLIER * (attempt + 1)))
                logger.warning(
                    f"Telegram rate limit for {error_context}: retry after {wait_time}s "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                )
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Failed to send {error_context} due to repeated rate limits")
                return False

            except TelegramError as e:
                logger.error(f"Telegram error sending {error_context}: {e}")
                return False
                
            except Exception as e:
                logger.error(f"Unexpected error sending {error_context}: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.BACKOFF_MULTIPLIER * (attempt + 1))
                else:
                    return False
        
        return False
    
    async def send_release(self, release: ReleaseProtocol) -> bool:
        """Send release notification to Telegram."""
        message = self._format_release_message(release)
        
        async def send():
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
        
        success = await self._send_with_retry(
            send, 
            f"release '{release.title}'"
        )
        
        if success:
            logger.info(f"Sent release: {release.title} by {release.artist}")
        
        return success
    
    async def send_message(self, text: str) -> bool:
        """Send plain text message."""
        async def send():
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text
            )
        
        return await self._send_with_retry(send, "message")
    
    async def send_html(self, html: str) -> bool:
        """Send HTML formatted message."""
        async def send():
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=html,
                parse_mode='HTML'
            )
        
        return await self._send_with_retry(send, "HTML message")
