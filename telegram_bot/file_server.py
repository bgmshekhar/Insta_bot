"""
file_server.py — FastAPI direct-download server with:
  - UUID-based shadow routing (tamper-proof)
  - Range request / chunked streaming support (resume-capable)
  - Periodic disk-reaper (crash-safe cleanup, no in-memory timers)
"""
import os
import time
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
DOWNLOADS_DIR = Path("telegram_bot/downloads")
FILE_TTL_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT", "900"))   # 15 min default
REAPER_INTERVAL = 300                                            # scan every 5 min
CHUNK_SIZE = 1024 * 1024                                         # 1 MB stream chunks

active_downloads: set[str] = set()
active_download_dirs: set[str] = set()
valid_tokens: dict[str, float] = {}

def register_token(uuid_token: str):
    valid_tokens[uuid_token] = time.time() + FILE_TTL_SECONDS


# ── Reaper Task ──────────────────────────────────────────────────────────────
async def _reaper_loop():
    """Periodically delete expired UUID download folders."""
    while True:
        await asyncio.sleep(REAPER_INTERVAL)
        now = time.time()

        # Clean up expired tokens
        expired_tokens = [tok for tok, exp in valid_tokens.items() if now > exp]
        for tok in expired_tokens:
            if tok not in active_downloads:
                valid_tokens.pop(tok, None)

        if DOWNLOADS_DIR.exists():
            for uuid_dir in DOWNLOADS_DIR.iterdir():
                if not uuid_dir.is_dir():
                    continue
                if uuid_dir.name in active_download_dirs:
                    logger.debug(f"[Reaper] skipping {uuid_dir.name} (download in progress)")
                    continue
                if uuid_dir.name in active_downloads:
                    logger.debug(f"[Reaper] skipping {uuid_dir.name} (being served)")
                    continue
                age = now - uuid_dir.stat().st_mtime
                if age > FILE_TTL_SECONDS:
                    try:
                        import shutil
                        shutil.rmtree(uuid_dir, ignore_errors=True)
                        logger.info(f"[Reaper] Cleaned up expired folder: {uuid_dir.name}")
                    except Exception as e:
                        logger.warning(f"[Reaper] Failed to remove {uuid_dir}: {e}")


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background reaper on startup; cancel it on shutdown."""
    reaper = asyncio.create_task(_reaper_loop())
    logger.info("[FileServer] Reaper task started.")
    yield
    reaper.cancel()
    logger.info("[FileServer] Reaper task stopped.")


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


def _find_file(uuid_token: str) -> Path | None:
    """Resolve a UUID token to the single file inside that folder."""
    target = DOWNLOADS_DIR / uuid_token
    if not target.is_dir():
        return None
    for f in target.iterdir():
        if f.is_file():
            return f
    return None


def _iter_range(file_path: Path, start: int, end: int):
    """Generator that streams a byte range from a file."""
    with open(file_path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)


@app.get("/dl/{uuid_token}")
async def download_file(uuid_token: str, request: Request):
    """Serve a file by UUID — supports Range requests for resume capability."""
    file_path = _find_file(uuid_token)
    if file_path is None:
        raise HTTPException(status_code=404, detail="File not found or link has expired.")

    active_downloads.add(uuid_token)

    def stream_with_cleanup(start: int, end: int):
        try:
            yield from _iter_range(file_path, start, end)
        finally:
            active_downloads.discard(uuid_token)

    try:
        file_size = file_path.stat().st_size
        range_header = request.headers.get("Range")

        if range_header:
            # Parse "bytes=start-end"
            try:
                unit, rng = range_header.split("=")
                start_str, end_str = rng.split("-")
                start = int(start_str)
                end = int(end_str) if end_str else file_size - 1
            except Exception:
                raise HTTPException(status_code=416, detail="Invalid Range header.")

            if start >= file_size or end >= file_size:
                raise HTTPException(status_code=416, detail="Range out of bounds.")

            content_length = end - start + 1
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Disposition": f'attachment; filename="{file_path.name}"',
            }
            return StreamingResponse(
                stream_with_cleanup(start, end),
                status_code=206,
                headers=headers,
                media_type="application/octet-stream",
            )

        # Full file response
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'attachment; filename="{file_path.name}"',
        }
        return StreamingResponse(
            stream_with_cleanup(0, file_size - 1),
            media_type="application/octet-stream",
            headers=headers,
        )
    except Exception:
        active_downloads.discard(uuid_token)
        raise


@app.get("/health")
async def health():
    return {"status": "ok"}
