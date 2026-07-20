"""Bandcamp parser module."""
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Generator, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class Release:
    """Represents a Bandcamp release."""
    url: str
    title: str
    artist: str
    tags: List[str] = field(default_factory=list)
    cover_url: Optional[str] = None
    description: Optional[str] = None
    release_date: Optional[datetime] = None
    location: Optional[str] = None
    is_preorder: Optional[bool] = None

    def __repr__(self) -> str:
        return f"<Release: {self.title} by {self.artist}>"

    def is_older_than_days(self, days: int) -> bool:
        """Check if release is older than specified days."""
        if not self.release_date or days <= 0:
            return False
        return (datetime.now() - self.release_date).days > days


class BandcampParser:
    """Fetches Bandcamp releases via Bandcamp's internal discover API.

    Bandcamp's anti-bot layer challenges the HTML /discover pages (and any
    browser automation hitting them, even through a clean residential
    proxy), but not this internal JSON endpoint, which plain HTTP requests
    can call directly.
    """

    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    # The endpoint the discover page itself uses when a visitor filters by a
    # specific tag rather than just browsing a top-level genre. Unlike the
    # older /api/discover/3/get_web (which only accepts ~15 curated genre
    # slugs via "g"), this one takes a real list of tag slugs and searches
    # across every genre - so a release whose primary genre is, say, "rock"
    # but which is tagged "hardcore-punk" is still found, instead of being
    # invisible unless we happened to also scan the "rock" feed.
    DISCOVER_API_URL = "https://bandcamp.com/api/discover/1/discover_web"

    # Retries for a single discover API page fetch before giving up on a
    # tag for this run. Processing many newly-blacklisted releases in a row
    # (one release-page GET each, see fetch_release_tags) has been observed
    # to trip Bandcamp's rate limiting right before the main tags are
    # fetched, failing every one of them in the same run - a short backoff
    # and retry rides out that kind of transient block instead of losing
    # the whole run's results for every tag.
    MAX_RETRIES = 3

    def __init__(
        self,
        user_agent: Optional[str] = None,
        request_delay: float = 1.5,
        shutdown_event: Optional[threading.Event] = None,
    ):
        """Initialize parser."""
        self.request_delay = request_delay
        # Signaled by the main thread on SIGTERM/SIGINT so a shutdown can
        # skip remaining tags instead of racing the cleanup.
        self.shutdown_event = shutdown_event or threading.Event()

        # Cursor-based pagination per tag: each call always fetches the
        # freshest page (cursor "*") so a new release is never missed, plus
        # one supplemental page picking up where the previous run's crawl
        # left off, for broader coverage of a tag's back catalog over time.
        self._tag_page_cursor: Dict[str, str] = {}

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent or self.DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })

    def _parse_api_item(self, item: dict, tag: str) -> Optional[Release]:
        """Convert one discover_web result item into a Release."""
        title = item.get('title')
        url = item.get('item_url')
        if not title or not url:
            return None
        url = url.split('?')[0]

        release_date = None
        raw_date = item.get('release_date')
        if raw_date:
            try:
                release_date = datetime.strptime(raw_date, '%Y-%m-%d %H:%M:%S UTC')
            except ValueError:
                pass

        cover_url = None
        image_id = (item.get('primary_image') or {}).get('image_id')
        if image_id:
            cover_url = f"https://f4.bcbits.com/img/a{int(image_id):010d}_10.jpg"

        is_preorder = item.get('is_album_preorder')

        return Release(
            url=url,
            title=title,
            artist=item.get('band_name') or 'Unknown Artist',
            tags=[tag],
            cover_url=cover_url,
            release_date=release_date,
            location=item.get('band_location') or None,
            is_preorder=bool(is_preorder) if is_preorder is not None else None
        )

    def _throttle(self) -> None:
        """Pace outbound requests so we don't hit Bandcamp with a burst of
        dozens of requests back to back - a likely trigger for the rate
        limiting seen after enriching many newly-found releases at once."""
        if self.request_delay > 0:
            time.sleep(self.request_delay)

    def _fetch_discover_tag_page(self, tag_slug: str, cursor: str):
        """Fetch a single page of results genuinely filtered by tag_slug
        (any Bandcamp tag - curated genre, official subgenre, or informal
        community tag all work the same way here). Retries on failure with
        an increasing backoff. Returns (items, next_cursor, total_count),
        or None if every attempt fails."""
        payload = {
            'category_id': 0,  # 0 = search across all genres
            'tag_norm_names': [tag_slug],
            'geoname_id': 0,
            'slice': 'new',
            'time_facet_id': None,
            'cursor': cursor,
            'size': 48,
            'include_result_types': ['a'],
            'followed_bands': False,
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            if attempt == 1:
                self._throttle()
            else:
                backoff = self.request_delay * (2 ** (attempt - 1))
                logger.info(
                    f"Retrying discover API for tag '{tag_slug}' in {backoff:.1f}s "
                    f"(attempt {attempt}/{self.MAX_RETRIES})"
                )
                time.sleep(backoff)

            try:
                response = self.session.post(self.DISCOVER_API_URL, json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.warning(
                    f"Discover API request failed for tag '{tag_slug}' "
                    f"(cursor {cursor}, attempt {attempt}/{self.MAX_RETRIES}): {e}"
                )
                continue

            if 'results' not in data:
                logger.warning(
                    f"Discover API returned no results field for tag '{tag_slug}' "
                    f"(attempt {attempt}/{self.MAX_RETRIES}): {data}"
                )
                continue

            return data['results'], data.get('cursor'), data.get('result_count') or 0

        logger.error(f"Discover API request for tag '{tag_slug}' failed after {self.MAX_RETRIES} attempts")
        return None

    def _fetch_via_discover_api(self, tag: str) -> Optional[List[Release]]:
        """Fetch releases actually tagged with `tag` via Bandcamp's discover_web
        API. Always includes the freshest page (cursor "*") so a genuinely new
        release is never missed; also folds in one supplemental page picking
        up where the previous run's crawl left off, for broader coverage of
        the tag's back catalog over time. Returns None only on a request
        error (an unrecognized/empty tag comes back as zero results, not an
        error)."""
        slug = tag.strip().lower().replace(' ', '-')

        fresh = self._fetch_discover_tag_page(slug, '*')
        if fresh is None:
            return None
        items, fresh_cursor, _ = fresh

        deeper_cursor = self._tag_page_cursor.get(slug, fresh_cursor)
        if deeper_cursor and deeper_cursor != '*':
            deeper = self._fetch_discover_tag_page(slug, deeper_cursor)
            if deeper is not None:
                deeper_items, next_cursor, _ = deeper
                items = items + deeper_items
                # Ran out of deeper results - restart the slow crawl right
                # after the fresh page next time instead of looping forever.
                self._tag_page_cursor[slug] = next_cursor if deeper_items else fresh_cursor

        releases = []
        seen_urls = set()
        for item in items:
            try:
                release = self._parse_api_item(item, tag)
            except Exception as e:
                logger.error(f"Error parsing API item: {e}")
                continue
            if release and release.url not in seen_urls:
                seen_urls.add(release.url)
                releases.append(release)
        return releases

    # Matches the tag links Bandcamp renders on a release's own page, e.g.
    # <a class="tag" href="https://bandcamp.com/discover/hardcore-punk?...">
    _RELEASE_TAG_RE = re.compile(r'<a class="tag" href="https://bandcamp\.com/discover/([^"?]+)\?')

    def fetch_release_tags(self, url: str) -> List[str]:
        """Fetch a release's own page and extract the full list of tags the
        artist actually applied (as normalized slugs, e.g. "hardcore-punk").

        Unlike /discover, individual release pages are server-rendered (no
        anti-bot challenge, no JS needed). The discover_web API only reports
        that a release matched the one tag it was searched for - this fills
        in the rest of the release's real tags, for storage and for a fuller
        Telegram message."""
        self._throttle()
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Could not fetch tags for {url}: {e}")
            return []

        return self._RELEASE_TAG_RE.findall(response.text)

    def get_releases_by_tag(self, tag: str) -> List[Release]:
        """Get releases by tag from Bandcamp."""
        if self.shutdown_event.is_set():
            return []

        releases = self._fetch_via_discover_api(tag)
        if releases is None:
            logger.warning(f"Discover API request failed for tag '{tag}'")
            return []

        logger.info(f"Fetched {len(releases)} releases for tag '{tag}' via Bandcamp API")
        return releases

    def get_releases_generator(self, tags: List[str]) -> Generator[Release, None, None]:
        """Generator yielding unique releases from all tags."""
        seen_urls = set()

        for tag in tags:
            for release in self.get_releases_by_tag(tag):
                if release.url not in seen_urls:
                    seen_urls.add(release.url)
                    yield release
