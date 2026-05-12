#!/data/data/com.termux/files/usr/bin/sh

# ===============================================
# Unified Insta Bot Management Script
# ===============================================

SESSION_NAME="insta_bot"
BOT_DIR="/data/data/com.termux/files/home/storage/Insta_bot"
MAIN_SCRIPT="$BOT_DIR/telegram_bot/bot.py"
LOG_DIR="$BOT_DIR/logs"
LOG_FILE="$LOG_DIR/bot_runtime.log"

mkdir -p "$LOG_DIR"

start_bot() {
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        echo "Session '$SESSION_NAME' is already running. Use './manage-instabot.sh restart' to force a restart."
        exit 1
    fi
    echo "Starting Insta Bot in new tmux session '$SESSION_NAME'..."
    tmux new-session -d -s "$SESSION_NAME" "
        cd '$BOT_DIR'
        source venv/bin/activate
        while true; do
            echo \"[\$(date)] Bot starting...\" >> \"$LOG_FILE\"
            python \"$MAIN_SCRIPT\" >> \"$LOG_FILE\" 2>&1
            echo \"[\$(date)] Bot crashed or exited. Restarting in 10 seconds...\" >> \"$LOG_FILE\"
            sleep 10
        done
    "
    echo "Bot session created. Use './manage-instabot.sh status' to check it."
}

stop_bot() {
    echo "Attempting to stop bot session '$SESSION_NAME'..."
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null
    echo "Bot session stopped."
}

case "$1" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        sleep 2
        start_bot
        ;;
    status)
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            echo "Bot session '$SESSION_NAME' is RUNNING."
        else
            echo "Bot session '$SESSION_NAME' is STOPPED."
        fi
        ;;
    logs)
        echo "Displaying live logs. Press Ctrl+b then d to detach."
        tmux attach-session -t "$SESSION_NAME"
        ;;
    *)
        echo "Usage: \$0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac

exit 0
