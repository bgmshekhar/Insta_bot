#!/usr/bin/env bash
# Universal Setup Script for InstaBot 🚀
# Supports: Linux, macOS, Termux, and Windows (via Git Bash / WSL)

set -e

echo "=================================================="
echo "      🚀 InstaBot Universal Setup Script 🚀       "
echo "=================================================="

# 1. Check Python installation
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Error: Python 3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✅ Found Python version $PYTHON_VERSION"

# 2. Check for ffmpeg (Required for yt-dlp)
if ! command -v ffmpeg &>/dev/null; then
    echo "⚠️  Warning: 'ffmpeg' is not installed."
    echo "   yt-dlp requires ffmpeg to merge high-quality video and audio tracks."
    echo "   Please install it via your package manager (apt, brew, pkg, choco, etc)."
else
    echo "✅ Found ffmpeg"
fi

# 3. Setup Virtual Environment
echo ""
echo "📦 Setting up Python Virtual Environment..."
if [ ! -d "venv" ]; then
    $PYTHON_CMD -m venv venv
    echo "✅ Virtual environment created in ./venv"
else
    echo "✅ Virtual environment already exists."
fi

# Activate venv based on OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    # Windows Git Bash
    source venv/Scripts/activate
else
    # Unix / Termux
    source venv/bin/activate
fi

# 4. Install Dependencies
echo "📥 Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r telegram_bot/requirements.txt
echo "✅ Dependencies installed successfully."

# 5. Environment Variables (.env)
echo ""
echo "⚙️  Configuring Environment Variables..."
if [ ! -f ".env" ]; then
    read -p "Enter your Telegram Bot Token: " BOT_TOKEN
    read -p "Enter your Admin Telegram ID (e.g. 123456789): " ADMIN_ID
    
    # Default Base URL for local testing
    BASE_URL="http://127.0.0.1:8500"

    cat <<EOF > .env
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
ROOT_ADMIN_ID=$ADMIN_ID
BASE_URL=$BASE_URL
MAX_CONCURRENT_JOBS=2
MAX_QUEUE_SIZE=50
MAX_DL_PER_HOUR=20
DOWNLOAD_TIMEOUT=900
EOF
    echo "✅ .env file generated successfully."
else
    echo "✅ .env file already exists. Skipping configuration."
fi

# 6. Final Instructions
echo ""
echo "=================================================="
echo "🎉 Setup Complete! 🎉"
echo "=================================================="
echo ""
echo "To start the bot, run the following commands:"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    echo "  source venv/Scripts/activate"
else
    echo "  source venv/bin/activate"
fi
echo "  python telegram_bot/bot.py"
echo ""
echo "🌐 Note: If you want direct download links to work over the internet,"
echo "you must expose port 8500 using a tool like Cloudflare Tunnels (cloudflared)"
echo "or ngrok, and update BASE_URL in your .env file."
echo "=================================================="
