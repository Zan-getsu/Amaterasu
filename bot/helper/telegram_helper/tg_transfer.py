import socket
from asyncio import Event, Lock, gather

from pyrogram import raw, utils
from pyrogram.connection.transport.tcp.tcp import TCP
from pyrogram.file_id import FileType, ThumbnailSource

from ... import LOGGER
from ...core.tg_client import TgClient

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


class MtprotoPool:
    def __init__(self, clients):
        if isinstance(clients, dict):
            self._client_map = dict(clients)
            self._client_order = list(clients.keys())
        else:
            self._client_map = {i: c for i, c in enumerate(clients)}
            self._client_order = list(self._client_map.keys())
        self._sessions = {}
        self._locks = {}

    def _resolve_key(self, client_key):
        if client_key in self._client_map:
            return client_key
        if isinstance(client_key, int) and self._client_order:
            return self._client_order[client_key % len(self._client_order)]
        raise KeyError(f"Client key {client_key} not found")

    async def get_session(self, client_key, dc_id, is_media=True):
        ck = self._resolve_key(client_key)
        cache_key = (ck, dc_id)
        s = self._sessions.get(cache_key)
        if s and s.is_started.is_set():
            return s
        if cache_key not in self._locks:
            self._locks[cache_key] = Lock()
        async with self._locks[cache_key]:
            s = self._sessions.get(cache_key)
            if s and s.is_started.is_set():
                return s
            if s:
                try:
                    await s.stop()
                except Exception:
                    pass
            client = self._client_map[ck]
            # Use WZGram's public session path so media-only DC endpoints,
            # cross-DC authorization, proxy settings, and WarpCrypto's
            # executor are configured exactly like standard transfers.
            s = await client.get_session(
                dc_id,
                is_media=is_media,
                temporary=True,
            )
            self._sessions[cache_key] = s
        return s

    async def drop_session(self, client_key, dc_id):
        ck = self._resolve_key(client_key)
        cache_key = (ck, dc_id)
        s = self._sessions.pop(cache_key, None)
        if s:
            try:
                await s.stop()
            except Exception:
                pass

    async def stop(self):
        for s in self._sessions.values():
            try:
                await s.stop()
            except Exception:
                pass
        self._sessions.clear()


class HypertgTransfer:
    def __init__(self, obj):
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
        self._pool = MtprotoPool(self.clients)
        self._cancel = Event()
        self._tasks = []
        LOGGER.info(
            f"HypertgTransfer init clients={self.num_clients} "
            f"loads={dict(self.work_loads)}"
        )

    def _pick_client(self):
        if not self.clients:
            raise RuntimeError("No active HyperTG helper clients")
        return min(
            self.clients,
            key=lambda client_id: self.work_loads.get(client_id, 0),
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
