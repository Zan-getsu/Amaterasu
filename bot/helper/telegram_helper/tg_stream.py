"""Adaptive Telegram range streaming for FileToLink.

This is a compatibility-focused port of WZML-X's streaming pipeline.  It uses
WZGram's existing media-session pool, so Amaterasu keeps one source of truth
for authentication, connection lifecycle, and WarpCrypto acceleration.
"""

from asyncio import (
    FIRST_COMPLETED,
    CancelledError,
    ensure_future,
    gather,
    get_running_loop,
    shield,
    sleep,
    wait,
    wait_for,
)
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from inspect import isawaitable
from logging import getLogger

from pyrogram import raw, utils
from pyrogram.errors import (
    FileMigrate,
    FileReferenceExpired,
    FileReferenceInvalid,
    FloodWait,
)
from pyrogram.file_id import FileId, FileType, ThumbnailSource

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:  # pragma: no cover - older compatible WZGram fallback
    FloodPremiumWait = FloodWait


LOGGER = getLogger(__name__)

KB = 1024
MIN_ALIGN = 4 * KB
MAX_CHUNK = 1024 * KB
_MAX_CLIENTS = 4
_MAX_PULL_ATTEMPTS = 3
_INFLIGHT_CHUNKS = {}
_BACKGROUND_TASKS = set()


class AdaptiveStreamUnavailable(RuntimeError):
    """The direct MTProto backend cannot be used before response bytes start."""


class AdaptiveStreamError(OSError):
    """A range could not be completed after bounded retry and failover."""


@dataclass(frozen=True)
class StreamProfile:
    name: str
    first_chunk: int
    max_chunk: int
    window: int
    max_window: int
    client_count: int
    invoke_timeout: float
    sleep_threshold: int


@dataclass
class _ClientState:
    client_id: int
    client: object
    file_id: object
    location: object
    dc_id: int
    sessions: list
    session_cursor: int = 0


def build_profile(kind: str, concurrency: int, prefetch: int) -> StreamProfile:
    """Build bounded WZML-X-style playback and bulk transfer profiles."""
    concurrency = min(max(int(concurrency or 1), 1), 32)
    prefetch = min(max(int(prefetch or 1), 1), concurrency)
    if kind == "bulk":
        return StreamProfile(
            name="bulk",
            first_chunk=MAX_CHUNK,
            max_chunk=MAX_CHUNK,
            window=concurrency,
            max_window=concurrency,
            client_count=_MAX_CLIENTS,
            invoke_timeout=15.0,
            sleep_threshold=10,
        )
    initial_window = min(4, prefetch, concurrency)
    return StreamProfile(
        name="playback",
        first_chunk=32 * KB,
        max_chunk=512 * KB,
        window=initial_window,
        max_window=min(concurrency, initial_window * 3),
        client_count=1,
        invoke_timeout=8.0,
        sleep_threshold=0,
    )


def _next_power_of_two(value: int) -> int:
    return 1 << (value - 1).bit_length() if value > 1 else 1


def plan_chunks(
    start: int,
    end_exclusive: int,
    profile: StreamProfile,
) -> list[tuple[int, int]]:
    """Plan Telegram-valid aligned chunks with a latency-first first read."""
    position = start - (start % MIN_ALIGN)
    chunks = []
    while position < end_exclusive:
        size = (position & -position) or profile.max_chunk
        size = min(
            size,
            profile.max_chunk,
            max(MIN_ALIGN, _next_power_of_two(end_exclusive - position)),
        )
        if not chunks:
            size = min(size, profile.first_chunk)
        size = max(MIN_ALIGN, size)
        chunks.append((position, size))
        position += size
    return chunks


def inflight_chunk_count() -> int:
    return len(_INFLIGHT_CHUNKS)


def _consume_exception(future) -> None:
    if not future.cancelled():
        future.exception()


def _drain_in_background(tasks, timeout: float) -> None:
    pending = list(tasks)
    tasks.clear()
    if not pending:
        return

    async def drain():
        with suppress(Exception):
            await wait_for(
                gather(*pending, return_exceptions=True),
                timeout=timeout + 5,
            )

    task = ensure_future(drain())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _media_of(message):
    for attribute in (
        "audio",
        "document",
        "photo",
        "sticker",
        "animation",
        "video",
        "voice",
        "video_note",
        "new_chat_photo",
    ):
        media = getattr(message, attribute, None)
        if media is not None:
            return media
    raise AdaptiveStreamUnavailable("message does not contain downloadable media")


def _location(file_id):
    """Create a WZGram 3.1.0-compatible raw input file location."""
    if file_id.file_type == FileType.CHAT_PHOTO:
        if file_id.chat_id > 0:
            peer = raw.types.InputPeerUser(
                user_id=file_id.chat_id,
                access_hash=file_id.chat_access_hash,
            )
        elif file_id.chat_access_hash == 0:
            peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
        else:
            peer = raw.types.InputPeerChannel(
                channel_id=utils.get_channel_id(file_id.chat_id),
                access_hash=file_id.chat_access_hash,
            )
        return raw.types.InputPeerPhotoFileLocation(
            peer=peer,
            photo_id=file_id.media_id,
            big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
        )
    if file_id.file_type == FileType.PHOTO:
        return raw.types.InputPhotoFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size=file_id.thumbnail_size,
        )
    return raw.types.InputDocumentFileLocation(
        id=file_id.media_id,
        access_hash=file_id.access_hash,
        file_reference=file_id.file_reference,
        thumb_size=file_id.thumbnail_size,
    )


async def _notify(callback: Callable | None, *args) -> None:
    if callback is None:
        return
    result = callback(*args)
    if isawaitable(result):
        await result


class AdaptiveTelegramStream:
    """Serve one exact byte range through an adaptive ordered MTProto pipeline."""

    def __init__(
        self,
        *,
        chat_id: int,
        message_id: int,
        clients: dict[int, object],
        primary_client_id: int,
        primary_message,
        profile: StreamProfile,
        on_failure: Callable | None = None,
    ):
        self.chat_id = chat_id
        self.message_id = message_id
        self.clients = dict(clients)
        self.primary_client_id = primary_client_id
        self.primary_message = primary_message
        self.profile = profile
        self.on_failure = on_failure
        self.unique_id = ""
        self.file_size = 0
        self._states = []
        self._closed = False
        self.used_client_ids = set()
        self.failed_client_ids = set()
        self.peak_window = profile.window

    async def open(self):
        """Resolve fresh per-client file references and shared media sessions."""
        ordered_clients = sorted(
            self.clients.items(),
            key=lambda item: item[0] != self.primary_client_id,
        )[: self.profile.client_count]
        states = []
        for client_id, client in ordered_clients:
            try:
                message = (
                    self.primary_message
                    if client_id == self.primary_client_id
                    else await client.get_messages(self.chat_id, self.message_id)
                )
                state = await self._state_from_message(client_id, client, message)
                if self.file_size and state.file_id.file_size:
                    if int(state.file_id.file_size) != self.file_size:
                        raise AdaptiveStreamUnavailable(
                            "stream workers resolved different media sizes"
                        )
                else:
                    self.file_size = int(state.file_id.file_size or 0)
                self.unique_id = self.unique_id or str(
                    getattr(state.file_id, "unique_id", "") or ""
                )
                states.append(state)
            except CancelledError:
                raise
            except Exception as error:
                self.failed_client_ids.add(client_id)
                await _notify(self.on_failure, client_id, str(error), 30)
                LOGGER.warning(
                    "Adaptive stream worker %s could not open %s/%s: %s",
                    client_id,
                    self.chat_id,
                    self.message_id,
                    error,
                )
        if not states:
            raise AdaptiveStreamUnavailable("no stream worker could open the media")
        self._states = states
        return self

    async def _state_from_message(self, client_id, client, message):
        if message is None or getattr(message, "empty", False):
            raise AdaptiveStreamUnavailable("media message is unavailable")
        media = _media_of(message)
        file_id = FileId.decode(media.file_id)
        file_id.file_size = int(getattr(media, "file_size", 0) or 0)
        file_id.unique_id = getattr(media, "file_unique_id", "") or ""
        requested_sessions = min(max(self.profile.window, 1), 4)
        try:
            sessions = await client._get_media_session_pool(
                file_id.dc_id,
                requested_sessions,
            )
        except (AttributeError, TypeError):
            sessions = [await client.get_session(file_id.dc_id, is_media=True)]
        sessions = [
            session
            for session in sessions
            if getattr(session, "is_started", None) is None
            or session.is_started.is_set()
        ]
        if not sessions:
            sessions = [await client.get_session(file_id.dc_id, is_media=True)]
        return _ClientState(
            client_id=client_id,
            client=client,
            file_id=file_id,
            location=_location(file_id),
            dc_id=file_id.dc_id,
            sessions=sessions,
        )

    async def _refresh_state(self, state: _ClientState) -> None:
        message = await state.client.get_messages(self.chat_id, self.message_id)
        refreshed = await self._state_from_message(
            state.client_id,
            state.client,
            message,
        )
        state.file_id = refreshed.file_id
        state.location = refreshed.location
        state.dc_id = refreshed.dc_id
        state.sessions = refreshed.sessions
        state.session_cursor = 0

    async def _reset_sessions(self, state: _ClientState, reason: str) -> None:
        reset = getattr(state.client, "reset_media_session_pool", None)
        if reset is not None:
            with suppress(Exception):
                await reset(state.dc_id, reason=reason)
        try:
            state.sessions = await state.client._get_media_session_pool(
                state.dc_id,
                min(max(self.profile.window, 1), 4),
            )
        except Exception:
            state.sessions = [
                await state.client.get_session(state.dc_id, is_media=True)
            ]
        state.session_cursor = 0

    async def _pull_from_state(
        self,
        state: _ClientState,
        offset: int,
        limit: int,
    ) -> bytes:
        refreshes = 0
        for attempt in range(1, _MAX_PULL_ATTEMPTS + 1):
            if self._closed:
                raise AdaptiveStreamError("stream closed")
            try:
                session = state.sessions[state.session_cursor % len(state.sessions)]
                state.session_cursor += 1
                response = await session.invoke(
                    raw.functions.upload.GetFile(
                        precise=True,
                        cdn_supported=False,
                        location=state.location,
                        offset=offset,
                        limit=limit,
                    ),
                    timeout=self.profile.invoke_timeout,
                    sleep_threshold=self.profile.sleep_threshold,
                )
                if isinstance(response, raw.types.upload.File):
                    return response.bytes
                if isinstance(response, raw.types.upload.FileCdnRedirect):
                    raise ConnectionError("unexpected Telegram CDN redirect")
                raise AdaptiveStreamError(
                    f"unexpected GetFile response {type(response).__name__}"
                )
            except (FileReferenceExpired, FileReferenceInvalid):
                if refreshes >= 2:
                    raise AdaptiveStreamError(
                        "Telegram file reference kept expiring"
                    ) from None
                refreshes += 1
                await self._refresh_state(state)
            except FileMigrate as error:
                state.dc_id = error.value
                await self._reset_sessions(state, "media DC migration")
            except (FloodWait, FloodPremiumWait):
                raise
            except CancelledError:
                raise
            except (ConnectionError, OSError, TimeoutError) as error:
                if attempt >= _MAX_PULL_ATTEMPTS:
                    raise
                # Rotate through the existing WZGram pool first. Resetting a
                # shared pool on a single socket hiccup would interrupt other
                # healthy transfers using the same client.
                if attempt > 1:
                    await self._reset_sessions(state, str(error))
                await sleep(min(2 ** (attempt - 1), 2))
        raise AdaptiveStreamError("Telegram GetFile retry budget exhausted")

    async def _pull(self, preferred_state, offset: int, limit: int) -> bytes:
        states = [preferred_state]
        states.extend(state for state in self._states if state is not preferred_state)
        last_error = None
        for state in states:
            try:
                data = await self._pull_from_state(state, offset, limit)
                self.used_client_ids.add(state.client_id)
                return data
            except CancelledError:
                raise
            except (FloodWait, FloodPremiumWait) as error:
                last_error = error
                self.failed_client_ids.add(state.client_id)
                cooldown = max(int(getattr(error, "value", 1)), 1)
                await _notify(
                    self.on_failure,
                    state.client_id,
                    f"FloodWait {cooldown}s",
                    cooldown,
                )
                if len(states) == 1 and cooldown <= 5:
                    await sleep(cooldown + 1)
                    try:
                        data = await self._pull_from_state(state, offset, limit)
                        self.used_client_ids.add(state.client_id)
                        return data
                    except CancelledError:
                        raise
                    except Exception as retry_error:
                        last_error = retry_error
            except Exception as error:
                last_error = error
                self.failed_client_ids.add(state.client_id)
                await _notify(self.on_failure, state.client_id, str(error), 30)
        raise AdaptiveStreamError(
            f"all reserved stream workers failed at byte {offset}: {last_error}"
        ) from last_error

    async def _fetch(self, preferred_state, offset: int, limit: int) -> bytes:
        key = (
            self.unique_id or f"{self.chat_id}:{self.message_id}",
            offset,
            limit,
        )
        shared = _INFLIGHT_CHUNKS.get(key)
        if shared is not None:
            try:
                return await shield(shared)
            except Exception as error:
                LOGGER.debug("Shared adaptive chunk failed; refetching: %s", error)

        future = get_running_loop().create_future()
        future.add_done_callback(_consume_exception)
        _INFLIGHT_CHUNKS[key] = future
        try:
            data = await self._pull(preferred_state, offset, limit)
            if not future.done():
                future.set_result(data)
            return data
        except BaseException as error:
            if not future.done():
                future.set_exception(error)
            raise
        finally:
            if _INFLIGHT_CHUNKS.get(key) is future:
                _INFLIGHT_CHUNKS.pop(key, None)
            if not future.done():
                future.cancel()

    async def iter_range(self, start: int, end_inclusive: int):
        if not self._states:
            raise AdaptiveStreamUnavailable("adaptive stream was not opened")
        end_exclusive = end_inclusive + 1
        plan = plan_chunks(start, end_exclusive, self.profile)
        window = self.profile.window
        inflight = {}
        ready = {}
        next_index = 0
        launch_index = 0
        successful_in_window = 0
        sent = 0
        try:
            while next_index < len(plan):
                while (
                    len(inflight) + len(ready) < window
                    and launch_index < len(plan)
                ):
                    offset, limit = plan[launch_index]
                    state = self._states[launch_index % len(self._states)]
                    task = ensure_future(self._fetch(state, offset, limit))
                    inflight[task] = launch_index
                    launch_index += 1
                self.peak_window = max(
                    self.peak_window,
                    len(inflight) + len(ready),
                )

                while next_index not in ready:
                    if not inflight:
                        raise AdaptiveStreamError(
                            "adaptive pipeline stalled without pending work"
                        )
                    done, _ = await wait(
                        set(inflight),
                        return_when=FIRST_COMPLETED,
                    )
                    for task in done:
                        ready[inflight.pop(task)] = task.result()

                data = ready.pop(next_index)
                offset, limit = plan[next_index]
                next_index += 1
                successful_in_window += 1
                if (
                    successful_in_window >= window
                    and window < self.profile.max_window
                ):
                    window += 1
                    successful_in_window = 0

                left = max(start, offset) - offset
                right = min(end_exclusive, offset + limit) - offset
                if len(data) < right:
                    raise AdaptiveStreamError(
                        f"short Telegram chunk at {offset}: {len(data)}/{right} bytes"
                    )
                piece = data if left == 0 and right == len(data) else data[left:right]
                if piece:
                    sent += len(piece)
                    yield piece

            expected = end_exclusive - start
            if sent != expected:
                raise AdaptiveStreamError(
                    f"range length mismatch: streamed {sent}/{expected} bytes"
                )
        finally:
            self._closed = True
            _drain_in_background(inflight, self.profile.invoke_timeout)
            ready.clear()


async def shutdown_adaptive_streams() -> None:
    pending = [task for task in _BACKGROUND_TASKS if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await gather(*pending, return_exceptions=True)
    _BACKGROUND_TASKS.clear()
    _INFLIGHT_CHUNKS.clear()
