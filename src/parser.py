"""Bandcamp parser module."""
import logging
import platform
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Generator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Selenium imports (optional)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


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
    
    def __repr__(self) -> str:
        return f"<Release: {self.title} by {self.artist}>"
    
    def is_older_than_days(self, days: int) -> bool:
        """Check if release is older than specified days."""
        if not self.release_date or days <= 0:
            return False
        return (datetime.now() - self.release_date).days > days


# Backwards compatibility alias
BandcampRelease = Release


class SeleniumHelper:
    """Helper class for Selenium operations."""
    
    # Timeouts
    PAGE_LOAD_TIMEOUT = 10
    IMPLICIT_WAIT = 5
    ELEMENT_WAIT = 3
    ACTION_DELAY = 5
    
    # XPath selectors
    COOKIE_SELECTORS = [
        "//button[contains(text(), 'Accept')]",
        "//button[contains(@class, 'accept')]",
        "//div[contains(@class, 'cookie')]//button",
    ]
    
    VIEW_MORE_SELECTORS = [
        "//button[@id='view-more']",
        "//button[@data-test='view-more']",
        "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'view more')]",
        "//button[contains(@class, 'more')]",
    ]
    
    def __init__(self, driver):
        self.driver = driver
    
    def click_element(self, element) -> bool:
        """Try multiple methods to click an element."""
        # Method 1: JavaScript click
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            pass
        
        # Method 2: Regular click
        try:
            element.click()
            return True
        except Exception:
            pass
        
        # Method 3: ActionChains
        try:
            ActionChains(self.driver).move_to_element(element).click().perform()
            return True
        except Exception:
            pass
        
        return False
    
    def scroll_into_view(self, element) -> None:
        """Scroll element into view."""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", 
                element
            )
            time.sleep(0.5)
        except Exception:
            pass
    
    def scroll_to_bottom(self) -> None:
        """Scroll to bottom of page."""
        try:
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            for _ in range(5):
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
        except Exception as e:
            logger.debug(f"Scroll error: {e}")
    
    def find_and_click(self, selectors: List[str], description: str) -> bool:
        """Find element by selectors and click it."""
        for selector in selectors:
            try:
                wait = WebDriverWait(self.driver, self.ELEMENT_WAIT)
                element = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                self.scroll_into_view(element)
                if self.click_element(element):
                    logger.info(f"Clicked {description}")
                    return True
            except Exception:
                continue
        return False
    
    def accept_cookies(self) -> bool:
        """Accept cookie consent if present."""
        result = self.find_and_click(self.COOKIE_SELECTORS, "cookie consent")
        if result:
            time.sleep(self.ACTION_DELAY)
        return result
    
    def click_view_more(self, max_clicks: int = 5) -> int:
        """Click 'View more results' button repeatedly."""
        clicks = 0
        
        for i in range(max_clicks):
            if i > 0:
                time.sleep(self.ACTION_DELAY)
            
            self.scroll_to_bottom()
            time.sleep(3)
            
            clicked = False
            for selector in self.VIEW_MORE_SELECTORS:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            text = elem.text.lower()
                            if 'more' in text:
                                self.scroll_into_view(elem)
                                if self.click_element(elem):
                                    clicks += 1
                                    clicked = True
                                    logger.info(f"Clicked 'View more' ({clicks}/{max_clicks})")
                                    break
                except Exception:
                    continue
                if clicked:
                    break
            
            if not clicked:
                if clicks == 0:
                    logger.warning("'View more' button not found")
                else:
                    logger.info(f"'View more' button disappeared after {clicks} clicks")
                break
        
        return clicks


class BandcampParser:
    """Parser for Bandcamp releases."""
    
    BASE_URL = "https://bandcamp.com"
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    def __init__(
        self,
        base_url: str = BASE_URL,
        user_agent: Optional[str] = None,
        request_delay: float = 1.5,
        use_selenium: bool = True
    ):
        """Initialize parser."""
        self.base_url = base_url.rstrip('/')
        self.request_delay = request_delay
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE
        
        # HTTP session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent or self.DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
        
        # Selenium driver
        self.driver = None
        self._helper: Optional[SeleniumHelper] = None
        
        if self.use_selenium:
            self._init_driver()
        elif use_selenium and not SELENIUM_AVAILABLE:
            logger.warning("Selenium not available. Install: pip install selenium")
    
    def _init_driver(self) -> None:
        """Initialize Selenium WebDriver."""
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--window-size=1280,720')
            options.add_argument('--disable-images')
            options.add_argument('--blink-settings=imagesEnabled=false')
            options.add_argument(f'user-agent={self.session.headers["User-Agent"]}')
            
            # Linux-specific options
            if platform.system() != 'Windows':
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(SeleniumHelper.PAGE_LOAD_TIMEOUT)
            self.driver.implicitly_wait(SeleniumHelper.IMPLICIT_WAIT)
            self._helper = SeleniumHelper(self.driver)
            
            logger.info("Selenium WebDriver initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Selenium: {e}")
            logger.warning("Falling back to requests")
            self.use_selenium = False
            self.driver = None
    
    def _restart_driver(self) -> bool:
        """Restart Selenium driver."""
        if not self.use_selenium:
            return False
        
        try:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            
            self._init_driver()
            return self.driver is not None
            
        except Exception as e:
            logger.error(f"Failed to restart driver: {e}")
            return False
    
    def __del__(self):
        """Cleanup."""
        # Suppress urllib3 warnings during shutdown
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
            except Exception:
                pass
    
    def _fetch_with_requests(self, url: str, retries: int = 2) -> Optional[str]:
        """Fetch page using requests library."""
        for attempt in range(retries):
            try:
                time.sleep(self.request_delay)
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
                return response.text
            except requests.Timeout:
                logger.warning(f"Timeout fetching {url} (attempt {attempt + 1})")
                time.sleep(3 * (attempt + 1))
            except requests.RequestException as e:
                logger.error(f"Request error: {e}")
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        return None
    
    def _fetch_with_selenium(
        self, 
        url: str, 
        click_view_more: bool = False,
        retries: int = 2
    ) -> Optional[str]:
        """Fetch page using Selenium."""
        if not self.driver or not self._helper:
            return None
        
        for attempt in range(retries):
            try:
                self.driver.get(url)
                time.sleep(SeleniumHelper.ACTION_DELAY)
                
                # Handle cookie consent
                self._helper.accept_cookies()
                time.sleep(SeleniumHelper.ACTION_DELAY)
                
                # Click view more if requested
                if click_view_more:
                    logger.info("Clicking 'View more results'...")
                    clicks = self._helper.click_view_more()
                    if clicks > 0:
                        logger.info(f"✓ Clicked 'View more' {clicks} time(s)")
                
                return self.driver.page_source
                
            except Exception as e:
                logger.warning(f"Selenium error (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    self._restart_driver()
                    time.sleep(3 * (attempt + 1))
        
        return None
    
    def _fetch_page(self, url: str, click_view_more: bool = False) -> Optional[str]:
        """Fetch page HTML."""
        if self.use_selenium and self.driver:
            html = self._fetch_with_selenium(url, click_view_more)
            if html:
                return html
            logger.warning("Selenium failed, falling back to requests")
        
        return self._fetch_with_requests(url)
    
    def _parse_release_link(self, link, tag: str) -> Optional[Release]:
        """Parse release from link element."""
        href = link.get('href', '')
        if not href:
            return None
        
        # Clean and normalize URL
        href = href.split('?')[0]
        if not href.startswith('http'):
            release_url = urljoin(self.base_url, href)
        else:
            release_url = href
        
        # Extract title and artist
        text = link.get_text(strip=True)
        title, artist = None, None
        
        if 'by' in text.lower():
            parts = re.split(r'\s+by\s+', text, flags=re.IGNORECASE)
            if len(parts) >= 2:
                title = parts[0].strip()
                artist = parts[-1].strip()
        
        # Try parent elements
        if not title or not artist:
            parent = link.parent
            if parent:
                for elem in parent.find_all(['div', 'span']):
                    cls = str(elem.get('class', [])).lower()
                    if 'title' in cls or 'name' in cls:
                        title = title or elem.get_text(strip=True)
                    if 'artist' in cls or 'by' in cls:
                        artist = artist or elem.get_text(strip=True)
        
        # Fallback
        if not title:
            title = text.split('by')[0].strip() if 'by' in text else text
        
        if not artist:
            match = re.search(r'https?://([^.]+)\.bandcamp\.com', release_url)
            if match:
                artist = match.group(1).replace('-', ' ').title()
            else:
                artist = "Unknown Artist"
        
        if not title:
            return None
        
        # Extract cover image
        cover_url = None
        img = link.find('img')
        if not img and link.parent:
            img = link.parent.find('img')
        if img:
            cover_url = img.get('src') or img.get('data-src')
            if cover_url and not cover_url.startswith('http'):
                cover_url = urljoin(self.base_url, cover_url)
        
        return Release(
            url=release_url,
            title=title,
            artist=artist,
            tags=[tag],
            cover_url=cover_url
        )
    
    def get_releases_by_tag(self, tag: str) -> List[Release]:
        """Get releases by tag from Bandcamp."""
        releases = []
        tag_url = tag.replace(' ', '-')
        
        # Restart driver for fresh state
        if self.use_selenium:
            self._restart_driver()
            if not self.driver:
                logger.error(f"Driver not available for tag '{tag}'")
                return releases
        
        url = f"{self.base_url}/discover/{tag_url}?s=new"
        
        logger.info(f"Fetching releases for tag '{tag}'")
        
        html = self._fetch_page(url, click_view_more=True)
        if not html:
            return releases
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find release links
        links = soup.find_all('a', href=re.compile(r'/album/|/track/'))
        
        # Deduplicate
        seen = set()
        unique_links = []
        for link in links:
            href = link.get('href', '').split('?')[0]
            if href and href not in seen:
                seen.add(href)
                unique_links.append(link)
        
        if not unique_links:
            logger.warning(f"No releases found for tag '{tag}'")
            return releases
        
        for link in unique_links:
            try:
                release = self._parse_release_link(link, tag)
                if release:
                    releases.append(release)
            except Exception as e:
                logger.error(f"Error parsing release: {e}")
        
        logger.info(f"Found {len(releases)} releases for tag '{tag}'")
        return releases
    
    def get_releases_generator(self, tags: List[str]) -> Generator[Release, None, None]:
        """Generator yielding unique releases from all tags."""
        seen_urls = set()
        
        for tag in tags:
            for release in self.get_releases_by_tag(tag):
                if release.url not in seen_urls:
                    seen_urls.add(release.url)
                    yield release
