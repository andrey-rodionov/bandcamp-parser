"""Bandcamp Parser Bot - Source modules."""

from src.config import config, Config
from src.database import Database, DatabaseStats
from src.parser import BandcampParser, Release
from src.telegram_bot import TelegramBot
from src.scheduler import TaskScheduler
from src.main import BandcampBot

__all__ = [
    'config',
    'Config',
    'Database',
    'DatabaseStats',
    'BandcampParser',
    'Release',
    'TelegramBot',
    'TaskScheduler',
    'BandcampBot',
]

__version__ = '2.0.0'
