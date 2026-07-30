"""Amaterasu's source-based TeraBox compatibility layer.

The public account API is provided by the pinned ``aioterabox`` dependency.
Public share links reuse Amaterasu's existing resolver, keeping this package
portable across Python versions and CPU architectures.
"""

from __future__ import annotations

import os
from asyncio import FIRST_COMPLETED, CancelledError, Event, create_task, to_thread, wait
from asyncio import gather as asyncio_gather
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import aiohttp
from aiofiles import open as aiopen
from aiofiles.os import makedirs
from aioterabox.api import TeraboxClient as _AccountClient

__version__ = "1.0.0-amaterasu"


class TeraboxError(Exception):
    pass


class TeraboxPasswordError(TeraboxError):
    pass


class TeraboxCancelled(TeraboxError):
    pass


@dataclass(slots=True)
class TeraboxFile:
    name: str
    path: str
    fs_id: str
    size: int = 0
    is_dir: bool = False
    url: str = ""
    headers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResolveResult:
    name: str
    file_entries: list[TeraboxFile]
    is_folder: bool


def _read_cookie_file(cookie_file: str) -> dict[str, str]:
    jar = MozillaCookieJar(cookie_file)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as error:
        raise TeraboxError(f"Invalid TeraBox cookies.txt file: {error}") from error
    cookies = {cookie.name: cookie.value for cookie in jar}
    aliases = {
        "jstoken": ("jstoken", "jsToken"),
        "csrfToken": ("csrfToken", "csrf_token"),
        "browserid": ("browserid",),
        "ndus": ("ndus",),
    }
    normalized = dict(cookies)
    for target, names in aliases.items():
        normalized[target] = next(
            (cookies[name] for name in names if cookies.get(name)),
            "",
        )
    # aioterabox requires all four keys to exist, but it refreshes jsToken and
    # csrfToken during ensure_logged_in(). Browser cookie exports commonly do
    # not contain those page-derived values, so only the authentication cookie
    # itself must be non-empty here.
    if not normalized["ndus"]:
        raise TeraboxError("TeraBox cookie is missing the required ndus value")
    return normalized


def _headers_dict(headers: list[str] | None) -> dict[str, str]:
    if isinstance(headers, str):
        headers = headers.splitlines()
    result = {}
    for header in headers or []:
        if ":" in header:
            key, value = header.split(":", 1)
            result[key.strip()] = value.strip()
    return result


class TeraboxClient:
    def __init__(self, cookie_file: str, session_path: str | None = None):
        del session_path
        self.cookie_file = cookie_file
        self._session: aiohttp.ClientSession | None = None
        self._client: _AccountClient | None = None
        self._created_directories: set[str] = set()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def login(self):
        cookies = await to_thread(_read_cookie_file, self.cookie_file)
        await self._ensure_session()
        self._client = _AccountClient("", "", self._session, cookies=cookies)
        try:
            await self._client.ensure_logged_in()
        except Exception as error:
            await self.aclose()
            raise TeraboxError(f"TeraBox login failed: {error}") from error

    async def ensure_upload_ready(self):
        if self._client is None:
            await self.login()
        return await self._client.get_storage_quota()

    async def list_account_dir(self, path: str):
        try:
            entries = await self._client.list_remote_directory(path)
            return [
                TeraboxFile(
                    name=entry.name,
                    path=entry.path,
                    fs_id=entry.path,
                    size=int(entry.size or 0),
                    is_dir=bool(entry.is_dir),
                )
                for entry in entries
            ]
        except Exception as error:
            raise TeraboxError(str(error)) from error

    async def walk_account_dir(self, path: str):
        files = []
        pending = [path or "/"]
        while pending:
            current = pending.pop()
            for entry in await self.list_account_dir(current):
                if entry.is_dir:
                    pending.append(entry.path)
                else:
                    files.append(entry)
        name = os.path.basename((path or "/").rstrip("/")) or "TeraBox"
        return ResolveResult(name, files, True)

    async def region_list_dir(self, path: str):
        return [
            {
                "server_filename": entry.name,
                "path": entry.path,
                "fs_id": entry.fs_id,
                "size": entry.size,
                "isdir": int(entry.is_dir),
            }
            for entry in await self.list_account_dir(path)
        ]

    async def resolve(self, link: str, recursive: bool = True):
        del recursive
        await self._ensure_session()
        try:
            from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import (
                terabox as resolve_share,
            )

            resolved = await to_thread(resolve_share, link, self.cookie_file)
        except Exception as error:
            if "password" in str(error).lower():
                raise TeraboxPasswordError(str(error)) from error
            raise TeraboxError(str(error)) from error

        if isinstance(resolved, str):
            name = Path(resolved.split("?", 1)[0]).name or "TeraBox"
            size = await self._remote_size(resolved)
            files = [TeraboxFile(name, name, name, size=size, url=resolved)]
            return ResolveResult(name, files, False)
        if isinstance(resolved, tuple):
            url, headers = resolved
            name = Path(str(url).split("?", 1)[0]).name or "TeraBox"
            size = await self._remote_size(url, headers)
            files = [
                TeraboxFile(
                    name,
                    name,
                    name,
                    size=size,
                    url=url,
                    headers=headers,
                )
            ]
            return ResolveResult(name, files, False)

        contents = resolved.get("contents", [])
        root = resolved.get("title") or "TeraBox"
        files = []
        for index, item in enumerate(contents):
            name = item.get("filename") or f"file_{index + 1}"
            path = "/".join(
                part.strip("/")
                for part in (item.get("path", ""), name)
                if part and part.strip("/")
            )
            files.append(
                TeraboxFile(
                    name=name,
                    path=f"/{path}",
                    fs_id=str(index),
                    size=int(item.get("size", 0) or 0),
                    url=item.get("url", ""),
                    headers=item.get("headers") or resolved.get("header") or [],
                )
            )
        return ResolveResult(root, files, len(files) > 1)

    async def _remote_size(self, url: str, headers=None) -> int:
        try:
            async with self._session.head(
                url,
                headers=_headers_dict(headers),
                allow_redirects=True,
            ) as response:
                return int(response.headers.get("Content-Length", 0) or 0)
        except Exception:
            return 0

    async def reserve_files(self, destinations):
        for destination, _size in destinations:
            await makedirs(os.path.dirname(destination), exist_ok=True)

    async def download_file(
        self,
        file: TeraboxFile,
        destination: str,
        *,
        progress_cb=None,
        cancel_event: Event | None = None,
    ):
        try:
            url = file.url
            if not url:
                metadata = await self._client.get_files_meta([file.path])
                if not metadata:
                    raise TeraboxError(f"No download URL for {file.name}")
                url = metadata[0]["dlink"]
            headers = _headers_dict(file.headers)
            async with self._session.get(url, headers=headers) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", file.size) or 0)
                done = 0
                async with aiopen(destination, "wb") as output:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        if cancel_event and cancel_event.is_set():
                            raise TeraboxCancelled("Transfer cancelled")
                        await output.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
        except TeraboxCancelled:
            raise
        except Exception as error:
            raise TeraboxError(str(error)) from error

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        *,
        progress_cb=None,
        cancel_event: Event | None = None,
    ):
        remote_path = f"/{remote_path.lstrip('/')}"
        remote_dir = os.path.dirname(remote_path).replace("\\", "/")
        if remote_dir and remote_dir != "/" and remote_dir not in self._created_directories:
            try:
                await self._client.create_directory(remote_dir)
            except Exception as error:
                # TeraBox reports an error when the directory already exists.
                # Confirm that case by listing the parent instead of hiding
                # unrelated permission or API failures.
                parent = os.path.dirname(remote_dir.rstrip("/")) or "/"
                directory_name = os.path.basename(remote_dir.rstrip("/"))
                try:
                    entries = await self._client.list_remote_directory(parent)
                except Exception:
                    raise TeraboxError(
                        f"Unable to create TeraBox directory {remote_dir}: {error}"
                    ) from error
                if not any(
                    entry.is_dir and entry.name == directory_name for entry in entries
                ):
                    raise TeraboxError(
                        f"Unable to create TeraBox directory {remote_dir}: {error}"
                    ) from error
            self._created_directories.add(remote_dir)

        task = create_task(self._client.upload_file(local_path, remote_path))
        cancel_task = None
        if cancel_event:
            cancel_task = create_task(cancel_event.wait())
            done, _ = await wait(
                (task, cancel_task),
                return_when=FIRST_COMPLETED,
            )
            if cancel_task in done and cancel_event.is_set() and not task.done():
                task.cancel()
                await asyncio_gather(task, return_exceptions=True)
                raise TeraboxCancelled("Transfer cancelled")
            cancel_task.cancel()
        try:
            result = await task
        except CancelledError as error:
            raise TeraboxCancelled("Transfer cancelled") from error
        finally:
            if cancel_task and not cancel_task.done():
                cancel_task.cancel()
            if cancel_task:
                await asyncio_gather(cancel_task, return_exceptions=True)
        if progress_cb:
            size = os.path.getsize(local_path)
            progress_cb(size, size)
        return result

    async def create_share_link(self, file_ids, paths):
        del file_ids, paths
        return ""

    async def aclose(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._client = None
        self._created_directories.clear()


__all__ = [
    "ResolveResult",
    "TeraboxCancelled",
    "TeraboxClient",
    "TeraboxError",
    "TeraboxFile",
    "TeraboxPasswordError",
    "__version__",
]
