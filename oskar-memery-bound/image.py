"""Long-running HTTP server that serves the most-reacted Telegram image.

On startup it logs in as a Telegram *user* (not a bot — bots can't read chat
history or reaction counts). The login is interactive the first time (phone
number, code, optional 2FA password) and the session is persisted to disk, so
subsequent starts are non-interactive.

Endpoints:
    GET /meme?days=X   -> {"url": "http://<host>/images/<file>.jpg", "message": "..."}
    GET /images/<file> -> the cached image bytes
    GET /health        -> {"status": "ok"}

Configuration (environment variables):
    TELEGRAM_API_ID     required   from https://my.telegram.org
    TELEGRAM_API_HASH   required   from https://my.telegram.org
    TELEGRAM_CHAT       required   @username, t.me link, numeric id, or "me"
    DATA_DIR            optional   where the session + image cache live (./data)
    PORT                optional   listen port (8080)
    CACHE_TTL           optional   seconds to reuse a /meme result (300)
    PUBLIC_BASE_URL     optional   override the host used to build image URLs
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web
from telethon import TelegramClient


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #

def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"error: {name} is not set", file=sys.stderr)
        sys.exit(1)
    return value


API_ID = int(_require_env("TELEGRAM_API_ID"))
API_HASH = _require_env("TELEGRAM_API_HASH")
CHAT = _require_env("TELEGRAM_CHAT")

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
IMAGE_DIR = DATA_DIR / "images"
SESSION_PATH = DATA_DIR / "session"
PORT = int(os.environ.get("PORT", "8080"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")

# in-memory cache of computed results, keyed by the `days` value:
#   days -> (computed_at_epoch, filename, caption)
_result_cache: dict[int, tuple[float, str, str]] = {}
# serialises Telegram history scans so concurrent requests don't stampede.
_scan_lock = asyncio.Lock()


# --------------------------------------------------------------------------- #
# telegram helpers
# --------------------------------------------------------------------------- #

def _reaction_count(message) -> int:
    """Total number of reactions on a message (0 if none)."""
    reactions = getattr(message, "reactions", None)
    if not reactions or not reactions.results:
        return 0
    return sum(r.count for r in reactions.results)


def _resolve_chat(raw: str):
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


async def _find_most_reacted(client: TelegramClient, days: int):
    """Return the best (message, reaction_count) photo in the last `days`."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entity = await client.get_entity(_resolve_chat(CHAT))

    best_message = None
    best_count = -1

    # newest-first; stop as soon as we cross the cutoff.
    async for message in client.iter_messages(entity):
        if message.date < cutoff:
            break
        if message.photo is None:
            continue
        count = _reaction_count(message)
        if count > best_count:
            best_count = count
            best_message = message

    return best_message, best_count


async def _get_cached_result(
    client: TelegramClient, days: int
) -> tuple[str, str] | None:
    """(filename, message) of the most-reacted image for `days`.

    Downloads the image if it isn't cached on disk. Returns None if no image
    was found in the window. `message` is the photo's caption ("" if none).
    """
    now = time.time()
    cached = _result_cache.get(days)
    if cached and now - cached[0] < CACHE_TTL:
        # trust the cache only if the file is still on disk.
        if (IMAGE_DIR / cached[1]).exists():
            return cached[1], cached[2]

    async with _scan_lock:
        # re-check: another request may have populated it while we waited.
        cached = _result_cache.get(days)
        if cached and time.time() - cached[0] < CACHE_TTL and (IMAGE_DIR / cached[1]).exists():
            return cached[1], cached[2]

        message, _count = await _find_most_reacted(client, days)
        if message is None:
            return None

        # cache the download itself by message id so repeat winners are free.
        filename = f"{message.chat_id}_{message.id}.jpg"
        path = IMAGE_DIR / filename
        if not path.exists():
            await client.download_media(message, file=str(path))

        caption = message.message or ""
        _result_cache[days] = (time.time(), filename, caption)
        return filename, caption


# --------------------------------------------------------------------------- #
# http handlers
# --------------------------------------------------------------------------- #

async def handle_meme(request: web.Request) -> web.Response:
    raw_days = request.query.get("days", "7")
    try:
        days = int(raw_days)
        if days <= 0:
            raise ValueError
    except ValueError:
        return web.json_response(
            {"error": "days must be a positive integer"}, status=400
        )

    client: TelegramClient = request.app["client"]
    try:
        result = await _get_cached_result(client, days)
    except Exception as exc:  # surface Telegram errors as 502 rather than crash
        return web.json_response({"error": str(exc)}, status=502)

    if result is None:
        return web.json_response(
            {"error": f"no images found in the last {days} day(s)"}, status=404
        )

    filename, message = result
    if PUBLIC_BASE_URL:
        url = f"{PUBLIC_BASE_URL.rstrip('/')}/images/{filename}"
    else:
        url = str(request.url.with_path(f"/images/{filename}").with_query(None))

    return web.json_response({"url": url, "message": message})


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# --------------------------------------------------------------------------- #
# startup / wiring
# --------------------------------------------------------------------------- #

async def on_startup(app: web.Application) -> None:
    client = TelegramClient(str(SESSION_PATH), API_ID, API_HASH)
    print("Connecting to Telegram...", flush=True)
    # start() prompts interactively for phone / code / 2FA on first run only;
    # afterwards the persisted session is reused non-interactively.
    await client.start()
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username})", flush=True)
    app["client"] = client


async def on_cleanup(app: web.Application) -> None:
    client = app.get("client")
    if client is not None:
        await client.disconnect()


def build_app() -> web.Application:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    app = web.Application()
    app.router.add_get("/meme", handle_meme)
    app.router.add_get("/health", handle_health)
    app.router.add_static("/images/", str(IMAGE_DIR))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(build_app(), port=PORT)
