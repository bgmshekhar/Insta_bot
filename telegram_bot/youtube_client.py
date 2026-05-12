import os
import uuid
import shutil
import yt_dlp

# ── Disk Safety ───────────────────────────────────────────────────────────────
MIN_FREE_SPACE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB hard minimum

def _check_disk_space(path: str = "."):
    """Raise an error if less than 2 GB of disk space is available."""
    stat = shutil.disk_usage(path)
    if stat.free < MIN_FREE_SPACE_BYTES:
        free_gb = stat.free / (1024 ** 3)
        raise IOError(
            f"Not enough disk space. Only {free_gb:.2f} GB free (minimum 2 GB required)."
        )


class YouTubeClient:
    def get_video_info(self, url):
        """Fetch metadata without downloading."""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info, None
        except Exception as e:
            error_str = str(e).lower()
            if "sign in to confirm your age" in error_str or "age-restricted" in error_str:
                return None, "🔞 This video is age-restricted and requires a login. The bot cannot download it."
            elif "private video" in error_str:
                return None, "🔒 This is a private video. The bot cannot access it."
            elif "members-only" in error_str:
                return None, "💎 This is a members-only video. The bot cannot access it."
            return None, f"Error: {str(e)}"

    def download_video(self, url, format_spec=None, audio_only=False):
        """Download video/audio and return (list_of_paths, error_string)."""
        # Hard disk space guard — 2 GB minimum regardless of file size
        try:
            _check_disk_space()
        except IOError as e:
            return None, str(e)

        target_dir = os.path.join("telegram_bot", "downloads", str(uuid.uuid4()))
        os.makedirs(target_dir, exist_ok=True)

        ydl_opts = {
            'outtmpl': os.path.join(target_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            # No max_filesize cap — we handle large files via the file server
        }

        if format_spec:
            ydl_opts['format'] = format_spec
        elif audio_only:
            # Prioritize m4a — Telegram handles it natively as audio
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
        else:
            # Prefer pre-merged MP4 to avoid needing ffmpeg for muxing
            ydl_opts['format'] = 'best[ext=mp4]/best'

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            # Collect all downloaded files
            paths = []
            if os.path.exists(target_dir):
                for root, _, files in os.walk(target_dir):
                    for file in files:
                        paths.append(os.path.abspath(os.path.join(root, file)))

            if paths:
                return paths, None

            return None, "Video file(s) not found after download."

        except yt_dlp.utils.DownloadError as e:
            error_str = str(e).lower()
            if "sign in to confirm your age" in error_str or "age-restricted" in error_str:
                return None, "🔞 This video is age-restricted and requires a login. The bot cannot download it."
            elif "private video" in error_str:
                return None, "🔒 This is a private video. The bot cannot access it."
            elif "members-only" in error_str:
                return None, "💎 This is a members-only video. The bot cannot access it."
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            return None, str(e)
