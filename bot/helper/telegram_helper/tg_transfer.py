from asyncio import Event, Lock, gather, sleep
from concurrent.futures import ThreadPoolExecutor
from os import cpu_count
import socket

import pyrogram
from pyrogram import raw, utils
from pyrogram.connection import Connection
from pyrogram.connection.transport.tcp.tcp import TCP
from pyrogram.errors import AuthBytesInvalid, AuthKeyDuplicated, RPCError
from pyrogram.file_id import FileType, ThumbnailSource
from pyrogram.raw.all import layer
from pyrogram.session import Auth, Session
from pyrogram.session.internals import DataCenter

from ... import LOGGER
from ...core.tg_client import TgClient

pyrogram.crypto_executor = ThreadPoolExecutor(
    max_workers=min(16, (cpu_count() or 4) * 2), thread_name_prefix="crypto"
)

_orig_tcp_connect = TCP.connect


async def _tcp_tuned_connect(self, address):
    await _orig_tcp_connect(self, address)
    sock = None
    if self.writer:
        try:
            sock = self.writer.get_extra_info("socket")
        except Exception as e:
            LOGGER.info(f"HypertgTCP get socket err: {e}")
    if sock:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
        except OSError as e:
            LOGGER.info(f"HypertgTCP socket tune failed: {e}")


_orig_dc_new = DataCenter.__new__


def _dc_alt_port(cls, dc_id, test_mode, ipv6, media):
    ip, port = _orig_dc_new(cls, dc_id, test_mode, ipv6, media)
    if media and not test_mode:
        port = 5222
    return ip, port


TCP.connect = _tcp_tuned_connect
_hyper_patches_applied = False


def _apply_hyper_patches():
    """Enable the alternate Telegram media port only for Hyper transfers.

    This module is imported by the ordinary uploader too.  Applying the
    DataCenter override at import time therefore routed normal Pyrogram
    uploads through the Hyper port even when USE_HYPER=False.
    """
    global _hyper_patches_applied
    if _hyper_patches_applied:
        return
    try:
        DataCenter.__new__ = staticmethod(_dc_alt_port)
        _hyper_patches_applied = True
        LOGGER.info("Applied Hyper DC media port 5222")
    except Exception as e:
        LOGGER.warning(f"Failed to apply Hyper DC port patch: {e}")

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

    async def _get_auth_key(self, client, dc_id):
        test_mode = await client.storage.test_mode()
        main_dc = await client.storage.dc_id()
        if dc_id == main_dc:
            return await client.storage.auth_key(), False
        ak = await Auth(client, dc_id, test_mode).create()
        return ak, True

    async def get_session(self, client_key, dc_id, is_media=True):
        ck = self._resolve_key(client_key)
        cache_key = (ck, dc_id)
        s = self._sessions.get(cache_key)
        if s and s.is_started.is_set():
            return s
        if cache_key not in self._locks:
            self._locks[cache_key] = __import__("asyncio").Lock()
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
            ak, is_cross = await self._get_auth_key(client, dc_id)
            s = Session(
                client, dc_id, ak, await client.storage.test_mode(), is_media=is_media
            )
            await s.start()
            if is_cross:
                for attempt in range(6):
                    try:
                        e = await client.invoke(
                            raw.functions.auth.ExportAuthorization(dc_id=dc_id)
                        )
                        await s.invoke(
                            raw.functions.auth.ImportAuthorization(
                                id=e.id, bytes=e.bytes
                            )
                        )
                        break
                    except AuthBytesInvalid:
                        await sleep(1)
                else:
                    await s.stop()
                    raise RuntimeError(f"Auth export/import failed for DC {dc_id}")
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
        if _global_work_loads is None:
            _global_work_loads = dict(TgClient.helper_loads)
            if TgClient.helper_users:
                for no, load in TgClient.helper_user_loads.items():
                    _global_work_loads[-no] = load
            if TgClient.user:
                key = -(len(TgClient.helper_users) + 1)
                _global_work_loads[key] = 0
        self.work_loads = _global_work_loads
        self.client_ids = list(self.clients.keys())
        if TgClient.helper_users:
            for no, client in TgClient.helper_users.items():
                self.clients[-no] = client
                self.client_ids.append(-no)
        if TgClient.user and all(c is not TgClient.user for c in self.clients.values()):
            key = -(len(TgClient.helper_users) + 1)
            self.clients[key] = TgClient.user
            self.client_ids.append(key)
        self.num_clients = len(self.clients)
        self._pool = MtprotoPool(self.clients)
        self._cancel = Event()
        self._tasks = []
        LOGGER.info(
            f"HypertgTransfer init clients={self.num_clients} "
            f"loads={dict(self.work_loads)}"
        )

    def _pick_client(self):
        return min(self.work_loads, key=self.work_loads.get)

    @staticmethod
    async def start_session(s, mode=3):
        while True:
            s.connection = Connection(
                s.dc_id, s.test_mode, s.client.ipv6,
                s.client.proxy, s.is_media, mode=mode
            )
            try:
                await s.connection.connect()
                s.network_task = s.client.loop.create_task(s.network_worker())
                await s.send(raw.functions.Ping(ping_id=0), timeout=Session.START_TIMEOUT)
                if not s.is_cdn:
                    await s.send(
                        raw.functions.InvokeWithLayer(
                            layer=layer,
                            query=raw.functions.InitConnection(
                                api_id=await s.client.storage.api_id(),
                                app_version=s.client.app_version,
                                device_model=s.client.device_model,
                                system_version=s.client.system_version,
                                system_lang_code=s.client.lang_code,
                                lang_code=s.client.lang_code,
                                lang_pack="",
                                query=raw.functions.help.GetConfig(),
                            )
                        ),
                        timeout=Session.START_TIMEOUT
                    )
                s.ping_task = s.client.loop.create_task(s.ping_worker())
            except AuthKeyDuplicated as e:
                await s.stop()
                raise e
            except (OSError, TimeoutError, RPCError):
                await s.stop()
                continue
            except Exception as e:
                await s.stop()
                raise e
            else:
                break
        s.is_connected.set()

    def _get_lock(self, client_id, dc_id):
        key = (client_id, dc_id)
        if key not in self._session_locks:
            self._session_locks[key] = Lock()
        return self._session_locks[key]

    async def _mk_session(self, client, dc_id, mode=3):
        tm = await client.storage.test_mode()
        ak, is_cross = await self.create_auth(client, dc_id, tm)
        s = Session(client, dc_id, ak, tm, is_media=True)
        await self.start_session(s, mode=mode)
        if is_cross:
            for attempt in range(6):
                try:
                    e = await client.invoke(
                        raw.functions.auth.ExportAuthorization(dc_id=dc_id)
                    )
                    await s.invoke(
                        raw.functions.auth.ImportAuthorization(id=e.id, bytes=e.bytes)
                    )
                    break
                except AuthBytesInvalid:
                    LOGGER.warning(
                        f"HypertgTransfer AuthBytesInvalid attempt {attempt + 1}/6 "
                        f"client={client.me.username} dc={dc_id}"
                    )
                    await sleep(1)
            else:
                await s.stop()
                LOGGER.error(f"HypertgTransfer mk_session dc={dc_id} auth failed")
                raise AuthBytesInvalid
        client.media_sessions[dc_id] = s
        return s

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
