"""Phase 2.6 — Shared HTTP client singleton.

Provides a single httpx.AsyncClient instance for all new code, with
sensible defaults: HTTP/2 enabled, connection pooling, timeouts.

Existing v1.5.0 code uses requests, aiohttp, and httpx ad-hoc. This
module is the canonical client going forward. Migrate callers
gradually — do NOT rewrite all existing callers in one pass.

TODO (future phases): migrate these files to use this client:
  - bot/helper/ext_utils/bot_utils.py (search_images uses httpx.AsyncClient directly)
  - bot/helper/mirror_leech_utils/download_utils/direct_link_generator.py (uses requests + cloudscraper)
  - bot/helper/ext_utils/shortener_utils.py (uses requests)
  - web/wserver.py (uses aiohttp.ClientSession for proxy fetch)

Usage:
    from bot.helper.ext_utils.http_client import http_client

    async def fetch(url):
        resp = await http_client.get(url)
        return resp.json()
"""

from httpx import AsyncClient, Timeout, Limits, HTTPStatusError
from logging import getLogger

LOGGER = getLogger(__name__)

# Singleton — created lazily on first use (so we don't create it at
# import time, which would fail if httpx isn't installed yet during
# dependency installation).
_client = None


def _create_client():
    """Create the shared httpx.AsyncClient with project defaults."""
    return AsyncClient(
        # Timeouts: 30s connect (fail fast on unreachable hosts),
        # 300s read (allow slow downloads), 60s write, 10s pool wait.
        timeout=Timeout(connect=30.0, read=300.0, write=60.0, pool=10.0),
        # Connection pooling: 100 max connections, 20 keepalive.
        # Plenty for a single-bot deployment with 10 concurrent tasks.
        limits=Limits(max_connections=100, max_keepalive_connections=20),
        # HTTP/2 — multiplexes requests over a single connection,
        # reduces latency for hosts that support it.
        http2=True,
        # Follow redirects — most file-hosting sites redirect to CDN.
        follow_redirects=True,
        # Default headers — a realistic User-Agent avoids blocks.
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


async def get_client():
    """Return the shared AsyncClient, creating it on first call."""
    global _client
    if _client is None or _client.is_closed:
        _client = _create_client()
    return _client


async def close_client():
    """Close the shared client. Called on graceful shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


# Convenience property — use `http_client.get(...)` etc. This is a
# proxy that delegates to the singleton. For awaitable methods, use
# `await http_client.get(...)` — the proxy returns the coroutine.
class _HttpClientProxy:
    """Proxy that delegates attribute access to the shared client.
    Use `await http_client.get(url)` etc."""

    async def _get_client(self):
        return await get_client()

    async def get(self, url, **kwargs):
        client = await self._get_client()
        return await client.get(url, **kwargs)

    async def post(self, url, **kwargs):
        client = await self._get_client()
        return await client.post(url, **kwargs)

    async def put(self, url, **kwargs):
        client = await self._get_client()
        return await client.put(url, **kwargs)

    async def delete(self, url, **kwargs):
        client = await self._get_client()
        return await client.delete(url, **kwargs)

    async def head(self, url, **kwargs):
        client = await self._get_client()
        return await client.head(url, **kwargs)

    async def request(self, method, url, **kwargs):
        client = await self._get_client()
        return await client.request(method, url, **kwargs)

    async def stream(self, method, url, **kwargs):
        """Return a streaming response context manager."""
        client = await self._get_client()
        return client.stream(method, url, **kwargs)


http_client = _HttpClientProxy()
