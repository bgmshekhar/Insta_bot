import yt_dlp
import json

ydl_opts = {'quiet': True, 'no_warnings': True}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info("https://www.youtube.com/watch?v=BaW_jenozKc", download=False)

print(f"Title: {info.get('title')}")
print(f"Duration: {info.get('duration')}s")

# Let's find video formats with audio or common resolutions
# yt-dlp usually has 'format_note' (e.g. '1080p', '720p') and 'ext'
resolutions = {}
audio_formats = []

for f in info.get('formats', []):
    vcodec = f.get('vcodec')
    acodec = f.get('acodec')
    ext = f.get('ext')
    format_note = f.get('format_note', '')
    format_id = f.get('format_id')
    
    if vcodec != 'none' and acodec != 'none':
        # Combined video + audio
        if 'p' in format_note: # e.g. 720p, 1080p
            res = format_note.split('p')[0]
            if res.isdigit():
                res_int = int(res)
                if res_int not in resolutions:
                    resolutions[res_int] = f
    
    if vcodec == 'none' and acodec != 'none':
        # Audio only
        if ext in ['m4a', 'mp3']:
            audio_formats.append(f)

print("\nVideo Formats (Video+Audio combined):")
for res in sorted(resolutions.keys()):
    f = resolutions[res]
    print(f"  {res}p: format_id={f['format_id']}, ext={f['ext']}, size={f.get('filesize')}")

print("\nAudio Formats:")
for f in audio_formats:
    print(f"  {f['ext']}: format_id={f['format_id']}, size={f.get('filesize')}")

# Best video strategy: if no combined formats exist (often true for 1080p+ on YouTube),
# we need to download video+audio and merge. yt-dlp handles 'bestvideo[height<=1080]+bestaudio/best' automatically.
# Let's test if passing such a string works as a format selection.
