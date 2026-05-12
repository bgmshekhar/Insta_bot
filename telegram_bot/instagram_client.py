import instaloader
import os
import logging

logger = logging.getLogger(__name__)

class InstagramClient:
    def __init__(self):
        # Initialize an anonymous client
        self.L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True # Keep console clean
        )

    def download_video(self, shortcode):
        """Download video anonymously and return the file path."""
        try:
            post = instaloader.Post.from_shortcode(self.L.context, shortcode)
            if not post.is_video:
                return None, "This post is not a video."
            
            # Set download directory
            self.L.dirname_pattern = os.path.join("telegram_bot", "downloads", "{target}")
            
            # Download
            self.L.download_post(post, target=shortcode)
            
            # Find the .mp4 file
            target_dir = os.path.join("telegram_bot", "downloads", shortcode)
            if os.path.exists(target_dir):
                for root, dirs, files in os.walk(target_dir):
                    for file in files:
                        if file.endswith(".mp4"):
                            return [os.path.abspath(os.path.join(root, file))], None
            
            return None, "Video file not found."
        except Exception as e:
            if "401" in str(e) or "Login required" in str(e):
                return None, "Instagram is blocking this video for anonymous users. Try again in a moment."
            return None, str(e)