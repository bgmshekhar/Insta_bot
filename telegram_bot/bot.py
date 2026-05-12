"""
bot.py — InstaBot v2.0
Phases: DB Auth, Plugin Architecture, Smart Queue, Premium UI State Machine.
"""
import logging
import os
import asyncio
import shutil
import uuid
import re
import time
import dataclasses
from pathlib import Path
from dotenv import load_dotenv
from telegram import (
    Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommandScopeDefault, BotCommandScopeChat
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
import uvicorn

from database import (
    init_db, is_user_allowed, allow_user, revoke_user,
    get_all_users, check_and_increment_rate, record_download,
    get_analytics_summary, make_cache_key, get_cache, set_cache
)
from extractors import PluginManager
from file_server import app as fastapi_app, register_token, active_download_dirs

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL           = os.getenv("BASE_URL", "https://bot.csydev.online")
FILE_SIZE_THRESHOLD = 50 * 1024 * 1024
_BOT_DIR           = Path(__file__).parent          # telegram_bot/
DOWNLOADS_DIR      = _BOT_DIR / "downloads"
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
MAX_QUEUE_SIZE      = int(os.getenv("MAX_QUEUE_SIZE", "50"))
ROOT_ADMIN          = int(os.getenv("ROOT_ADMIN_ID", "1000808626"))
TIMEOUT_MINUTES     = int(os.getenv("DOWNLOAD_TIMEOUT", "900")) // 60

# ── Global state ──────────────────────────────────────────────────────────────
plugin_manager = PluginManager()
download_queue: asyncio.Queue = None          # initialized in main()
active_locks: dict[str, asyncio.Lock] = {}   # cache key → lock
URL_CACHE: dict[str, any] = {}               # inline keyboard cache

# ── Job State Machine ─────────────────────────────────────────────────────────
class JobState:
    QUEUED      = "⏳ In queue"
    FETCHING    = "🔍 Fetching info..."
    DOWNLOADING = "📥 Downloading"
    PROCESSING  = "⚙️ Processing..."
    UPLOADING   = "🚀 Uploading..."
    DONE        = "✅ Done"
    FAILED      = "❌ Failed"


@dataclasses.dataclass
class DownloadJob:
    id:         str
    user_id:    int
    url:        str
    format_spec: str | None
    audio_only: bool
    message:    object   # telegram Message object for replies
    status_msg: object   # telegram Message object to edit
    state:      str = JobState.QUEUED
    progress:   int = 0  # 0–100
    platform:   str = "unknown"
    media_type: str = "video"
    estimated_size: int | None = None


# ── Auth ──────────────────────────────────────────────────────────────────────
async def check_auth(update: Update) -> bool:
    uid = update.effective_user.id
    if uid == ROOT_ADMIN:
        return True
    if await is_user_allowed(uid):
        return True

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Request Access", callback_data=f"req_access|{uid}")]
    ])
    text = f"❌ *You are not authorized.*"
    
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        
    return False


def is_admin(uid: int) -> bool:
    admin_id = int(os.getenv("ADMIN_ID", str(ROOT_ADMIN)))
    return uid in (ROOT_ADMIN, admin_id)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _generate_download_link(file_path: str) -> tuple[str, Path]:
    token    = str(uuid.uuid4())
    dest_dir = DOWNLOADS_DIR / token
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest     = dest_dir / Path(file_path).name
    shutil.move(file_path, dest)
    dest_dir.touch()
    register_token(token)
    return f"{BASE_URL}/dl/{token}", dest_dir


async def _safe_edit(msg, text: str):
    """Edit message text, silently ignoring Telegram rate-limit errors."""
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        pass


PROGRESS_BAR_LEN = 10
def _bar(pct: int) -> str:
    filled = int(pct / 100 * PROGRESS_BAR_LEN)
    return "█" * filled + "░" * (PROGRESS_BAR_LEN - filled)


async def _send_or_link(message, paths: list[str], media_type: str, job: DownloadJob):
    temp_dirs = set()
    try:
        for path in paths:
            if not os.path.exists(path):
                logger.error(f"File not found during send: {path}")
                continue

            size = os.path.getsize(path)
            temp_dirs.add(os.path.dirname(path))

            if size <= FILE_SIZE_THRESHOLD:
                await _safe_edit(job.status_msg, f"*{JobState.UPLOADING}*")
                with open(path, "rb") as f:
                    if media_type == "video":
                        await message.reply_video(video=f, caption="🎥 Here you go!", read_timeout=180, write_timeout=180, connect_timeout=120)
                    else:
                        await message.reply_audio(audio=f, caption="🎵 Audio extracted!", read_timeout=180, write_timeout=180, connect_timeout=120)
            else:
                link, _ = _generate_download_link(path)
                size_mb = size / (1024 * 1024)
                await message.reply_text(
                    f"📦 *File ready!* ({size_mb:.1f} MB)\n\n"
                    f"⬇️ [Download Link]({link})\n\n"
                    f"⏳ Expires in *{TIMEOUT_MINUTES} min*. Supports resume.",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            await asyncio.sleep(0.5)
    finally:
        # Cleanup all temp directories after sending ALL files
        for d in temp_dirs:
            try:
                shutil.rmtree(d)
                # Also try to remove the parent UUID dir if it's empty
                parent = os.path.dirname(d)
                if os.path.basename(parent) != "downloads" and os.path.exists(parent):
                    if not os.listdir(parent):
                        os.rmdir(parent)
            except Exception as e:
                logger.warning(f"Cleanup failed for {d}: {e}")


# ── Worker Pool ───────────────────────────────────────────────────────────────
async def _worker(worker_id: int):
    logger.info(f"Worker-{worker_id} started.")
    while True:
        job: DownloadJob = await download_queue.get()
        try:
            await _process_job(job)
        except Exception as e:
            logger.exception(f"Worker-{worker_id} unhandled error: {e}")
            try:
                await _safe_edit(job.status_msg, f"❌ Unexpected error: {e}")
            except Exception:
                pass
        finally:
            download_queue.task_done()


async def _process_job(job: DownloadJob):
    start_time = time.monotonic()
    cache_hit  = False
    fsize_mb   = 0.0

    logger.info(f"[Job {job.id}] Starting processing for User {job.user_id} on {job.platform} | URL: {job.url}")

    # --- FETCHING state ---
    await _safe_edit(job.status_msg, f"*{JobState.FETCHING}*")

    extractor = plugin_manager.get_extractor(job.url)
    if not extractor:
        logger.warning(f"[Job {job.id}] Unsupported URL submitted: {job.url}")
        await _safe_edit(job.status_msg, "❌ Unsupported URL.")
        return

    job.platform = extractor.name

    # --- Cache check ---
    cache_key = make_cache_key(job.url, job.format_spec or ("audio" if job.audio_only else "video"))
    lock = active_locks.setdefault(cache_key, asyncio.Lock())

    async with lock:
        cached = await get_cache(cache_key)
        if cached and os.path.exists(cached["file_path"]):
            cache_hit = True
            elapsed = time.monotonic() - start_time
            logger.info(f"[Job {job.id}] Cache hit! Serving existing file: {cached['file_path']} to User {job.user_id}")
            await _safe_edit(job.status_msg, f"⚡ *Cache hit!* Sending instantly...")
            await _send_or_link(job.message, [cached["file_path"]], job.media_type, job)
            await record_download(job.user_id, job.platform, cached["file_size_mb"], elapsed, cache_hit=True)
            await _safe_edit(job.status_msg, f"*{JobState.DONE}*")
            await asyncio.sleep(2)
            try: await job.status_msg.delete()
            except Exception: pass
            return

        # --- DOWNLOADING state ---
        loop = asyncio.get_event_loop()
        last_edit  = [0.0]
        last_pct   = [-1]

        def progress_hook(d):
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if not total:
                return
            pct = int(downloaded / total * 100)
            now = time.monotonic()
            if pct - last_pct[0] >= 5 and now - last_edit[0] >= 4:
                last_pct[0] = pct
                last_edit[0] = now
                asyncio.run_coroutine_threadsafe(
                    _safe_edit(job.status_msg, f"📥 *Downloading...*\n`[{_bar(pct)}] {pct}%`"),
                    loop
                )

        logger.info(f"[Job {job.id}] Downloading remote resource from {job.url} (format: {job.format_spec}, audio_only: {job.audio_only})")
        await _safe_edit(job.status_msg, f"📥 *Downloading...*\n`[{_bar(0)}] 0%`")

        target_dl_uuid = str(uuid.uuid4())
        target_dl_dir = str(DOWNLOADS_DIR / target_dl_uuid)
        
        is_downloading = [True]
        async def _monitor():
            while is_downloading[0]:
                await asyncio.sleep(60)
                if is_downloading[0] and (time.monotonic() - last_edit[0] >= 60):
                    pct = last_pct[0] if last_pct[0] >= 0 else 0
                    await _safe_edit(
                        job.status_msg, 
                        f"⏳ *Still working...* large video may take several minutes.\n`[{_bar(pct)}] {pct}%` — Processing, please wait."
                    )
                    last_edit[0] = time.monotonic()
        
        monitor_task = asyncio.create_task(_monitor())
        active_download_dirs.add(target_dl_uuid)

        try:
            paths, error = await loop.run_in_executor(
                None,
                lambda: extractor.download(
                    job.url,
                    options={"format_spec": job.format_spec, "audio_only": job.audio_only},
                    target_dir=target_dl_dir,
                    **({"progress_hook": progress_hook} if hasattr(extractor.download, "__code__") and "progress_hook" in extractor.download.__code__.co_varnames else {})
                )
            )
        finally:
            is_downloading[0] = False
            monitor_task.cancel()
            active_download_dirs.discard(target_dl_uuid)

        if error:
            logger.error(f"[Job {job.id}] Download failed. URL: {job.url} | Error: {error}")
            await _safe_edit(job.status_msg, f"❌ {error}")
            await record_download(job.user_id, job.platform, 0, time.monotonic() - start_time, status="failed")
            return

        logger.info(f"[Job {job.id}] Download finished. Downloaded files: {paths}")

        # --- PROCESSING state ---
        await _safe_edit(job.status_msg, f"*{JobState.PROCESSING}*")

        # Cache the result (first file only for simplicity)
        if paths:
            fsize_mb = os.path.getsize(paths[0]) / (1024 * 1024)
            await set_cache(cache_key, paths[0], fsize_mb)

        # --- UPLOADING state (handled inside _send_or_link) ---
        await _send_or_link(job.message, paths, job.media_type, job)

    elapsed   = time.monotonic() - start_time
    logger.info(f"[Job {job.id}] Job completed successfully. File Size: {fsize_mb:.2f} MB, Time Taken: {elapsed:.2f}s | User: {job.user_id}")
    await record_download(job.user_id, job.platform, fsize_mb, elapsed, cache_hit=False)

    await _safe_edit(job.status_msg, f"*{JobState.DONE}*")
    await asyncio.sleep(2)
    try: await job.status_msg.delete()
    except Exception: pass


# ── Enqueue Helper ────────────────────────────────────────────────────────────
async def _enqueue(
    update: Update, url: str,
    format_spec: str = None, audio_only: bool = False,
    media_type: str = "video", queue_msg=None,
    estimated_size: int | None = None
) -> bool:
    """Check limits and enqueue a job. Returns True if queued."""
    uid = update.effective_user.id
    logger.info(f"Enqueue request from User {uid} | URL: {url} | format_spec: {format_spec} | audio_only: {audio_only}")

    # Rate limit (admins bypass)
    if not is_admin(uid):
        allowed, count = await check_and_increment_rate(uid)
        if not allowed:
            await update.message.reply_text(
                f"⛔ *Rate limit reached!*\nYou've hit the `{os.getenv('MAX_DL_PER_HOUR', '10')} downloads/hour` cap.\nTry again later.",
                parse_mode="Markdown"
            )
            return False

    # Backpressure
    if download_queue.qsize() >= MAX_QUEUE_SIZE:
        await update.message.reply_text("🚫 *Queue is full!* The server is very busy. Please try again in a few minutes.", parse_mode="Markdown")
        return False

    pos = download_queue.qsize() + 1
    status_msg = queue_msg or await update.message.reply_text(
        f"*{JobState.QUEUED}*\n📍 Position: `{pos}` in queue" if pos > 1 else f"*{JobState.QUEUED}*\n⚡ Starting shortly...",
        parse_mode="Markdown"
    )

    job = DownloadJob(
        id=str(uuid.uuid4())[:8],
        user_id=uid,
        url=url,
        format_spec=format_spec,
        audio_only=audio_only,
        message=update.message,
        status_msg=status_msg,
        platform=plugin_manager.detect_platform(url),
        media_type=media_type,
        estimated_size=estimated_size,
    )
    await download_queue.put(job)
    return True


# ── Command Handlers ──────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    uid = update.effective_user.id
    msg = (
        "⚡️ *QUICK START GUIDE* ⚡️\n\n"
        "      `(̅_̅_̅_̅(̅_̅_̅_̅_̅_̅_̅_̅_̅_̅()`\n\n"
        "  ● *INSTAGRAM* - Reels & Posts\n"
        "  ● *YOUTUBE*   - 4K/HD Support\n\n"
        "*INSTRUCTIONS:*\n"
        "Just send the link! For files over 50MB, we provide a "
        "secure 15-minute download link that supports resuming.\n\n"
        "📌 `/help` - Show this guide\n"
        "🎵 `/audio <link>` - Extract MP3/M4A"
    )
    if is_admin(uid):
        msg += (
            "\n\n👑 *ADMIN COMMANDS*\n"
            "───────────────────\n"
            "📊 `/stats` - Server health & analytics\n"
            "👥 `/users` - List authorized users\n"
            "✅ `/allow <id>` - Authorize user\n"
            "⛔ `/revoke <id>` - Revoke user\n"
            "📢 `/broadcast <msg>` - Message all users"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def handle_audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/audio <link>`", parse_mode="Markdown")
        return
    url = context.args[0]
    extractor = plugin_manager.get_extractor(url)
    if not extractor:
        await update.message.reply_text("❌ Unsupported URL.")
        return
    await _enqueue(update, url, audio_only=True, media_type="audio")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    text = update.message.text or ""
    logger.info(f"Received message from User {update.effective_user.id} ({update.effective_user.username or ''}): {text}")
    urls = re.findall(r'https?://[^\s]+', text)
    if not urls:
        return

    supported = [u for u in urls if plugin_manager.get_extractor(u)]
    if not supported:
        return

    if len(supported) > 1:
        await update.message.reply_text(
            f"📦 *Batch detected: {len(supported)} links*\n⚙️ Adding to queue...",
            parse_mode="Markdown"
        )

    for url in supported:
        extractor = plugin_manager.get_extractor(url)
        if not extractor:
            continue

        # Instagram: download directly (no format selection)
        if extractor.name == "instagram":
            await _enqueue(update, url, media_type="video")
            continue

        # YouTube/Universal: fetch info and show quality keyboard
        status_msg = await update.message.reply_text("🔍 *Fetching info...*", parse_mode="Markdown")
        loop = asyncio.get_event_loop()
        info, error = await loop.run_in_executor(None, extractor.extract, url)

        if error or not info:
            await status_msg.edit_text(f"❌ Error: {error}")
            continue

        title    = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        mins, secs = divmod(duration, 60)

        cache_id = str(uuid.uuid4())[:8]
        URL_CACHE[cache_id] = {
            "url": url,
            "sizes": info.get("size_estimates", {})
        }

        keyboard = [
            [InlineKeyboardButton("🎞 1080p", callback_data=f"dl|{cache_id}|v_1080"),
             InlineKeyboardButton("🎞 720p",  callback_data=f"dl|{cache_id}|v_720")],
            [InlineKeyboardButton("🎞 480p",  callback_data=f"dl|{cache_id}|v_480"),
             InlineKeyboardButton("🎞 360p",  callback_data=f"dl|{cache_id}|v_360")],
            [InlineKeyboardButton("🎵 M4A",   callback_data=f"dl|{cache_id}|a_m4a"),
             InlineKeyboardButton("🎵 MP3",   callback_data=f"dl|{cache_id}|a_mp3")],
        ]
        await status_msg.edit_text(
            f"🎥 *{title}*\n⏱ `{mins:02d}:{secs:02d}`\n\n*Choose format:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    if not parts:
        return

    action = parts[0]

    if action == "req_access":
        if len(parts) < 2:
            return
        target_uid = int(parts[1])
        
        username = query.from_user.username or "No Username"
        first_name = query.from_user.first_name or ""
        last_name = query.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip() or "No Name"
        
        logger.info(f"User {target_uid} ({full_name} | @{username}) clicked 'Request Access'")
        
        # Notify Admin
        admin_msg = (
            f"🔔 *New Access Request!*\n\n"
            f"👤 *User:* {full_name} (@{username})\n"
            f"🆔 *ID:* `{target_uid}`\n"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"auth_appr|{target_uid}|{username}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"auth_deny|{target_uid}|{username}")
            ]
        ])
        try:
            await context.bot.send_message(chat_id=ROOT_ADMIN, text=admin_msg, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send request message to admin {ROOT_ADMIN}: {e}")
            
        await query.edit_message_text("⏳ *Request sent!* Admin has been notified. You will receive a message once approved.", parse_mode="Markdown")
        return

    elif action == "auth_appr":
        if len(parts) < 3:
            return
        target_uid = int(parts[1])
        target_username = parts[2]
        
        # Security: Only Admin can click this!
        admin_uid = query.from_user.id
        if not is_admin(admin_uid):
            await query.answer("❌ You are not authorized to perform this action.", show_alert=True)
            return
            
        # Grant permission
        await allow_user(target_uid)
        logger.info(f"Admin {admin_uid} APPROVED access for User {target_uid} (@{target_username})")
        
        # Update Admin Message
        await query.edit_message_text(f"🟢 *Approved!*\n👤 User: @{target_username} (ID: `{target_uid}`) has been granted access.", parse_mode="Markdown")
        
        # Notify User
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text="🎉 *Your access request has been approved!*\nYou can now send YouTube or Instagram links to download.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_uid} of approval: {e}")
        return

    elif action == "auth_deny":
        if len(parts) < 3:
            return
        target_uid = int(parts[1])
        target_username = parts[2]
        
        # Security: Only Admin can click this!
        admin_uid = query.from_user.id
        if not is_admin(admin_uid):
            await query.answer("❌ You are not authorized to perform this action.", show_alert=True)
            return
            
        logger.info(f"Admin {admin_uid} DENIED access for User {target_uid} (@{target_username})")
        
        # Update Admin Message
        await query.edit_message_text(f"🔴 *Denied!*\n👤 User: @{target_username} (ID: `{target_uid}`) request was rejected.", parse_mode="Markdown")
        
        # Notify User
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text="❌ *Your access request has been denied.*",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_uid} of rejection: {e}")
        return

    elif action == "dl":
        if len(parts) != 3:
            return

        _, cache_id, fmt = parts
        cache_data = URL_CACHE.get(cache_id)
        if not cache_data:
            await query.edit_message_text("❌ Session expired. Please send the link again.")
            return

        if isinstance(cache_data, str):
            url = cache_data
            estimated_size = None
        else:
            url = cache_data.get("url")
            estimated_size = cache_data.get("sizes", {}).get(fmt)

        FORMATS = {
            "v_1080": ("bestvideo[height<=1080]+bestaudio/best", "video"),
            "v_720":  ("bestvideo[height<=720]+bestaudio/best",  "video"),
            "v_480":  ("bestvideo[height<=480]+bestaudio/best",  "video"),
            "v_360":  ("bestvideo[height<=360]+bestaudio/best",  "video"),
            "a_m4a":  ("bestaudio[ext=m4a]/bestaudio",           "audio"),
            "a_mp3":  ("bestaudio/best",                         "audio"),
        }
        if fmt not in FORMATS:
            return

        format_spec, media_type = FORMATS[fmt]
        audio_only = media_type == "audio"
        uid = query.from_user.id
        logger.info(f"Callback query from User {uid} | Selection: {fmt} | Format: {format_spec} | URL: {url}")

        await query.edit_message_text(f"*{JobState.QUEUED}*\n⚡ Starting shortly...", parse_mode="Markdown")
        # Rate limit check for callbacks too
        if not is_admin(uid):
            allowed, _ = await check_and_increment_rate(uid)
            if not allowed:
                await query.edit_message_text("⛔ *Rate limit reached!* Try again later.", parse_mode="Markdown")
                return

        if download_queue.qsize() >= MAX_QUEUE_SIZE:
            await query.edit_message_text("🚫 *Queue is full!* Please try again in a few minutes.", parse_mode="Markdown")
            return

        class _FakeUpdate:
            effective_user = query.from_user
            message        = query.message

        job = DownloadJob(
            id=str(uuid.uuid4())[:8],
            user_id=uid,
            url=url,
            format_spec=format_spec,
            audio_only=audio_only,
            message=query.message,
            status_msg=query.message,
            platform=plugin_manager.detect_platform(url),
            media_type=media_type,
            estimated_size=estimated_size,
        )
        await download_queue.put(job)


# ── Admin Commands ────────────────────────────────────────────────────────────
async def handle_allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admins only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/allow <telegram_id>`", parse_mode="Markdown")
        return
    try:
        uid = int(context.args[0])
        await allow_user(uid)
        await update.message.reply_text(f"✅ User `{uid}` authorized!", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID format.")


async def handle_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/revoke <telegram_id>`", parse_mode="Markdown")
        return
    try:
        uid = int(context.args[0])
        await revoke_user(uid)
        await update.message.reply_text(f"⛔ User `{uid}` revoked!", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID format.")


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    stat    = shutil.disk_usage("/")
    free_gb = stat.free  / (1024 ** 3)
    total_gb= stat.total / (1024 ** 3)

    active_links = sum(1 for d in DOWNLOADS_DIR.iterdir() if d.is_dir()) if DOWNLOADS_DIR.exists() else 0
    analytics    = await get_analytics_summary()
    queue_size   = download_queue.qsize() if download_queue else 0

    # Platform breakdown
    platforms = "\n".join([f"  `{p}`: {c}" for p, c in analytics["platform_breakdown"]]) or "  None yet"
    top_users = "\n".join([f"  `{u}`: {c} downloads" for u, c in analytics["top_users"]]) or "  None yet"

    msg = (
        "📊 *Advanced Bot Stats*\n\n"
        f"💾 *Disk:* `{free_gb:.2f} GB free / {total_gb:.2f} GB`\n"
        f"🔗 *Active Temp Downloads:* `{active_links}`\n"
        f"🚦 *Queue Size:* `{queue_size}/{MAX_QUEUE_SIZE}`\n"
        f"👥 *Authorized Users:* `{analytics['user_count']}`\n\n"
        f"📈 *Total Downloads:* `{analytics['total_downloads']}`\n"
        f"⚡ *Cache Hit Rate:* `{analytics['cache_hit_rate']:.1f}%`\n"
        f"⏱ *Avg Download Time:* `{analytics['avg_download_time']:.1f}s`\n\n"
        f"🌐 *By Platform:*\n{platforms}\n\n"
        f"🏆 *Top Users:*\n{top_users}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    users = await get_all_users()
    if not users:
        await update.message.reply_text("No additional users authorized.")
        return
    user_list = "\n".join([f"`{u}`" for u in users])
    await update.message.reply_text(f"👥 *Authorized Users:*\n\n{user_list}", parse_mode="Markdown")


async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown")
        return

    message = " ".join(context.args)
    users   = await get_all_users()
    targets = set(users)
    targets.add(ROOT_ADMIN)

    success = 0
    for uid in targets:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Broadcast from Admin:*\n\n{message}",
                parse_mode="Markdown"
            )
            success += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {success} users.")


# ── Post Init (command scopes) ────────────────────────────────────────────────
async def post_init(application):
    user_commands = [
        BotCommand("start", "Show instructions"),
        BotCommand("help",  "Get detailed help"),
        BotCommand("audio", "Extract audio ONLY from link"),
    ]
    admin_commands = user_commands + [
        BotCommand("stats",     "Admin: Server stats & analytics"),
        BotCommand("users",     "Admin: List users"),
        BotCommand("allow",     "Admin: Authorize user"),
        BotCommand("revoke",    "Admin: Revoke user"),
        BotCommand("broadcast", "Admin: Send announcement"),
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ROOT_ADMIN))

    admin_id = int(os.getenv("ADMIN_ID", str(ROOT_ADMIN)))
    if admin_id != ROOT_ADMIN:
        try:
            await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass

    # Initialize DB
    await init_db()
    logger.info("Database initialized via post_init.")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    global download_queue

    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        return

    download_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

    tg_app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    tg_app.add_handler(CommandHandler("start",     start))
    tg_app.add_handler(CommandHandler("help",      help_command))
    tg_app.add_handler(CommandHandler("audio",     handle_audio_command))
    tg_app.add_handler(CommandHandler("allow",     handle_allow))
    tg_app.add_handler(CommandHandler("revoke",    handle_revoke))
    tg_app.add_handler(CommandHandler("stats",     handle_stats))
    tg_app.add_handler(CommandHandler("users",     handle_users))
    tg_app.add_handler(CommandHandler("broadcast", handle_broadcast))
    tg_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    tg_app.add_handler(CallbackQueryHandler(handle_callback_query))

    await tg_app.initialize()
    await tg_app.start()

    async def run_polling():
        while True:
            try:
                logger.info("Starting Telegram polling...")
                await tg_app.updater.start_polling(drop_pending_updates=True)
                # Keep the polling loop alive
                while tg_app.updater.running:
                    await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Polling error: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

    # Start polling in background
    polling_task = asyncio.create_task(run_polling())

    # Start worker pool
    workers = [asyncio.create_task(_worker(i)) for i in range(MAX_CONCURRENT_JOBS)]
    logger.info(f"Started {MAX_CONCURRENT_JOBS} download worker(s).")

    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=8500, log_level="warning")
    server = uvicorn.Server(config)
    logger.info("Starting FastAPI server on port 8500.")

    try:
        await server.serve()
    finally:
        polling_task.cancel()
        for w in workers:
            w.cancel()
        if tg_app.updater.running:
            await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())