"""
extractors/youtube.py — YouTube/Universal extractor using yt-dlp.

Handles: YouTube, TikTok, Twitter/X, Pinterest, and most public video sites.
Priority: 10 (lower than Instagram to avoid conflict)
"""

import os
import uuid
import shutil
import logging
import yt_dlp

from .base import BaseExtractor

logger = logging.getLogger(__name__)

MIN_FREE_SPACE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def _check_disk_space(path: str = "."):
    stat = shutil.disk_usage(path)
    if stat.free < MIN_FREE_SPACE_BYTES:
        free_gb = stat.free / (1024 ** 3)
        raise IOError(f"Not enough disk space. Only {free_gb:.2f} GB free (minimum 2 GB required).")


def _friendly_error(error_str: str) -> str:
    s = error_str.lower()
    if "sign in to confirm your age" in s or "age-restricted" in s:
        return "🔞 This video is age-restricted and requires a login. The bot cannot download it."
    elif "private video" in s:
        return "🔒 This is a private video. The bot cannot access it."
    elif "members-only" in s:
        return "💎 This is a members-only video. The bot cannot access it."
    return f"Download failed: {error_str}"


UNIVERSAL_DOMAINS = (
    "youtube.com", "youtu.be", "tiktok.com",
    "twitter.com", "x.com", "pinterest.com",
)


class YouTubeExtractor(BaseExtractor):
    priority = 10
    supports_audio = True
    supports_video = True
    supports_batch = False

    def can_handle(self, url: str) -> bool:
        return any(d in url for d in UNIVERSAL_DOMAINS)

    def extract(self, url: str, options: dict = None) -> tuple[dict | None, str | None]:
        """Fetch metadata without downloading. Returns normalized info dict."""
        ydl_opts = {"quiet": True, "no_warnings": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                raw = ydl.extract_info(url, download=False)

            # Normalize output
            info = {
                "title":     raw.get("title", "Unknown Title"),
                "duration":  raw.get("duration", 0) or 0,
                "formats":   raw.get("formats", []),
                "thumbnail": raw.get("thumbnail", ""),
                "platform":  raw.get("extractor_key", "youtube").lower(),
            }
            
            size_estimates = {}
            formats = raw.get("formats", [])
            
            best_audio_size = 0
            for f in formats:
                if f.get("acodec") != "none" and f.get("vcodec") == "none":
                    s = f.get("filesize") or f.get("filesize_approx") or 0
                    if s > best_audio_size: best_audio_size = s

            for height in [1080, 720, 480, 360]:
                best_size = 0
                for f in formats:
                    h = f.get("height")
                    if h and h <= height and f.get("vcodec") != "none":
                        s = f.get("filesize") or f.get("filesize_approx") or 0
                        if not s: continue
                        if f.get("acodec") == "none":
                            s += best_audio_size
                        if s > best_size: best_size = s
                if best_size:
                    size_estimates[f"v_{height}"] = best_size

            m4a_size = 0
            for f in formats:
                if f.get("ext") == "m4a" and f.get("acodec") != "none" and f.get("vcodec") == "none":
                    s = f.get("filesize") or f.get("filesize_approx") or 0
                    if s > m4a_size: m4a_size = s
            if m4a_size:
                size_estimates["a_m4a"] = m4a_size
            if best_audio_size:
                size_estimates["a_mp3"] = best_audio_size
                
            info["size_estimates"] = size_estimates
            
            return info, None
        except Exception as e:
            return None, _friendly_error(str(e))

    def download(
        self,
        url: str,
        options: dict = None,
        target_dir: str = None,
        progress_hook=None,
    ) -> tuple[list[str] | None, str | None]:
        """
        Download to target_dir. options may contain:
          - format_spec: str  (yt-dlp format string)
          - audio_only: bool
        """
        options = options or {}
        format_spec = options.get("format_spec")
        audio_only = options.get("audio_only", False)

        try:
            _check_disk_space()
        except IOError as e:
            return None, str(e)

        if not target_dir:
            target_dir = os.path.join("telegram_bot", "downloads", str(uuid.uuid4()))
        os.makedirs(target_dir, exist_ok=True)

        ydl_opts = {
            "outtmpl": os.path.join(target_dir, "%(title).100s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "socket_timeout": 30,
        }

        if progress_hook:
            ydl_opts["progress_hooks"] = [progress_hook]

        if format_spec:
            ydl_opts["format"] = format_spec
        elif audio_only:
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio"
        else:
            ydl_opts["format"] = "best[ext=mp4]/best"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            paths = []
            for root, _, files in os.walk(target_dir):
                for file in files:
                    paths.append(os.path.abspath(os.path.join(root, file)))

            return (paths, None) if paths else (None, "No files found after download.")

        except yt_dlp.utils.DownloadError as e:
            return None, _friendly_error(str(e))
        except Exception as e:
            return None, str(e)
