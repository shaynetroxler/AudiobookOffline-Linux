from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gi
import requests

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "audiobookshelf-linux" / "covers"

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cover-fetch")


def _cache_path(item_id: str, width: int) -> Path:
    return CACHE_ROOT / f"{item_id}_{width}.png"


def fetch(client, item_id: str, width: int = 80) -> Path | None:
    """Return a local file path for this item's cover, downloading and
    caching it on disk first if needed. Safe to call from any thread."""
    path = _cache_path(item_id, width)
    if path.exists():
        return path
    response = requests.get(client.cover_url(item_id, width=width), timeout=10)
    if not response.ok:
        return None
    # Audiobookshelf serves covers as WebP. Re-encode to PNG on disk: this
    # GTK build's WebP texture path renders blank even though the pixel data
    # decodes correctly (confirmed via GdkPixbuf inspection) -- PNG avoids it.
    loader = GdkPixbuf.PixbufLoader()
    loader.write(response.content)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(path), "png", [], [])
    return path


def fetch_async(client, item_id: str, on_done, width: int = 80):
    """Fetch in a bounded background thread pool; on_done(path_or_None) is
    called back on that worker thread, NOT the GTK main thread -- callers
    must hop back via GLib.idle_add themselves."""
    def work():
        try:
            path = fetch(client, item_id, width=width)
        except Exception:
            path = None
        on_done(path)

    _executor.submit(work)
