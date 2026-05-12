<div align="center">
  <h1>🚀 InstaBot - Universal Media Downloader</h1>
  <p>A hybrid, high-performance Telegram Bot & File Server to download media from Instagram, YouTube, TikTok, X (Twitter), and Pinterest.</p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/FastAPI-0.100+-00a393.svg" alt="FastAPI">
    <img src="https://img.shields.io/badge/yt--dlp-latest-red.svg" alt="yt-dlp">
    <img src="https://img.shields.io/badge/python--telegram--bot-20.0+-blue.svg" alt="PTB">
    <img src="https://img.shields.io/github/license/bgmshekhar/Insta_bot" alt="License">
  </p>
</div>

---

## 📑 Table of Contents
- [✨ Features](#-features)
- [🏗️ Architecture](#️-architecture)
- [⚙️ Prerequisites](#️-prerequisites)
- [⚡ Quick Start (Installation)](#-quick-start-installation)
- [🛠️ Configuration (.env)](#️-configuration-env)
- [👑 Admin Suite & Commands](#-admin-suite--commands)
- [🧹 The Reaper (Auto-Cleanup)](#-the-reaper-auto-cleanup)
- [🚀 Deployment on Termux](#-deployment-on-termux)
- [🤝 Contributing](#-contributing)

---

## ✨ Features

- **🌐 Universal Downloading**: Paste a link, and the bot auto-detects the platform.
- **🎛️ Elite Quality Selector**: Inline keyboard to select exact video resolutions (1080p, 720p, etc.) or audio formats (M4A, MP3).
- **🧠 Proactive Size Estimation**: The bot parses metadata before downloading to accurately estimate file sizes.
- **⚡ Smart Delivery System**:
  - Files **<= 45MB** are uploaded natively to Telegram.
  - Files **> 45MB** completely bypass the Telegram upload limits. They are securely hosted on the internal FastAPI server and delivered via a resumable HTTP download link.
- **🔐 Secure One-Time Token Links**: Direct download links use UUIDs and are tracked in memory. Links expire automatically (default: 15 mins), and tampered links return a strict 404 error.
- **🛡️ Crash-Proofing**: Intelligently handles `yt-dlp` exceptions (e.g., age-restricted, members-only) and sends a clean warning to the user. Hard safety checks prevent downloads if server disk space falls below **2 GB**.

---

## 🏗️ Architecture

- **Bot Framework**: `python-telegram-bot` (v20+) running asynchronously.
- **Web Server**: `FastAPI` powered by `uvicorn` running in the *same event loop* as the Telegram bot.
- **Plugin Architecture**: A modular extractor system (`extractors/`) routing URLs seamlessly:
  - `yt-dlp`: For YouTube, TikTok, X, Pinterest, etc.
  - `instaloader`: Specifically tuned for Instagram Reels and Posts.
- **Database**: `aiosqlite` powered SQLite database (`bot_data.db`) for robust user authentication, lazy rate-limiting, and analytics tracking.

---

## ⚙️ Prerequisites

Before installing, ensure your system has:
1. **Python 3.10+** installed.
2. **FFmpeg**: Required by `yt-dlp` to merge high-quality video and audio tracks.
   - *Ubuntu/Debian*: `sudo apt install ffmpeg`
   - *macOS*: `brew install ffmpeg`
   - *Windows*: `winget install ffmpeg` or download from the official site.
   - *Termux*: `pkg install ffmpeg`
3. A **Telegram Bot Token** (from [@BotFather](https://t.me/botfather)).

---

## ⚡ Quick Start (Installation)

We provide a universal setup script that automatically checks your Python version, installs requirements, sets up a virtual environment, and securely configures your `.env` file across **Windows (Git Bash/WSL), Linux, macOS, and Termux**.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/bgmshekhar/Insta_bot.git
   cd Insta_bot
   ```

2. **Run the setup script:**
   ```bash
   bash setup.sh
   ```

3. **Start the bot:**
   ```bash
   # On Linux / macOS / Termux
   source venv/bin/activate
   python telegram_bot/bot.py

   # On Windows (Git Bash)
   source venv/Scripts/activate
   python telegram_bot/bot.py
   ```

---

## 🛠️ Configuration (.env)

If you didn't use `setup.sh`, you can manually create a `.env` file in the root directory:

```ini
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_ID=your_telegram_id_here
ROOT_ADMIN_ID=your_telegram_id_here
# If hosting publicly, use your domain/tunnel url (e.g., https://bot.yourdomain.com)
BASE_URL=http://127.0.0.1:8500 
MAX_CONCURRENT_JOBS=2
MAX_QUEUE_SIZE=50
MAX_DL_PER_HOUR=20
DOWNLOAD_TIMEOUT=900
```

> **Note on `BASE_URL`**: If you want direct download links (for files > 45MB) to work over the internet, you must expose port `8500` using a tool like **Cloudflare Tunnels (cloudflared)** or **ngrok**, and update the `BASE_URL` to match your tunnel address.

---

## 👑 Admin Suite & Commands

The bot features a highly secure SQLite authentication system. The `ROOT_ADMIN_ID` ensures the owner always has full access. Admin commands are scoped directly to the Admin's private chat, ensuring zero clutter for end-users.

**User Commands:**
- `/start` - Displays the welcome UI.
- `/help` - Shows help and usage instructions.

**Admin Commands:**
- `/allow <id>` - Grants a user permission to use the bot.
- `/revoke <id>` - Removes a user's permission.
- `/stats` - Displays critical server health: Free Disk Space (GB), Queue Status, Cache Hit Rates, and Analytics.
- `/users` - Prints a list of all currently authorized Telegram IDs.
- `/broadcast <message>` - Sends a direct message to every authorized user.

---

## 🧹 The Reaper (Auto-Cleanup)

To protect your server's disk space, the bot includes an asynchronous background task called **The Reaper**. 
- Runs every **5 minutes**.
- Scans the `downloads/` directory and permanently deletes files older than `DOWNLOAD_TIMEOUT` (default 15 minutes).
- **Context-Aware Safety**: The Reaper actively monitors active tasks. It will *never* delete a directory currently being written to by `yt-dlp`, nor will it delete a file that is actively being streamed to a user's browser, preventing corruption.

---

## 🚀 Deployment on Termux

If deploying to an Android device using Termux, the repository includes a custom shell script to manage the bot persistently using `tmux`.

```bash
# Make the script executable
chmod +x manage-instabot.sh

# Start the bot in the background
./manage-instabot.sh start

# Check status
./manage-instabot.sh status

# View live logs
./manage-instabot.sh logs

# Stop the bot
./manage-instabot.sh stop
```

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! 
Feel free to check the [issues page](https://github.com/bgmshekhar/Insta_bot/issues). If you want to contribute, please fork the repository and submit a pull request.

<div align="center">
  <i>Made with ❤️ by the Open Source Community</i>
</div>
