# InstaBot - Telegram Media Downloader 🚀

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00a393.svg)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red.svg)
![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-20.0+-blue.svg)

InstaBot is a hybrid, high-performance Telegram bot and file server designed to download media from multiple platforms (Instagram, YouTube, TikTok, X/Twitter, Pinterest) and deliver it directly to users. 

It intelligently handles large files by estimating their sizes in real-time and serving them over a secure, temporary HTTP link instead of hitting Telegram's 50MB upload limits.

---

## 🏗️ Architecture

- **Bot Framework**: `python-telegram-bot` (v20+) running asynchronously.
- **Web Server**: `FastAPI` powered by `uvicorn` running in the *same event loop* as the Telegram bot.
- **Tunneling**: Exposes the local FastAPI server to the internet using a persistent Cloudflare Tunnel.
- **Plugin Architecture**: A modular extractor system (`extractors/`) seamlessly routes URLs to the correct handler based on priority.
  - `yt-dlp` (for YouTube, TikTok, X, Pinterest, and general media)
  - `instaloader` (specifically tuned for Instagram reels/posts)
- **Database**: `aiosqlite` powered SQLite database (`bot_data.db`) for robust user authentication, lazy rate-limiting, and analytics.
- **Deployment Host**: A local Android device running **Termux**, utilizing `tmux` for background process management.

---

## ✨ Key Features

1. **Universal Downloading**: Just paste a link. The bot auto-detects the platform and extracts the media.
2. **Elite Quality Selector**: For YouTube and other supported platforms, the bot provides an inline keyboard to select the exact resolution (1080p, 720p, etc.) or audio format (M4A, MP3).
3. **Proactive Size Estimation & Smart Delivery**:
   - The bot parses metadata before downloading to accurately estimate file sizes.
   - Files **<= 45MB** are uploaded natively to Telegram.
   - Files **> 45MB** completely bypass the Telegram upload attempt. They are moved to a secure, UUID-named folder and served via a temporary download link with range-request (resumable) support.
4. **Secure One-Time Token Links**: Direct download links are tracked in memory. If a link expires (default 15 minutes) or is tampered with, the FastAPI server strictly rejects the request with a 404 error before hitting the disk.
5. **Smart Auto-Cleanup (The Reaper)**: A background asynchronous task that runs every 5 minutes, scanning the `downloads/` directory. It safely deletes files older than the TTL. It is context-aware and actively skips:
   - Directories currently being downloaded into by `yt-dlp`.
   - Files actively being streamed to a user's browser/download manager.
6. **Crash-Proofing & Safety**: 
   - Intelligently catches `yt-dlp` errors for age-restricted, members-only, or private videos and sends a clean warning to the user.
   - A hard safety check prevents downloads from starting if the server has less than **2 GB** of free disk space.

---

## 👑 Advanced Admin Suite

The bot features a highly secure SQLite authentication system. A root `ADMIN_ID` is hardcoded to ensure the owner always has access, bypassing any file corruption or `.env` issues.

**Admin Security & UI Scoping:**
- **Dynamic Help Menu**: The `/help` and `/start` commands feature a professional ASCII UI. The admin commands section is automatically injected *only* for the root admin or authorized admin IDs.
- **Command Menu Scoping**: Regular users only see a clean, 3-item command menu (`/start`, `/help`, `/audio`). Admin-level commands are programmatically restricted to the Admin's private chat, ensuring zero clutter for end-users.

**Admin Commands:**
- `/allow <id>` - Grants a user permission to use the bot (Stored in `bot_data.db`).
- `/revoke <id>` - Removes a user's permission.
- `/stats` - Displays critical server health: Free Disk Space (GB), Queue Status, Cache Hit Rates, and Analytics breakdowns.
- `/users` - Prints a list of all currently authorized Telegram IDs.
- `/broadcast <message>` - Sends a direct message to every authorized user from the bot.

---

## 🚀 Deployment & Management

The project uses a custom deployment pipeline designed for seamless updates from a Windows PC to the Android Termux server.

- **`deploy.ps1` (Windows)**: Pushes the local Python files and `.env` over SSH to the Termux device, updates pip dependencies, runs database migrations, and cleanly restarts the bot and the Cloudflare tunnel.
- **`manage-instabot.sh` (Termux)**: A shell script that manages the bot's lifecycle. It ensures the bot runs persistently inside a `tmux` session named `insta_bot`.
  - Usage: `./manage-instabot.sh [start|stop|restart|status|logs]`

---

## 📁 Directory Structure

```text
Insta_bot/
│
├── telegram_bot/
│   ├── bot.py                # Main entry point: Telegram handlers & hybrid runner
│   ├── database.py           # SQLite connection and auth/analytics functions
│   ├── file_server.py        # FastAPI server & the background Reaper task
│   ├── extractors/           # Modular plugin architecture
│   │   ├── manager.py        # PluginManager for routing URLs
│   │   ├── base.py           # Abstract BaseExtractor class
│   │   ├── youtube.py        # yt-dlp integration
│   │   └── instagram.py      # instaloader integration
│   ├── scripts/              # Migration/utility scripts
│   ├── requirements.txt      # Python dependencies
│   └── downloads/            # Temporary directory for large files
│
├── manage-instabot.sh        # Termux lifecycle manager (tmux)
├── .env                      # Environment variables (Tokens, IDs)
└── README.md                 # This documentation file
```