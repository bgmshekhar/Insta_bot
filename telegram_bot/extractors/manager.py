"""
extractors/manager.py — Plugin Manager.

Registers all extractors sorted by priority (highest first).
Provides get_extractor(url) for the bot to look up the right handler.
"""

import logging
from .base import BaseExtractor
from .instagram import InstagramExtractor
from .youtube import YouTubeExtractor

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self):
        # Register all extractors here; sorted by priority (desc)
        self._extractors: list[BaseExtractor] = sorted(
            [
                InstagramExtractor(),
                YouTubeExtractor(),
            ],
            key=lambda e: e.priority,
            reverse=True,
        )
        logger.info(f"PluginManager loaded {len(self._extractors)} extractor(s): "
                    f"{[e.name for e in self._extractors]}")

    def get_extractor(self, url: str) -> BaseExtractor | None:
        """Return the first extractor that can handle this URL."""
        for extractor in self._extractors:
            if extractor.can_handle(url):
                return extractor
        return None

    def detect_platform(self, url: str) -> str:
        """Return a string label for analytics."""
        extractor = self.get_extractor(url)
        if extractor:
            return extractor.name
        return "unknown"
