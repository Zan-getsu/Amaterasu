from asyncio import (
    CancelledError,
    Lock,
    Queue,
    QueueFull,
    QueueShutDown,
    Semaphore,
    create_task,
    gather,
    sleep,
)
from hashlib import md5
from math import ceil
from mimetypes import guess_type
from os import path as ospath
from re import search as research

from pyrogram import StopTransmission, raw
from pyrogram.errors import FilePartMissing, FloodPremiumWait, FloodWait
from pyrogram.session import Session

from ... import LOGGER
from ..telegram_helper.tg_transfer import MB, HypertgTransfer
from .bot_utils import sync_to_async

_ul_load_lock = Lock()
_ul_slots = [None]
_ul_slots_lock = Lock()


KB = 1024
PART_SIZE = 512 * KB


class HypertgUpload(HypertgTransfer):
    def __init__(self, obj):
        super().__init__(obj)
        self._up_file = ""
        self._up_size = 0
    @staticmethod
    def _parse_missing_part(exc):
        val = getattr(exc, "value", None)
        if isinstance(val, int):
            return val
        m = research(r"Part (\d+)", str(exc))
        if m:
            return int(m.group(1))
        LOGGER.warning(f"HypertgUL parse_part fallback=0 exc={exc}")
        return 0

    def _build_media(self, input_file, mime_type, media_type, attributes, thumb_file=None):
        if media_type == "photo":
            return raw.types.InputMediaUploadedPhoto(file=input_file)
        return raw.types.InputMediaUploadedDocument(
            file=input_file,
            thumb=thumb_file,
            mime_type=mime_type or "application/octet-stream",
            attributes=attributes or [],
            nosound_video=media_type == "video" and "video" in (mime_type or ""),
            force_file=media_type == "document",
        )

    async def _upload_file(self, client, file_path):
        file_size = ospath.getsize(file_path)
        file_total_parts = ceil(file_size / PART_SIZE)
        file_id = client.rnd_id()
        dc_id = await client.storage.dc_id()
        is_big = file_size > 10 * MB

        _slot_acquired = False
        async with _ul_slots_lock:
            if _ul_slots[0] is None:
                _ul_slots[0] = Semaphore(max(1, self.num_clients))
        await _ul_slots[0].acquire()
        _slot_acquired = True

        ul_ci = None
        fp = None
        q = None
        workers = []

        try:
            if self.clients:
                async with _ul_load_lock:
                    ul_ci = min(self.clients.keys(), key=lambda i: self.work_loads.get(i, 0))
                    self.work_loads[ul_ci] = self.work_loads.get(ul_ci, 0) + 1
                    _concurrent = sum(1 for v in self.work_loads.values() if v > 0)
                up_client = self.clients[ul_ci]
                LOGGER.info(
                    f"HypertgUL client={ul_ci} loads={dict(self.work_loads)} "
                    f"bots={len(self.clients)} concurrent={_concurrent}"
                )
            else:
                up_client = client
                _concurrent = 1

            _is_bot = bool(getattr(getattr(up_client, 'me', None), 'is_bot', True))
            n_workers = max(1, (4 if _is_bot else 2) // _concurrent)

            fp = open(file_path, "rb", buffering=4 * 1024 * 1024)
            q = Queue(n_workers * 4)

            tm = await client.storage.test_mode()
            ak, is_cross = await self.create_auth(client, dc_id, tm)
            ea = None
            if is_cross:
                ea = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=dc_id))

            async def _worker(wid):
                s = Session(up_client, dc_id, ak, tm, is_media=True)
                await self.start_session(s, mode=1)
                if ea is not None:
                    await s.invoke(raw.functions.auth.ImportAuthorization(id=ea.id, bytes=ea.bytes))
                try:
                    while True:
                        try:
                            data = await q.get()
                        except QueueShutDown:
                            return
                        for attempt in range(5):
                            try:
                                await s.invoke(data)
                                break
                            except StopTransmission:
                                raise
                            except CancelledError:
                                return
                            except Exception:
                                if attempt == 4:
                                    break
                                await sleep(2 ** attempt)
                finally:
                    try:
                        await s.stop()
                    except Exception:
                        pass

            workers = [create_task(_worker(i)) for i in range(n_workers)]

            rpc_fn = raw.functions.upload.SaveBigFilePart if is_big else raw.functions.upload.SaveFilePart
            POOL = 4 * 1024 * 1024
            acc = 0
            part = 0

            buf_fut = await sync_to_async(fp.read, POOL, wait=False)
            while True:
                buf = await buf_fut
                if not buf:
                    break
                buf_fut = await sync_to_async(fp.read, POOL, wait=False)

                if self._listener.is_cancelled:
                    raise StopTransmission()

                off = 0
                n = len(buf)
                while off < n:
                    end = off + PART_SIZE
                    chunk = buf[off:end]
                    rpc = rpc_fn(
                        file_id=file_id, file_part=part,
                        file_total_parts=file_total_parts, bytes=chunk,
                    )
                    while True:
                        try:
                            q.put_nowait(rpc)
                            break
                        except QueueFull:
                            await sleep(0)
                    acc += len(chunk)
                    if part & 7 == 7:
                        self._obj._processed_bytes += acc
                        acc = 0
                    part += 1
                    off = end

            if acc:
                self._obj._processed_bytes += acc

            q.shutdown()
            await gather(*workers)

            if is_big:
                result = raw.types.InputFileBig(
                    id=file_id, parts=file_total_parts,
                    name=ospath.basename(file_path),
                )
            else:
                result = raw.types.InputFile(
                    id=file_id, parts=file_total_parts,
                    name=ospath.basename(file_path),
                )
            return result
        except StopTransmission:
            LOGGER.warning("HypertgUL upload cancelled (StopTransmission)")
            raise
        except Exception as e:
            LOGGER.error(f"HypertgUL upload fail: {type(e).__name__}: {e}")
            raise
        finally:
            if ul_ci is not None:
                async with _ul_load_lock:
                    self.work_loads[ul_ci] = max(0, self.work_loads.get(ul_ci, 0) - 1)
            if _slot_acquired:
                _ul_slots[0].release()
            if q:
                q.shutdown(immediate=True)
            if workers:
                await gather(*workers, return_exceptions=True)
            if fp:
                try:
                    fp.close()
                except Exception:
                    pass

    async def _upload_small(self, client, file_path):
        file_size = ospath.getsize(file_path)
        file_total_parts = ceil(file_size / PART_SIZE)
        file_id = client.rnd_id()
        dc_id = await client.storage.dc_id()
        ak = await client.storage.auth_key()
        tm = await client.storage.test_mode()
        s = Session(client, dc_id, ak, tm, is_media=False)
        fp = open(file_path, "rb")
        h = md5()

        try:
            await s.start()
            for part in range(file_total_parts):
                if self._listener.is_cancelled:
                    raise StopTransmission()
                chunk = fp.read(PART_SIZE)
                if not chunk:
                    break
                h.update(chunk)
                await s.invoke(raw.functions.upload.SaveFilePart(
                    file_id=file_id, file_part=part, bytes=chunk,
                ))
                self._obj._processed_bytes += len(chunk)
            return raw.types.InputFile(
                id=file_id, parts=file_total_parts,
                name=ospath.basename(file_path), md5_checksum=h.hexdigest(),
            )
        finally:
            try:
                await s.stop()
            except Exception:
                pass
            fp.close()

    async def _upload_thumb(self, client, file_path):
        file_size = ospath.getsize(file_path)
        file_id = client.rnd_id()
        file_total_parts = ceil(file_size / PART_SIZE)
        fp = open(file_path, "rb")
        h = md5()

        try:
            for part in range(file_total_parts):
                if self._listener.is_cancelled:
                    raise StopTransmission()
                chunk = fp.read(PART_SIZE)
                if not chunk:
                    break
                h.update(chunk)
                await client.invoke(raw.functions.upload.SaveFilePart(
                    file_id=file_id, file_part=part, bytes=chunk,
                ))
                self._obj._processed_bytes += len(chunk)
            return raw.types.InputFile(
                id=file_id, parts=file_total_parts,
                name=ospath.basename(file_path), md5_checksum=h.hexdigest(),
            )
        finally:
            fp.close()

    async def _reupload_part(self, client, file_path, input_file, part_num):
        offset = part_num * PART_SIZE
        fp = open(file_path, "rb")
        try:
            fp.seek(offset)
            chunk = fp.read(PART_SIZE)
            if not chunk:
                LOGGER.warning(f"HypertgUL reupload part={part_num} empty")
                return
            if isinstance(input_file, raw.types.InputFileBig):
                rpc = raw.functions.upload.SaveBigFilePart(
                    file_id=input_file.id, file_part=part_num,
                    file_total_parts=input_file.parts, bytes=chunk,
                )
            else:
                rpc = raw.functions.upload.SaveFilePart(
                    file_id=input_file.id, file_part=part_num, bytes=chunk,
                )
            await client.invoke(rpc)
        except Exception as e:
            LOGGER.error(f"HypertgUL reupload part={part_num} fail: {type(e).__name__}: {e}")
        finally:
            fp.close()

    async def upload(
        self, target_client, target_chat_id, file_path, dump_chat_id,
        media_type, attributes, thumb_path=None, caption="", reply_to_message_id=None,
    ):
        self._cancel.clear()
        self._obj._processed_bytes = 0
        self._up_file = ospath.basename(file_path)
        self._up_size = ospath.getsize(file_path)

        if self._up_size > 10 * MB:
            input_file = await self._upload_file(target_client, file_path)
        else:
            input_file = await self._upload_small(target_client, file_path)

        thumb_file = None
        if thumb_path and ospath.exists(thumb_path) and ospath.getsize(thumb_path) > 0:
            thumb_file = await self._upload_thumb(target_client, thumb_path)

        mime_type = self._mime(file_path)
        input_media = self._build_media(input_file, mime_type, media_type, attributes, thumb_file)

        peer = await target_client.resolve_peer(target_chat_id)
        rpc = raw.functions.messages.SendMedia(
            peer=peer, media=input_media, message=caption or "",
            random_id=target_client.rnd_id(),
            reply_to=raw.types.InputReplyToMessage(reply_to_msg_id=reply_to_message_id)
            if reply_to_message_id else None,
            silent=True,
        )

        r_updates = None
        send_retries = 0
        missing_fixed = 0
        while True:
            try:
                r_updates = await target_client.invoke(rpc)
                break
            except FilePartMissing as e:
                part = self._parse_missing_part(e)
                missing_fixed += 1
                LOGGER.warning(
                    f"HypertgUL SendMedia missing part {part} "
                    f"(fixed {missing_fixed}) {self._up_file}"
                )
                await self._reupload_part(target_client, file_path, input_file, part)
                send_retries += 1
                if send_retries >= 100:
                    raise RuntimeError(f"SendMedia exhausted after fixing {missing_fixed} missing parts")
            except (FloodWait, FloodPremiumWait) as e:
                val = e.value if hasattr(e, "value") else 5
                send_retries += 1
                LOGGER.warning(
                    f"HypertgUL SendMedia flood {val}s "
                    f"(retry {send_retries}) {self._up_file}"
                )
                if send_retries >= 10:
                    raise
                await sleep(val + 1)
            except Exception as e:
                send_retries += 1
                LOGGER.error(
                    f"HypertgUL SendMedia {type(e).__name__}: {e} "
                    f"(retry {send_retries}) {self._up_file}"
                )
                if send_retries >= 10:
                    raise
        msg_id = None
        for u in r_updates.updates:
            if isinstance(u, (raw.types.UpdateNewMessage, raw.types.UpdateNewChannelMessage, raw.types.UpdateNewScheduledMessage)):
                msg_id = u.message.id
                break
        if msg_id is None:
            LOGGER.error("HypertgUL no UpdateNewMessage in response")
            raise ValueError("No UpdateNewMessage in SendMedia response")

        msg = await target_client.get_messages(chat_id=target_chat_id, message_ids=msg_id)
        return msg

    async def cancel(self):
        await super().cancel()

    @staticmethod
    def _mime(path):
        m, _ = guess_type(path)
        return m or "application/octet-stream"
