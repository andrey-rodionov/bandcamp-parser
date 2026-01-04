"""Configuration management module."""
import os
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    """Schedule configuration."""
    times: List[str]
    timezone: str


@dataclass  
class ParserConfig:
    """Parser configuration."""
    request_delay: float
    user_agent: str


@dataclass
class TelegramConfig:
    """Telegram configuration."""
    bot_token: str
    chat_id: str
    max_description_length: int


@dataclass
class DatabaseConfig:
    """Database configuration."""
    db_path: str
    cleanup_days: int


class Config:
    """Application configuration."""
    
    # Default values
    DEFAULT_SCHEDULE_TIMES = ["08:00", "14:00", "22:00"]
    DEFAULT_TIMEZONE = "UTC"
    DEFAULT_TAGS = ["punk", "hardcore"]
    DEFAULT_REQUEST_DELAY = 1.5
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    DEFAULT_MAX_DESC_LENGTH = 0
    DEFAULT_DB_PATH = "bandcamp_releases.db"
    DEFAULT_CLEANUP_DAYS = 90
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize configuration from YAML file and environment variables."""
        self._config_path = Path(config_path)
        self._raw_config = self._load_yaml()
        self._validate_env_vars()
        
    def _load_yaml(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not self._config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self._config_path}")
        
        with open(self._config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        logger.debug(f"Loaded configuration from {self._config_path}")
        return config
    
    def _validate_env_vars(self) -> None:
        """Validate required environment variables."""
        if not os.getenv("TELEGRAM_BOT_TOKEN"):
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
        if not os.getenv("TELEGRAM_CHAT_ID"):
            raise ValueError("TELEGRAM_CHAT_ID environment variable is required")
    
    def _get(self, *keys: str, default: Any = None) -> Any:
        """Get nested config value."""
        value = self._raw_config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value
    
    @property
    def schedule(self) -> ScheduleConfig:
        """Get schedule configuration."""
        return ScheduleConfig(
            times=self._get("schedule", "times", default=self.DEFAULT_SCHEDULE_TIMES),
            timezone=self._get("schedule", "timezone", default=self.DEFAULT_TIMEZONE)
        )
    
    @property
    def tags(self) -> List[str]:
        """Get list of tags to monitor."""
        return self._get("tags", default=self.DEFAULT_TAGS)
    
    @property
    def blacklist_tags(self) -> List[str]:
        """Get list of blacklist tags."""
        return self._get("blacklist_tags", default=[])
    
    @property
    def parser(self) -> ParserConfig:
        """Get parser configuration."""
        return ParserConfig(
            request_delay=self._get("parser", "request_delay", default=self.DEFAULT_REQUEST_DELAY),
            user_agent=self._get("parser", "user_agent", default=self.DEFAULT_USER_AGENT)
        )
    
    @property
    def telegram(self) -> TelegramConfig:
        """Get Telegram configuration."""
        return TelegramConfig(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            max_description_length=self._get("telegram", "max_description_length", default=self.DEFAULT_MAX_DESC_LENGTH)
        )
    
    @property
    def database(self) -> DatabaseConfig:
        """Get database configuration."""
        return DatabaseConfig(
            db_path=self._get("database", "db_path", default=self.DEFAULT_DB_PATH),
            cleanup_days=self._get("database", "cleanup_days", default=self.DEFAULT_CLEANUP_DAYS)
        )
    
    # Legacy compatibility properties
    @property
    def schedule_times(self) -> List[str]:
        return self.schedule.times
    
    @property
    def schedule_timezone(self) -> str:
        return self.schedule.timezone
    
    @property
    def telegram_bot_token(self) -> str:
        return self.telegram.bot_token
    
    @property
    def telegram_chat_id(self) -> str:
        return self.telegram.chat_id
    
    @property
    def parser_config(self) -> Dict[str, Any]:
        """Legacy: Get parser config as dict."""
        p = self.parser
        return {
            "request_delay": p.request_delay,
            "user_agent": p.user_agent
        }
    
    @property
    def telegram_config(self) -> Dict[str, Any]:
        """Legacy: Get telegram config as dict."""
        return {"max_description_length": self.telegram.max_description_length}
    
    @property
    def database_config(self) -> Dict[str, Any]:
        """Legacy: Get database config as dict."""
        d = self.database
        return {"db_path": d.db_path, "cleanup_days": d.cleanup_days}
    
    @property
    def _config(self) -> Dict[str, Any]:
        """Legacy: Raw config access."""
        return self._raw_config


# Global config instance
config = Config()
