"""
extractors/base.py — Abstract base class for all media extractors.

All extractors must implement:
  - can_handle(url) -> bool
  - extract(url, options) -> dict | None  (metadata, no download)
  - download(url, options, target_dir) -> (list[str], error_str)

Normalized output contract for extract():
{
    "title":     str,
    "duration":  int,   # seconds
    "formats":   list,  # list of format dicts from yt-dlp or custom
    "thumbnail": str,   # URL
    "platform":  str,   # e.g. "youtube", "instagram"
}
"""

from abc import ABC, abstractmethod


class BaseExtractor(ABC):
    # Higher priority = checked first (for overlapping URL patterns)
    priority: int = 0

    # Capability flags — set on subclass
    supports_audio: bool = True
    supports_video: bool = True
    supports_batch: bool = False

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this extractor can process the given URL."""
        ...

    @abstractmethod
    def extract(self, url: str, options: dict = None) -> tuple[dict | None, str | None]:
        """
        Fetch metadata WITHOUT downloading.
        Returns: (info_dict, error_string)
        """
        ...

    @abstractmethod
    def download(self, url: str, options: dict = None, target_dir: str = None) -> tuple[list[str] | None, str | None]:
        """
        Download to target_dir and return a list of absolute file paths.
        Returns: (list_of_paths, error_string)
        """
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__.replace("Extractor", "").lower()
