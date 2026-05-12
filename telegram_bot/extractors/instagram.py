"""
extractors/instagram.py — Instagram extractor using instaloader.

Handles: Instagram Reels & Posts.
Priority: 20 (checked before generic YouTube extractor)
"""

import os
import shutil
import logging
import instaloader

from .base import BaseExtractor

logger = logging.getLogger(__name__)

MIN_FREE_SPACE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def _check_disk_space(path: str = "."):
    stat = shutil.disk_usage(path)
    if stat.free < MIN_FREE_SPACE_BYTES:
        free_gb = stat.free / (1024 ** 3)
        raise IOError(f"Not enough disk space. Only {free_gb:.2f} GB free (minimum 2 GB required).")


class InstagramExtractor(BaseExtractor):
    priority = 20
    supports_audio = False
    supports_video = True
    supports_batch = False

    def __init__(self):
        self._loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )

    def can_handle(self, url: str) -> bool:
        return "instagram.com" in url

    def extract(self, url: str, options: dict = None) -> tuple[dict | None, str | None]:
        """
        Fetch metadata from Instagram post.
        Extracts shortcode from URL and queries the API.
        """
        shortcode = self._parse_shortcode(url)
        if not shortcode:
            return None, "Could not parse Instagram shortcode from URL."

        try:
            post = instaloader.Post.from_shortcode(self._loader.context, shortcode)
            if not post.is_video:
                return None, "This Instagram post is not a video."

            info = {
                "title":     post.caption[:80] if post.caption else f"Instagram Reel ({shortcode})",
                "duration":  int(post.video_duration or 0),
                "formats":   [],  # Instagram doesn't expose format choices
                "thumbnail": post.url,
                "platform":  "instagram",
            }
            return info, None
        except Exception as e:
            return None, self._friendly_error(str(e))

    def download(
        self,
        url: str,
        options: dict = None,
        target_dir: str = None,
    ) -> tuple[list[str] | None, str | None]:
        """Download Instagram video. Returns list of .mp4 paths."""
        shortcode = self._parse_shortcode(url)
        if not shortcode:
            return None, "Could not parse Instagram shortcode from URL."

        download_base = target_dir or os.path.join("telegram_bot", "downloads")
        self._loader.dirname_pattern = os.path.join(download_base, "{target}")

        try:
            _check_disk_space()
        except IOError as e:
            return None, str(e)

        try:
            post = instaloader.Post.from_shortcode(self._loader.context, shortcode)
            if not post.is_video:
                return None, "This Instagram post is not a video."

            self._loader.download_post(post, target=shortcode)

            target_path = os.path.join(download_base, shortcode)
            paths = []
            if os.path.exists(target_path):
                for root, _, files in os.walk(target_path):
                    for file in files:
                        if file.endswith(".mp4"):
                            paths.append(os.path.abspath(os.path.join(root, file)))

            return (paths, None) if paths else (None, "Video file not found after download.")

        except Exception as e:
            return None, self._friendly_error(str(e))

    @staticmethod
    def _parse_shortcode(url: str) -> str | None:
        """Extract shortcode from Instagram URL."""
        import re
        match = re.search(r'instagram\.com/(?:p|reels|reel)/([^/?#&]+)', url)
        return match.group(1) if match else None

    @staticmethod
    def _friendly_error(error_str: str) -> str:
        s = error_str.lower()
        if "401" in s or "login required" in s:
            return "Instagram is blocking this video for anonymous users. Try again in a moment."
        return error_str
