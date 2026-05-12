from telegram_bot.instagram_client import InstagramClient
import os

def test_download():
    client = InstagramClient()
    # Using the shortcode from your logs
    shortcode = "DS1VP1Lknvx"
    print(f"Testing download for shortcode: {shortcode}")
    
    video_path, error = client.download_video(shortcode)
    
    if error:
        print(f"FAILED: {error}")
    else:
        print(f"SUCCESS: Video downloaded to {video_path}")
        if os.path.exists(video_path):
            print(f"File size: {os.path.getsize(video_path) / (1024*1024):.2f} MB")
        else:
            print("File not found on disk!")

if __name__ == "__main__":
    test_download()
