import socket
from asyncio import Event, Lock, Semaphore, gather, sleep, wait_for
from contextlib import asynccontextmanager
from time import monotonic

from pyrogram import raw, utils
from pyrogram.connection.transport.tcp.tcp import TCP
from pyrogram.errors import FloodPremiumWait, FloodWait
from pyrogram.file_id import FileType, ThumbnailSource
from pyrogram.methods.rate_limiter import AdaptiveBucket
from pyrogram.session import Session

from ... import LOGGER
from ...core.tg_client import WZGRAM_MEDIA_RESTART_ATTEMPTS, TgClient

_current_tcp_connect = TCP.connect
_orig_tcp_connect = getattr(
    _current_tcp_connect,
    "_amaterasu_original",
    _current_tcp_connect,
)


async def _tcp_tuned_connect(self, address):
    await _orig_tcp_connect(self, address)
    sock = None
    if self.writer:
        try:
            sock = self.writer.get_extra_info("socket")
        except Exception as e:
            LOGGER.info(f"HypertgTCP get socket err: {e}")
    if sock:
        options = (
            (socket.IPPROTO_TCP, "TCP_NODELAY", 1),
            (socket.SOL_SOCKET, "SO_KEEPALIVE", 1),
            (socket.IPPROTO_TCP, "TCP_KEEPIDLE", 60),
            (socket.IPPROTO_TCP, "TCP_KEEPINTVL", 10),
            (socket.IPPROTO_TCP, "TCP_KEEPCNT", 3),
            (socket.IPPROTO_TCP, "TCP_QUICKACK", 1),
        )
        for level, option_name, value in options:
            option = getattr(socket, option_name, None)
            if option is None:
                continue
            try:
                sock.setsockopt(level, option, value)
            except (AttributeError, OSError, ValueError) as error:
                LOGGER.debug(
                    "HypertgTCP %s tune failed: %s",
                    option_name,
                    error,
                )


_tcp_tuned_connect._amaterasu_original = _orig_tcp_connect
_tcp_tuned_connect._amaterasu_tuned = True
if not getattr(_current_tcp_connect, "_amaterasu_tuned", False):
    TCP.connect = _tcp_tuned_connect

MB = 1024 * 1024

_global_work_loads = None


class _DownloadPacer:
    """Share admission and Telegram cooldowns across one account's downloads."""

    def __init__(self):
        self.in_flight = Semaphore(4 * max(1, Session.MAX_INFLIGHT_MEDIA))
        self.bucket = AdaptiveBucket(rate=32, ceiling=300, burst=16, step=1.0)
        self.lock = Lock()
        self.flood_until = 0.0

    @asynccontextmanager
    async def slot(self):
        async with self.in_flight:
            async with self.lock:
                while True:
                    delay = self.flood_until - monotonic()
                    if delay > 0:
                        await sleep(delay)
                        continue
                    await self.bucket.acquire()
                    if self.flood_until <= monotonic():
                        break
            try:
                yield
            except (FloodWait, FloodPremiumWait) as error:
                self.flood_until = max(
                    self.flood_until, monotonic() + max(float(error.value), 1) + 1,
                )
                self.bucket.on_flood()
                raise
            else:
                self.bucket.on_success()


def _download_pacer(client):
    pacer = getattr(client, "_amaterasu_download_pacer", None)
    if pacer is None:
        pacer = client._amaterasu_download_pacer = _DownloadPacer()
    return pacer


class MtprotoPool:
    def __init__(self, clients, sessions_per_client=1):
        if isinstance(clients, dict):
            self._client_map = dict(clients)
            self._client_order = list(clients.keys())
        else:
            self._client_map = {i: c for i, c in enumerate(clients)}
            self._client_order = list(self._client_map.keys())
        self._sessions = {}
        self._locks = {}
        self.sessions_per_client = max(1, sessions_per_client)
        self._cursors = {}
        self._limited = set()

    def _resolve_key(self, client_key):
        if client_key in self._client_map:
            return client_key
        if isinstance(client_key, int) and self._client_order:
            return self._client_order[client_key % len(self._client_order)]
        raise KeyError(f"Client key {client_key} not found")

    async def get_session(self, client_key, dc_id, is_media=True):
        ck = self._resolve_key(client_key)
        group = (ck, dc_id, is_media)
        cursor = self._cursors.get(group, 0)
        self._cursors[group] = cursor + 1
        fallback = self._fallback_session(group, cursor)
        if fallback is not None:
            return fallback
        cache_key = (*group, cursor % self.sessions_per_client)
        s = self._sessions.get(cache_key)
        if s and s.is_started.is_set() and not getattr(s, "_amaterasu_media_failed", False):
            return s
        if group not in self._locks:
            self._locks[group] = Lock()
        async with self._locks[group]:
            fallback = self._fallback_session(group, cursor)
            if fallback is not None:
                return fallback
            s = self._sessions.get(cache_key)
            if s and s.is_started.is_set() and not getattr(s, "_amaterasu_media_failed", False):
                return s
            if s:
                await self._stop_session(s)
                self._sessions.pop(cache_key, None)
            client = self._client_map[ck]
            # Use WZGram's public session path so media-only DC endpoints,
            # cross-DC authorization, proxy settings, and WarpCrypto's
            # executor are configured exactly like standard transfers.
            try:
                s = await wait_for(
                    client.get_session(dc_id, is_media=is_media, temporary=True), timeout=15,
                )
            except Exception:
                self._limited.add(group)
                fallback = self._fallback_session(group, cursor)
                if fallback is None:
                    raise
                LOGGER.warning("HyperTG client %s DC%s could not add a media session; retaining its healthy pool", ck, dc_id)
                return fallback
            s.MAX_RETRIES = min(getattr(s, "MAX_RETRIES", WZGRAM_MEDIA_RESTART_ATTEMPTS), WZGRAM_MEDIA_RESTART_ATTEMPTS)
            self._sessions[cache_key] = s
        return s

    def _fallback_session(self, group, cursor):
        if group not in self._limited:
            return None
        healthy = [session for key, session in self._sessions.items()
                   if key[:3] == group and session.is_started.is_set()
                   and not getattr(session, "_amaterasu_media_failed", False)]
        return healthy[cursor % len(healthy)] if healthy else None

    async def drop_session(self, client_key, dc_id):
        ck = self._resolve_key(client_key)
        sessions = [self._sessions.pop(key) for key in list(self._sessions) if key[:2] == (ck, dc_id)]
        self._limited = {group for group in self._limited if group[:2] != (ck, dc_id)}
        await gather(*(self._stop_session(s) for s in sessions))

    @staticmethod
    async def _stop_session(session):
        try:
            await wait_for(session.stop(), timeout=10)
        except Exception as error:
            LOGGER.debug("Unable to stop HyperTG media session: %s", error)

    async def stop(self):
        sessions = list(self._sessions.values())
        self._sessions.clear()
        self._cursors.clear()
        self._limited.clear()
        await gather(*(self._stop_session(s) for s in sessions))


class HypertgTransfer:
    def __init__(self, obj, media_sessions=1):
        global _global_work_loads
        self._obj = obj
        self._listener = obj._listener
        self.clients = dict(TgClient.helper_bots)
        self.client_ids = list(self.clients.keys())
        if TgClient.helper_users:
            for no, client in TgClient.helper_users.items():
                self.clients[-no] = client
                self.client_ids.append(-no)
        if TgClient.user and all(c is not TgClient.user for c in self.clients.values()):
            key = -(max(TgClient.helper_users, default=0) + 1)
            while key in self.clients:
                key -= 1
            self.clients[key] = TgClient.user
            self.client_ids.append(key)

        # Helper clients start in the background and can appear after the
        # first transfer object is constructed.  Reconcile the shared load
        # map on every construction instead of freezing the first snapshot.
        if _global_work_loads is None:
            _global_work_loads = {}
        initial_loads = dict(TgClient.helper_loads)
        initial_loads.update(
            {-no: load for no, load in TgClient.helper_user_loads.items()}
        )
        for key in self.clients:
            _global_work_loads.setdefault(key, initial_loads.get(key, 0))
        for key in list(_global_work_loads):
            if key not in self.clients and _global_work_loads[key] <= 0:
                _global_work_loads.pop(key, None)
        self.work_loads = _global_work_loads
        self.num_clients = len(self.clients)
        self._pool = MtprotoPool(self.clients, sessions_per_client=media_sessions)
        self._cancel = Event()
        self._tasks = []
        LOGGER.info(
            f"HypertgTransfer init clients={self.num_clients} "
            f"loads={dict(self.work_loads)}"
        )

    def _pick_client(self, user_only=None):
        candidates = [
            key for key in self.clients
            if user_only is None or (key < 0 if user_only else key > 0)
        ]
        if not candidates:
            raise RuntimeError("No active HyperTG helper clients")
        now = monotonic()
        return min(
            candidates,
            key=lambda client_id: (
                max(
                    0,
                    getattr(self.clients[client_id], "_amaterasu_send_flood_until", 0) - now,
                    getattr(self.clients[client_id], "_amaterasu_hyper_retry_until", 0) - now,
                    getattr(getattr(self.clients[client_id], "_amaterasu_upload_pacer", None), "flood_until", 0) - now,
                ),
                self.work_loads.get(client_id, 0),
            ),
        )

    async def _get_session(self, idx, dc_id, force=False):
        if force:
            await self._pool.drop_session(idx, dc_id)
        return await self._pool.get_session(idx, dc_id, is_media=True)

    async def _warmup(self, indices, dc_id):
        async def _w(i):
            try:
                await self._pool.get_session(i, dc_id)
            except Exception as e:
                LOGGER.warning(f"HypertgTransfer warmup fail client {i}: {e}")

        await gather(*[_w(i) for i in indices])

    async def _close_all(self):
        await self._pool.stop()

    @staticmethod
    def _location(fid):
        ft = fid.file_type
        if ft == FileType.CHAT_PHOTO:
            if fid.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=fid.chat_id, access_hash=fid.chat_access_hash
                )
            elif fid.chat_access_hash == 0:
                peer = raw.types.InputPeerChat(chat_id=-fid.chat_id)
            else:
                peer = raw.types.InputPeerChannel(
                    channel_id=utils.get_channel_id(fid.chat_id),
                    access_hash=fid.chat_access_hash,
                )
            loc = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=fid.volume_id,
                local_id=fid.local_id,
                big=fid.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
            )
            return loc
        if ft == FileType.PHOTO:
            loc = raw.types.InputPhotoFileLocation(
                id=fid.media_id,
                access_hash=fid.access_hash,
                file_reference=fid.file_reference,
                thumb_size=fid.thumbnail_size,
            )
            return loc
        loc = raw.types.InputDocumentFileLocation(
            id=fid.media_id,
            access_hash=fid.access_hash,
            file_reference=fid.file_reference,
            thumb_size=fid.thumbnail_size,
        )
        return loc

    async def cancel(self):
        self._cancel.set()
        for t in self._tasks:
            if not t.done():
                t.cancel()
        if self._tasks:
            await gather(*self._tasks, return_exceptions=True)
        await self._close_all()
