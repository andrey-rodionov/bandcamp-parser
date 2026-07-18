"""Bandcamp parser module."""
import logging
import threading
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

    # Bandcamp's internal API backing the /discover page. Only understands
    # ~15 curated top-level genre slugs (e.g. "punk") via the "g" param -
    # subgenres/community tags fall back to "g": "all" server-side, which
    # we detect and treat as "not supported here".
    DISCOVER_API_URL = "https://bandcamp.com/api/discover/3/get_web"

    # Empirically observed items-per-page for the discover API (it ignores
    # any "size" param we send and always returns this many, except on the
    # last page of a genre's result set).
    GENRE_PAGE_SIZE = 48

    # The discover API's "g" param only accepts Bandcamp's ~15-20 curated
    # top-level genre slugs. Our tags that aren't themselves one of those
    # (subgenres / community tags like "hardcore punk" or "d-beat") are
    # mapped here to the closest curated parent genre, found by cross-
    # referencing against Bandcamp's own curated genre/subgenre list (see
    # punk/metal subgenre entries: hardcore-punk, crust-punk, post-punk,
    # punk-rock, garage under "punk"; hardcore, metalcore under "metal";
    # techno, happy-hardcore under "electronic").
    GENRE_FALLBACK = {
        'hardcore': 'metal',
        'hc': 'metal',
        'hardcore-punk': 'punk',
        'hcpunk': 'punk',
        'raw-punk': 'punk',
        'd-beat': 'punk',
        'dbeat': 'punk',
        'crust-punk': 'punk',
        'post-punk': 'punk',
        'punk-rock': 'punk',
        'metalcore': 'metal',
        'egg-punk': 'punk',
        'street-punk': 'punk',
        'uk82': 'punk',
        'h8000': 'metal',
        'garage-punk': 'punk',
        'techno': 'electronic',
        'happy-hardcore': 'electronic',
    }

    def __init__(
        self,
        user_agent: Optional[str] = None,
        request_delay: float = 1.5,
        shutdown_event: Optional[threading.Event] = None,
        genre_fallback: Optional[Dict[str, str]] = None,
    ):
        """Initialize parser."""
        self.request_delay = request_delay
        # Signaled by the main thread on SIGTERM/SIGINT so a shutdown can
        # skip remaining tags instead of racing the cleanup.
        self.shutdown_event = shutdown_event or threading.Event()

        # Informal-tag -> curated-genre mapping (see GENRE_FALLBACK below).
        # Defaults to the built-in dict so this class stays usable standalone
        # (e.g. from run_once.py) without a Config instance; callers that
        # have one (main.py) pass config.genre_fallback instead, which layers
        # in any admin-edited overrides.
        self.genre_fallback = genre_fallback if genre_fallback is not None else self.GENRE_FALLBACK

        # Several of our configured tags map to the same curated genre (see
        # GENRE_FALLBACK). A per-genre page cursor lets each subsequent tag
        # mapped to the same genre fold in a different supplemental page
        # instead of only ever re-fetching page 0.
        self._genre_page_cursor: Dict[str, int] = {}

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent or self.DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })

    def _parse_api_item(self, item: dict, tag: str) -> Optional[Release]:
        """Convert one discover-API item into a Release."""
        title = item.get('primary_text')
        if not title:
            return None

        url_hints = item.get('url_hints') or {}
        host = url_hints.get('custom_domain') or (
            f"{url_hints.get('subdomain')}.bandcamp.com" if url_hints.get('subdomain') else None
        )
        slug = url_hints.get('slug')
        if not host or not slug:
            return None
        item_type = url_hints.get('item_type') or item.get('type')
        path = 'track' if item_type == 't' else 'album'
        url = f"https://{host}/{path}/{slug}"

        release_date = None
        raw_date = item.get('publish_date')
        if raw_date:
            try:
                release_date = datetime.strptime(raw_date.replace(' GMT', ''), '%d %b %Y %H:%M:%S')
            except ValueError:
                pass

        cover_url = None
        art_id = item.get('art_id')
        if art_id:
            cover_url = f"https://f4.bcbits.com/img/a{int(art_id):010d}_10.jpg"

        is_preorder = item.get('is_preorder')

        return Release(
            url=url,
            title=title,
            artist=item.get('secondary_text') or 'Unknown Artist',
            tags=[tag or item.get('genre_text')],
            cover_url=cover_url,
            release_date=release_date,
            location=item.get('location_text') or None,
            is_preorder=bool(is_preorder) if is_preorder is not None else None
        )

    def _fetch_discover_genre_page(self, genre_slug: str, page: int):
        """Fetch a single raw page of a curated genre feed. Returns
        (items, total_count), or None if genre_slug isn't a genre Bandcamp
        recognizes."""
        try:
            response = self.session.post(
                self.DISCOVER_API_URL,
                json={'g': genre_slug, 's': 'new', 'f': 'all', 'p': page, 'w': 0},
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.debug(f"Discover API request failed for '{genre_slug}' (page {page}): {e}")
            return [], 0

        if data.get('args', {}).get('g') != genre_slug:
            return None
        return data.get('items', []), data.get('total_count') or 0

    def _fetch_discover_genre(self, genre_slug: str, tag_label: Optional[str] = None) -> Optional[List[Release]]:
        """Fetch a curated top-level genre feed. Always includes page 0
        (the freshest releases) so genuinely new releases are never missed
        even when several tags share one fallback genre; also folds in one
        supplemental, slowly-advancing deeper page per call so those shared
        tags still get broader catalog coverage over multiple runs. Returns
        None if Bandcamp didn't recognize genre_slug as a curated genre."""
        fresh = self._fetch_discover_genre_page(genre_slug, 0)
        if fresh is None:
            return None
        items, total_count = fresh

        deeper_page = self._genre_page_cursor.get(genre_slug, 1)
        if deeper_page:
            deeper = self._fetch_discover_genre_page(genre_slug, deeper_page)
            if deeper is not None:
                deeper_items, _ = deeper
                items = items + deeper_items

            total_pages = -(-total_count // self.GENRE_PAGE_SIZE)  # ceil div
            next_page = deeper_page + 1
            if next_page >= total_pages:
                next_page = 1  # page 0 is always fetched separately above
            self._genre_page_cursor[genre_slug] = next_page

        releases = []
        seen_urls = set()
        for item in items:
            try:
                release = self._parse_api_item(item, tag_label or genre_slug)
            except Exception as e:
                logger.error(f"Error parsing API item: {e}")
                continue
            if release and release.url not in seen_urls:
                seen_urls.add(release.url)
                releases.append(release)
        return releases

    def _fetch_via_discover_api(self, tag: str) -> Optional[List[Release]]:
        """Fetch releases for a tag via Bandcamp's internal discover API.
        Returns None only if the tag isn't a curated genre AND has no
        GENRE_FALLBACK mapping."""
        slug = tag.strip().lower().replace(' ', '-')

        releases = self._fetch_discover_genre(slug)
        if releases is not None:
            return releases

        fallback_genre = self.genre_fallback.get(slug)
        if fallback_genre:
            logger.info(
                f"'{tag}' isn't a Bandcamp top-level genre, "
                f"using broader '{fallback_genre}' feed instead"
            )
            return self._fetch_discover_genre(fallback_genre, tag_label=tag)

        return None

    def get_releases_by_tag(self, tag: str) -> List[Release]:
        """Get releases by tag from Bandcamp."""
        if self.shutdown_event.is_set():
            return []

        releases = self._fetch_via_discover_api(tag)
        if releases is None:
            logger.warning(
                f"'{tag}' has no working data source (not a Bandcamp genre "
                f"and no GENRE_FALLBACK mapping) - add one in parser.py"
            )
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
