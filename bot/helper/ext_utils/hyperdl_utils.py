from asyncio import (
    FIRST_COMPLETED,
    CancelledError,
    Lock,
    Queue,
    create_task,
    ensure_future,
    gather,
    sleep,
    to_thread,
    wait,
)
from datetime import datetime
from mimetypes import guess_extension
import os
from os import cpu_count
from pathlib import Path
from re import sub
from sys import argv

from aiofiles.os import makedirs
from pyrogram import StopTransmission, raw
from pyrogram.crypto.aes import ctr256_decrypt
from pyrogram.errors import (
    FileMigrate,
    FileReferenceExpired,
    FileReferenceInvalid,
    FileTokenInvalid,
    FloodPremiumWait,
    FloodWait,
    RequestTokenInvalid,
)
from pyrogram.file_id import PHOTO_TYPES, FileId, FileType
from pyrogram.session import Auth, Session
from pyrogram.session.internals import MsgId

from ... import LOGGER
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..telegram_helper.tg_transfer import MB, HypertgTransfer

KB = 1024
_MIN_CHUNK = 64 * KB
_DEFAULT_PIPELINE = 32
_MIN_PIPELINE = 4
_MAX_PIPELINE_MULT = 4
_LOW_WORKERS = 2
_HIGH_WORKERS = max(8, (cpu_count() or 4) * 2)
_load_lock = Lock()


async def _pick_clients(wl, clients, count):
    keys = list(clients.keys())
    async with _load_lock:
        picked = sorted(keys, key=lambda i: wl.get(i, 0))[:count]
        for k in picked:
            wl[k] = wl.get(k, 0) + 1
    return picked


class HypertgDownload(HypertgTransfer):
    def __init__(self, obj):
        super().__init__(obj)
        self.chunk_size = max(Config.HYPER_CHUNK or 256 * KB, _MIN_CHUNK)
        self.num_parts = Config.HYPER_THREADS or max(
            _LOW_WORKERS, min(_HIGH_WORKERS, self.num_clients)
        )
        base_pipe = max(Config.HYPER_PIPELINE or _DEFAULT_PIPELINE, _MIN_PIPELINE)
        self.pipeline_depth = max(base_pipe // max(self.num_parts, 1), _MIN_PIPELINE)
        self.message = None
        self.dump_chat = None
        self.download_dir = "downloads/"
        self._ref_cache = {}
        self._cdn_info = {}
        self._cdn_sessions = {}
    def _ref_get(self, idx):
        return self._ref_cache.get(idx)

    def _ref_put(self, idx, data):
        if len(self._ref_cache) > 100:
            self._ref_cache.pop(next(iter(self._ref_cache)))
        self._ref_cache[idx] = data

    async def _fetch_ref(self, idx, client, retries=3, force=False):
        if not force:
            cached = self._ref_get(idx)
            if cached is not None:
                return cached
        last_err = None
        for attempt in range(retries):
            try:
                msg = await client.get_messages(self.dump_chat, self.message.id)
                if msg is None:
                    raise ValueError(f"msg {self.message.id} not found in {self.dump_chat}")
                media = self._media_of(msg)
                fid_str = media.file_id if hasattr(media, "file_id") else None
                if not fid_str:
                    raise ValueError(f"no file_id in media from msg {self.message.id}")
                fid = FileId.decode(fid_str)
                self._ref_put(idx, fid)
                return fid
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    await sleep(attempt + 1)
        raise ValueError(f"Failed to get file ref with {client.me.username}: {last_err}")

    @staticmethod
    def _media_of(message):
        for attr in ("audio", "document", "photo", "sticker", "animation",
                     "video", "voice", "video_note", "new_chat_photo"):
            if m := getattr(message, attr, None):
                return m
        raise ValueError("No downloadable media")

    async def _do_req(self, sess, client, location, off, csz, attempt=0):
        try:
            r = await sess.invoke(
                raw.functions.upload.GetFile(
                    precise=True, cdn_supported=True,
                    location=location, offset=off, limit=csz,
                ),
                sleep_threshold=client.sleep_threshold,
            )
            if isinstance(r, raw.types.upload.File):
                return r.bytes
            if isinstance(r, raw.types.upload.FileCdnRedirect):
                return None, {"cdn_dc": r.dc_id, "file_token": r.file_token,
                              "key": r.encryption_key, "iv": r.encryption_iv}
            raise ValueError(f"Unexpected response type: {type(r)}")
        except FileMigrate as e:
            dc = e.value if hasattr(e, "value") else int(str(e).split()[-1])
            if attempt < 3:
                return None, dc
            raise
        except (FileReferenceExpired, FileReferenceInvalid):
            if attempt < 3:
                return None, -1
            raise
        except (ConnectionError, OSError, TimeoutError):
            if attempt < 3:
                return None, -2
            raise

    async def _get_cdn_session(self, idx, cdn_dc, client):
        key = (idx, cdn_dc)
        s = self._cdn_sessions.get(key)
        if s and s.is_connected:
            return s
        tm = await client.storage.test_mode()
        ak = await Auth(client, cdn_dc, tm).create()
        s = Session(client, cdn_dc, ak, tm, is_media=True, is_cdn=True)
        await s.start()
        self._cdn_sessions[key] = s
        return s

    async def _cdnpull(self, idx, cdn_info, off, csz):
        client = self.clients[idx]
        cdn_dc = cdn_info["cdn_dc"]
        file_token = cdn_info["file_token"]
        enc_key = cdn_info["key"]
        enc_iv = cdn_info["iv"]
        sess = await self._get_cdn_session(idx, cdn_dc, client)

        for attempt in range(3):
            try:
                r = await sess.invoke(
                    raw.functions.upload.GetCdnFile(
                        file_token=file_token, offset=off, limit=csz,
                    ),
                    sleep_threshold=client.sleep_threshold,
                )
                if isinstance(r, raw.types.upload.CdnFile):
                    chunk = r.bytes
                    iv_mod = bytearray(
                        enc_iv[:-4] + (off // 16).to_bytes(4, "big")
                    )
                    return ctr256_decrypt(chunk, enc_key, iv_mod)
                if isinstance(r, raw.types.upload.CdnFileReuploadNeeded):
                    try:
                        await client.invoke(
                            raw.functions.upload.ReuploadCdnFile(
                                file_token=file_token,
                                request_token=r.request_token,
                            )
                        )
                    except Exception:
                        pass
                    await sleep(1)
                    continue
                raise ValueError(f"Unexpected CDN response: {type(r)}")
            except (FloodWait, FloodPremiumWait) as e:
                val = e.value if hasattr(e, "value") else 5
                LOGGER.warning(f"HypertgDL CDN flood {val}s dc={cdn_dc}")
                await sleep(val + 1)
            except FileTokenInvalid:
                LOGGER.warning(f"HypertgDL CDN FileTokenInvalid dc={cdn_dc} — fallback to non-CDN")
                self._cdn_info.pop(idx, None)
                return None
            except RequestTokenInvalid:
                LOGGER.warning(f"HypertgDL CDN RequestTokenInvalid dc={cdn_dc} — fallback to non-CDN")
                self._cdn_info.pop(idx, None)
                return None
            except (ConnectionError, OSError, TimeoutError) as e:
                LOGGER.warning(f"HypertgDL CDN {type(e).__name__}: {e} dc={cdn_dc}")
                if attempt < 2:
                    try:
                        await sess.stop()
                    except Exception:
                        pass
                    self._cdn_sessions.pop((idx, cdn_dc), None)
                    sess = await self._get_cdn_session(idx, cdn_dc, client)
                    await sleep(1)
        return None

    async def _pipeline_fetch(self, idx, location, start, end, fid, queue, csz):
        cname = self.clients[idx].me.username
        sess = await self._get_session(idx, fid.dc_id)
        loc = location
        first_off = start - (start % csz)
        first_trim = start - first_off
        last_byte = end - 1
        window = self.pipeline_depth
        min_win = _MIN_PIPELINE
        max_win = window * _MAX_PIPELINE_MULT
        inflight = set()
        _inflight_offsets = {}
        cur = first_off
        seq = 0
        ok_count = 0
        flood_count = 0
        timeout_count = 0
        pipe_timeouts = 0
        bot_down = False

        async def _req(off, s):
            nonlocal window, ok_count, flood_count, timeout_count, sess, loc, pipe_timeouts, bot_down
            if bot_down:
                return s, off, b""
            my_sess = sess
            my_loc = loc
            max_attempts = 1
            for attempt in range(max_attempts):
                try:
                    cdn = self._cdn_info.get(idx)
                    if cdn:
                        chunk = await self._cdnpull(idx, cdn, off, csz)
                        if chunk is not None:
                            return s, off, chunk
                    result = await self._do_req(my_sess, self.clients[idx], my_loc, off, csz, attempt)
                    if isinstance(result, tuple):
                        _, dc_or_ref = result
                        if isinstance(dc_or_ref, dict):
                            self._cdn_info[idx] = dc_or_ref
                            chunk = await self._cdnpull(idx, dc_or_ref, off, csz)
                            if chunk is not None:
                                return s, off, chunk
                            self._cdn_info.pop(idx, None)
                            await sleep(attempt + 1)
                            continue
                        if dc_or_ref == -1:
                            fid_new = await self._fetch_ref(idx, self.clients[idx], force=True)
                            my_loc = self._location(fid_new)
                            await sleep(attempt + 1)
                            continue
                        if dc_or_ref == -2:
                            if bot_down:
                                return s, off, b""
                            pipe_timeouts += 1
                            window = max(min_win, window - 1)
                            if pipe_timeouts >= 3:
                                bot_down = True
                                return s, off, b""
                            await sleep(min(3, pipe_timeouts))
                            continue
                        my_sess = await self._get_session(idx, dc_or_ref, force=True)
                        sess = my_sess
                        await sleep(attempt + 1)
                        continue
                    timeout_count = 0
                    return s, off, result
                except (FloodWait, FloodPremiumWait) as e:
                    flood_count += 1
                    val = e.value if hasattr(e, "value") else 5
                    if val > 10 or flood_count >= 3:
                        window = max(min_win, window - max(1, window // 4))
                        ok_count = 0
                        flood_count = 0
                        LOGGER.warning(
                            f"HypertgDL flood window={window} "
                            f"val={val}s client={cname} off={off}"
                        )
                    await sleep(val + 1)
                except CancelledError:
                    raise
            timeout_count += 1
            if timeout_count >= 3:
                window = max(min_win, window - max(1, window // 4))
                timeout_count = 0
                ok_count = 0
            return s, off, b""

        failed_offsets = set()
        try:
            while cur <= last_byte or inflight:
                if bot_down:
                    while inflight:
                        done_set, inflight = await wait(inflight, return_when=FIRST_COMPLETED)
                        for f in done_set:
                            try:
                                s, roff, chunk = f.result()
                                if not chunk:
                                    failed_offsets.add(roff)
                                    continue
                                if roff == first_off and roff + csz >= end:
                                    chunk = chunk[first_trim:last_byte - roff + 1]
                                    await queue.put((start, chunk))
                                elif roff == first_off:
                                    chunk = chunk[first_trim:]
                                    await queue.put((start, chunk))
                                elif roff + csz > end:
                                    chunk = chunk[:end - roff]
                                    await queue.put((roff, chunk))
                                else:
                                    await queue.put((roff, chunk))
                            except CancelledError:
                                raise
                            except Exception:
                                roff = _inflight_offsets.get(f)
                                if roff is not None:
                                    failed_offsets.add(roff)
                    remaining = []
                    c = cur
                    while c <= last_byte:
                        remaining.append(c)
                        c += csz
                    if remaining:
                        failed_offsets.update(remaining)
                    break
                while len(inflight) < window and cur <= last_byte:
                    if self._cancel.is_set():
                        raise CancelledError
                    f = ensure_future(_req(cur, seq))
                    _inflight_offsets[f] = cur
                    inflight.add(f)
                    cur += csz
                    seq += 1
                if not inflight:
                    break
                done_set, inflight = await wait(inflight, return_when=FIRST_COMPLETED)
                for f in done_set:
                    s, roff, chunk = f.result()
                    if not chunk:
                        failed_offsets.add(roff)
                        continue
                    ok_count += 1
                    if ok_count >= window:
                        window = min(window + 2, max_win)
                        ok_count = 0
                    if roff == first_off and roff + csz >= end:
                        chunk = chunk[first_trim:last_byte - roff + 1]
                        await queue.put((start, chunk))
                    elif roff == first_off:
                        chunk = chunk[first_trim:]
                        await queue.put((start, chunk))
                    elif roff + csz > end:
                        chunk = chunk[:end - roff]
                        await queue.put((roff, chunk))
                    else:
                        await queue.put((roff, chunk))
        except CancelledError:
            raise
        except Exception as e:
            if "Flood" in type(e).__name__:
                window = max(min_win, window // 2)
                ok_count = 0
            LOGGER.error(f"HypertgDL pipeline fail client={cname}: {e}")
            raise
        finally:
            for f in inflight:
                if not f.done():
                    f.cancel()
        return failed_offsets

    async def _part(self, start, end, final_path, ci, fid, csz):
        cname = self.clients[ci].me.username
        q = Queue(maxsize=self.pipeline_depth + 1)
        err = [None]
        failed_offsets = set()
        completed_offsets = set()

        async def _producer():
            nonlocal failed_offsets
            try:
                result = await self._pipeline_fetch(ci, self._location(fid), start, end, fid, q, csz)
                if isinstance(result, set):
                    failed_offsets = result
            except CancelledError:
                pass
            except Exception as e:
                err[0] = e
                LOGGER.error(f"HypertgDL part fail ci={ci} client={cname}: {e}")
            finally:
                await q.put(None)

        async def _consumer():
            fd = await to_thread(os.open, final_path, os.O_WRONLY)
            try:
                while True:
                    item = await q.get()
                    if item is None:
                        break
                    roff, chunk = item
                    await self._pwrite(fd, chunk, roff)
                    self._obj._processed_bytes += len(chunk)
                    completed_offsets.add(roff)
            except Exception as e:
                LOGGER.error(f"HypertgDL consumer err ci={ci}: {e}")
                raise
            finally:
                await to_thread(os.close, fd)

        prod = ensure_future(_producer())
        try:
            await _consumer()
            if err[0] is not None:
                if not failed_offsets:
                    first_off = start - (start % csz)
                    c = first_off
                    while c < end:
                        if c not in completed_offsets:
                            failed_offsets.add(c)
                        c += csz
                err[0].failed_offsets = failed_offsets
                raise err[0]
        except CancelledError:
            prod.cancel()
            raise
        except Exception:
            prod.cancel()
            raise
        finally:
            if not prod.done():
                prod.cancel()
        return failed_offsets

    @staticmethod
    async def _pwrite(fd, data, offset):
        total = len(data)
        written = 0
        while written < total:
            n = await to_thread(os.pwrite, fd, data[written:], offset + written)
            if n == 0:
                raise OSError(f"pwrite returned 0 at offset {offset + written}")
            written += n

    async def handle_download(self):
        self._cancel.clear()
        self._obj._processed_bytes = 0
        await makedirs(self.directory, exist_ok=True)
        final = os.path.abspath(sub("\\\\", "/", os.path.join(self.directory, self.file_name)))

        n_use = min(self.num_parts, self.num_clients)
        cidx = await _pick_clients(self.work_loads, self.clients, n_use)

        min_part = 1 * MB
        n_parts = min(n_use, max(1, self.file_size // min_part)) if self.file_size >= min_part else 1
        psz = self.file_size // n_parts if n_parts > 0 else self.file_size
        ranges = [(i * psz, min((i + 1) * psz, self.file_size)) for i in range(n_parts)]
        assigns = [cidx[i % n_use] for i in range(n_parts)]

        unique_clients = set(assigns)
        fid_map = {}
        try:
            for ci in unique_clients:
                fid_map[ci] = await self._fetch_ref(ci, self.clients[ci])
        except Exception as e:
            LOGGER.error(f"HypertgDL ref fail: {e}")
            return None

        first_fid = fid_map[assigns[0]]
        try:
            await self._warmup(unique_clients, first_fid.dc_id)
        except Exception as e:
            LOGGER.warning(f"HypertgDL warmup err: {e}")

        self._tasks = []
        try:
            fd = await to_thread(os.open, final, os.O_WRONLY | os.O_CREAT)
            try:
                pass  # placeholder for file descriptor opened above
            finally:
                await to_thread(os.close, fd)

            all_failed_offsets = set()
            for i, (s, e) in enumerate(ranges):
                self._tasks.append(
                    create_task(self._part(s, e, final, assigns[i], fid_map[assigns[i]], self.chunk_size))
                )

            results = await gather(*self._tasks, return_exceptions=True)
            bad_bots = set()
            for i, r in enumerate(results):
                if isinstance(r, BaseException):
                    LOGGER.error(f"HypertgDL part {i} failed: {r}")
                    bad_bots.add(assigns[i])
                    if hasattr(r, "failed_offsets") and r.failed_offsets:
                        all_failed_offsets.update(r.failed_offsets)
                    else:
                        s, e = ranges[i]
                        LOGGER.warning(
                            f"HypertgDL part {i} missing failed_offsets — "
                            f"retrying full range {s}-{e}"
                        )
                        all_failed_offsets.update(
                            range(s, e, self.chunk_size)
                        )
                elif isinstance(r, set) and r:
                    all_failed_offsets.update(r)
                    bad_bots.add(assigns[i])
            max_retries = 4
            for retry_round in range(max_retries):
                if not all_failed_offsets:
                    break

                await sleep(1)

                good_bots = sorted(
                    [i for i in self.clients.keys() if i not in bad_bots],
                    key=lambda i: self.work_loads.get(i, 0),
                )
                if not good_bots:
                    LOGGER.error("HypertgDL retry: no good bots remaining")
                    break

                range_buckets = {i: [] for i in range(len(ranges))}
                orphans = 0
                for off in all_failed_offsets:
                    matched = False
                    for i, (s, e) in enumerate(ranges):
                        if s <= off < e:
                            range_buckets[i].append(off)
                            matched = True
                            break
                    if not matched:
                        LOGGER.error(
                            f"HypertgDL retry: offset {off} outside all ranges"
                        )
                        range_buckets[0].append(off)
                        orphans += 1

                orphans_str = f" {orphans} orphans" if orphans else ""
                LOGGER.warning(
                    f"HypertgDL retry round {retry_round + 1}/{max_retries}: "
                    f"{len(all_failed_offsets)} failed offsets"
                    f"{orphans_str}"
                    f"{' (bad bots: ' + str(bad_bots) + ')' if bad_bots else ''}"
                )

                sorted_buckets = sorted(
                    [(i, offs) for i, offs in range_buckets.items() if offs],
                    key=lambda x: x[0],
                )
                assigned = set()
                bot_task_map = []
                still_failed = set()
                for i, bucket in sorted_buckets:
                    bot_idx = assigns[i]
                    if bot_idx in bad_bots or bot_idx in assigned:
                        for gb in good_bots:
                            if gb not in bad_bots and gb not in assigned:
                                bot_idx = gb
                                assigned.add(gb)
                                break
                        else:
                            still_failed |= set(bucket)
                            continue
                    else:
                        assigned.add(bot_idx)

                    if bot_idx not in fid_map:
                        try:
                            fid_map[bot_idx] = await self._fetch_ref(
                                bot_idx, self.clients[bot_idx]
                            )
                        except Exception:
                            bad_bots.add(bot_idx)
                            still_failed |= set(bucket)
                            continue
                    retry_start = min(bucket)
                    retry_end = min(
                        max(bucket) + self.chunk_size, self.file_size
                    )
                    task = create_task(
                        self._part(
                            retry_start, retry_end, final, bot_idx,
                            fid_map[bot_idx], self.chunk_size,
                        )
                    )
                    bot_task_map.append((bot_idx, bucket, task))

                if not bot_task_map:
                    LOGGER.error(
                        "HypertgDL retry: no bots available for retry"
                    )
                    break

                retry_results = await gather(
                    *[t for _, _, t in bot_task_map], return_exceptions=True
                )
                for (bot_idx, bucket, _), r in zip(bot_task_map, retry_results):
                    if isinstance(r, BaseException):
                        LOGGER.error(
                            f"HypertgDL retry ci={bot_idx} "
                            f"client={self.clients[bot_idx].me.username} "
                            f"failed: {r}"
                        )
                        if hasattr(r, "failed_offsets") and r.failed_offsets:
                            still_failed |= r.failed_offsets
                        else:
                            still_failed |= set(bucket)
                        bad_bots.add(bot_idx)
                    elif isinstance(r, set):
                        if r:
                            still_failed |= r
                            bad_bots.add(bot_idx)
                all_failed_offsets = still_failed

            if all_failed_offsets:
                n_bad = len(bad_bots)
                bad_detail = f" ({n_bad} bot{'s' if n_bad != 1 else ''} exhausted)" if n_bad else ""
                LOGGER.error(
                    f"HypertgDL {len(all_failed_offsets)} offsets still failed "
                    f"after {max_retries} retry rounds — file may be incomplete"
                    f"{bad_detail}"
                )

            return final
        except FloodWait:
            raise
        except (CancelledError, StopTransmission):
            return None
        except Exception as e:
            LOGGER.error(f"HypertgDL: {e}", exc_info=True)
            return None
        finally:
            self._cancel.set()
            for t in self._tasks:
                if not t.done():
                    t.cancel()
            if self._tasks:
                await gather(*self._tasks, return_exceptions=True)
            async with _load_lock:
                for k in cidx:
                    self.work_loads[k] = max(0, self.work_loads.get(k, 0) - 1)
            for s in self._cdn_sessions.values():
                try:
                    if s.is_connected:
                        await s.stop()
                except Exception:
                    pass
            self._cdn_sessions.clear()
            self._cdn_info.clear()
            await self._close_all()

    async def download_media(self, message, file_name="downloads/", dump_chat=None):
        try:
            if dump_chat and not isinstance(dump_chat, int):
                try:
                    dump_chat = int(dump_chat)
                except (ValueError, TypeError):
                    dump_chat = None
            if dump_chat:
                try:
                    self.message = await TgClient.bot.copy_message(
                        chat_id=dump_chat,
                        from_chat_id=message.chat.id,
                        message_id=message.id,
                        disable_notification=True,
                    )
                except Exception as e:
                    LOGGER.warning(f"HypertgDL copy fail: {e} (from={message.chat.id} to={dump_chat})")
                    raise RuntimeError(f"Cannot copy to dump chat: {e}") from e
            self.dump_chat = dump_chat or message.chat.id
            self.message = self.message or message
            media = self._media_of(self.message)
            fid_str = media if isinstance(media, str) else media.file_id
            fid_obj = FileId.decode(fid_str)
            ftype = fid_obj.file_type
            mname = media.file_name if hasattr(media, "file_name") else ""
            self.file_size = media.file_size if hasattr(media, "file_size") else 0
            mime = media.mime_type if hasattr(media, "mime_type") else "image/jpeg"
            dt = media.date if hasattr(media, "date") else None
            self.directory, self.file_name = os.path.split(file_name)
            self.file_name = self.file_name or mname or ""
            if not os.path.isabs(self.file_name):
                self.directory = Path(argv[0]).parent / (self.directory or self.download_dir)
            if not self.file_name:
                ext = self.get_extension(ftype, mime)
                self.file_name = (
                    f"{FileType(ftype).name.lower()}_"
                    f"{(dt or datetime.now()).strftime('%Y-%m-%d_%H-%M-%S')}_"
                    f"{MsgId()}{ext}"
                )
            return await self.handle_download()
        except Exception as e:
            LOGGER.error(f"HypertgDL download_media: {e}")
            raise

    @staticmethod
    def get_extension(file_type, mime_type):
        if file_type in PHOTO_TYPES:
            return ".jpg"
        if mime_type:
            e = guess_extension(mime_type)
            if e:
                return e
        return {
            FileType.VOICE: ".ogg",
            FileType.VIDEO: ".mp4",
            FileType.ANIMATION: ".mp4",
            FileType.VIDEO_NOTE: ".mp4",
            FileType.AUDIO: ".mp3",
            FileType.STICKER: ".webp",
        }.get(file_type, ".bin")
