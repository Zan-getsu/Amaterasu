"""Amaterasu's source-based TeraBox compatibility layer.

The public account API is provided by the pinned ``aioterabox`` dependency.
Public share links reuse Amaterasu's existing resolver, keeping this package
portable across Python versions and CPU architectures.
"""

from __future__ import annotations

import json
import os
from asyncio import FIRST_COMPLETED, CancelledError, Event, create_task, to_thread, wait
from asyncio import gather as asyncio_gather
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import md5
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from re import compile as re_compile
from urllib.parse import urlsplit

import aiohttp
from aiofiles import open as aiopen
from aiofiles import tempfile as aiotempfile
from aiofiles.os import makedirs
from aioterabox.api import CHUNK_SIZE as _SDK_CHUNK_SIZE
from aioterabox.api import MAX_UNCHUNKED_FILE_SIZE as _SDK_UNCHUNKED_LIMIT
from aioterabox.api import TeraboxClient as _AccountClient
from aioterabox.exceptions import TeraboxApiError as _SdkApiError
from aioterabox.exceptions import TeraboxUnauthorizedError as _SdkUnauthorizedError

__version__ = "1.0.0-amaterasu"

_DEFAULT_ACCOUNT_BASE_URL = "https://www.terabox.com"
_REGION_PREFIX = re_compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NON_REGIONAL_COOKIE_PREFIXES = {"www", "d", "data", "s3", "static"}
_REGIONAL_ACCOUNT_DOMAINS = ("terabox.com", "1024terabox.com")
_FREE_MAX_FILE_SIZE = 4 * 1024**3
_VIP_MAX_FILE_SIZE = 20 * 1024**3 - 1


class TeraboxError(Exception):
    pass


class TeraboxPasswordError(TeraboxError):
    pass


class TeraboxCancelled(TeraboxError):
    pass


class _CookieData(dict):
    """Cookie mapping plus non-secret routing metadata from the export."""

    def __init__(self, *args, region_hint: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.region_hint = region_hint


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
    except Exception:
        raise TeraboxError(
            "Invalid TeraBox cookies.txt file: expected a Netscape-format export"
        ) from None
    records = list(jar)
    cookies = {cookie.name: cookie.value for cookie in records}
    aliases = {
        "jstoken": ("jstoken", "jsToken"),
        "csrfToken": ("csrfToken", "csrf_token"),
        "browserid": ("browserid",),
        "ndus": ("ndus",),
    }
    normalized = _CookieData(cookies, region_hint=_cookie_region_hint(records))
    for target, names in aliases.items():
        normalized[target] = next(
            (cookies[name] for name in names if cookies.get(name)),
            "",
        )
    # aioterabox requires all four keys to exist. Browser cookie exports commonly
    # omit the page-derived values, so only the authentication cookie itself must
    # be non-empty before the explicit bootstrap performed by login().
    if not normalized["ndus"]:
        raise TeraboxError("TeraBox cookie is missing the required ndus value")
    return normalized


def _cookie_region_hint(records) -> str | None:
    """Infer a safe regional prefix from cookie domains without reading values."""
    for cookie in records:
        domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
        for root in ("terabox.com", "1024terabox.com"):
            suffix = "." + root
            if not domain.endswith(suffix):
                continue
            prefix = domain[: -len(suffix)]
            if (
                "." not in prefix
                and prefix not in _NON_REGIONAL_COOKIE_PREFIXES
                and _regional_base_url(prefix)
            ):
                return prefix
    return None


def _regional_base_url(
    prefix: str | None,
    domain: str = _REGIONAL_ACCOUNT_DOMAINS[0],
) -> str | None:
    """Return a safe account API origin from TeraBox's regional-prefix header."""
    normalized = (prefix or "").strip().lower()
    if domain not in _REGIONAL_ACCOUNT_DOMAINS or not _REGION_PREFIX.fullmatch(
        normalized
    ):
        return None
    return f"https://{normalized}.{domain}"


def _is_rejected_session(error: Exception) -> bool:
    if isinstance(error, _SdkUnauthorizedError):
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in ("errno': -6", 'errno": -6', "user not login", "invalid cookies")
    )


def _bootstrap_failure_reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "request timed out"
    if isinstance(error, aiohttp.ClientResponseError):
        return f"HTTP {error.status}"
    if isinstance(error, aiohttp.ClientError):
        return "network request failed"
    if isinstance(error, (AttributeError, KeyError, TypeError, ValueError)):
        return "response format was not recognized"
    return "SDK bootstrap request failed"


def _terabox_proxy_url() -> str | None:
    proxy_url = os.getenv("TERABOX_PROXY", "").strip()
    if not proxy_url:
        return None
    parsed = urlsplit(proxy_url)
    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        return proxy_url
    return None


class _RegionalAccountClient(_AccountClient):
    """Make the SDK's hard-coded account origin per-client and region-aware."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = _DEFAULT_ACCOUNT_BASE_URL
        self.detected_region_prefix: str | None = None
        self.proxy_url = _terabox_proxy_url()

    def use_region(self, prefix: str | None, *, alternate: bool = False) -> bool:
        domain = _REGIONAL_ACCOUNT_DOMAINS[1 if alternate else 0]
        base_url = _regional_base_url(prefix, domain)
        if not base_url or base_url == self.base_url:
            return False
        self.base_url = base_url
        self._base_headers["Origin"] = base_url
        self._base_headers["Referer"] = base_url + "/main"
        self.account["account_id"] = None
        self.is_vip = None
        self._signb = None
        self._public_key = None
        return True

    def _remember_region(self, prefix: str | None):
        if _regional_base_url(prefix):
            self.detected_region_prefix = prefix.strip().lower()

    def _rewrite_url(self, value: str) -> str:
        if value == _DEFAULT_ACCOUNT_BASE_URL:
            return self.base_url
        if value.startswith(_DEFAULT_ACCOUNT_BASE_URL + "/"):
            return self.base_url + value[len(_DEFAULT_ACCOUNT_BASE_URL) :]
        return value

    @asynccontextmanager
    async def _request(self, method: str, url: str, *, headers=None, **kwargs):
        if self.proxy_url and "proxy" not in kwargs:
            kwargs["proxy"] = self.proxy_url
        rewritten_headers = {
            key: self._rewrite_url(value) if isinstance(value, str) else value
            for key, value in (headers or {}).items()
        }
        async with super()._request(
            method,
            self._rewrite_url(url),
            headers=rewritten_headers,
            **kwargs,
        ) as response:
            self._remember_region(response.headers.get("Url-Domain-Prefix"))
            yield response

    async def get_max_file_size(self) -> int:
        """Correct aioterabox 0.2.3's reversed free/VIP size limits."""
        return _VIP_MAX_FILE_SIZE if await self.check_vip_status() else _FREE_MAX_FILE_SIZE

    async def upload_file(self, filename: str, destination_path: str) -> dict:
        """Upload every chunk, including the SDK's previously omitted remainder."""
        destination_path = f"/{destination_path.lstrip('/')}"
        file_size = await to_thread(os.path.getsize, filename)
        max_file_size = await self.get_max_file_size()
        if file_size > max_file_size:
            raise ValueError(
                f"File size {file_size} exceeds maximum allowed size of "
                f"{max_file_size} bytes."
            )

        async with aiotempfile.TemporaryDirectory() as tmpdir:
            chunks = []
            async with aiopen(filename, "rb") as source:
                if file_size > _SDK_UNCHUNKED_LIMIT:
                    index = 0
                    while data := await source.read(_SDK_CHUNK_SIZE):
                        chunk_path = os.path.join(
                            tmpdir,
                            f"{os.path.basename(destination_path)}.part{index:03d}",
                        )
                        async with aiopen(chunk_path, "wb") as chunk_file:
                            await chunk_file.write(data)
                        chunks.append(
                            (
                                chunk_path,
                                len(data),
                                md5(data, usedforsecurity=False).hexdigest(),
                            )
                        )
                        index += 1
                else:
                    chunks.append(
                        (filename, file_size, await self.file_md5(source))
                    )

            if sum(chunk_size for _path, chunk_size, _digest in chunks) != file_size:
                raise TeraboxError(
                    "TeraBox upload preparation did not preserve the complete file"
                )

            upload_host = await self._locate_upload_host()
            md5_list = [digest for _path, _size, digest in chunks]
            try:
                upload_id = await self._precreate_file(destination_path, md5_list)
            except _SdkUnauthorizedError:
                await self.refresh_cookies()
                upload_id = await self._precreate_file(destination_path, md5_list)

            await self._upload_chunks(
                upload_host=upload_host,
                remote_path=destination_path,
                uploadid=upload_id,
                file_chunks_md5=chunks,
            )
            return await self._postcreate_file(
                remote_path=destination_path,
                uploadid=upload_id,
                file_size=file_size,
                md5_list_json=md5_list,
            )

    async def _upload_chunks(
        self,
        *,
        upload_host: str,
        remote_path: str,
        uploadid: str,
        file_chunks_md5: list[tuple[str, int, str]],
        concurrency: int = 1,
    ) -> list[dict]:
        """Upload chunks without leaving SDK-created child tasks behind.

        aioterabox 0.2.3 creates one task per chunk with ``asyncio.gather``.
        When a child fails, other children can outlive the caller, temporary
        chunk directory, and HTTP session.  Keep the transfer sequential so a
        failure or cancellation is fully settled before cleanup can begin.
        """
        del concurrency
        results = []
        for partseq, (chunk_path, chunk_size, chunk_md5) in enumerate(
            file_chunks_md5
        ):
            if not await to_thread(os.path.isfile, chunk_path):
                raise TeraboxError(
                    f"Prepared TeraBox upload chunk {partseq + 1} is no longer "
                    "available; the transfer was stopped before cleanup"
                )
            results.append(
                await self._upload_file_chunk(
                    upload_host=upload_host,
                    filename=chunk_path,
                    filesize=chunk_size,
                    remote_path=remote_path,
                    chunk_md5=chunk_md5,
                    uploadid=uploadid,
                    partseq=partseq,
                )
            )
        return results

    async def _postcreate_file(
        self,
        remote_path: str,
        uploadid: str,
        file_size: int,
        md5_list_json: list[str],
    ) -> dict:
        """Finalize an upload without logging jsToken or emitting a root `//`."""
        remote_dir = os.path.dirname(remote_path).rstrip("/") or "/"
        target_path = remote_dir if remote_dir == "/" else remote_dir + "/"
        data = {
            "isdir": "0",
            "rtype": "1",
            "app_id": "250528",
            "jsToken": self.js_token,
            "path": remote_path,
            "uploadid": uploadid,
            "target_path": target_path,
            "size": str(file_size),
            "block_list": json.dumps(md5_list_json),
        }
        async with self._request(
            "POST",
            f"{_DEFAULT_ACCOUNT_BASE_URL}/api/create",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            timeout=10,
        ) as response:
            result = await response.json()
        if result.get("errno") == 0:
            return result
        code = result.get("errno", "unknown")
        message = str(result.get("errmsg") or result.get("msg") or "unknown")[:120]
        raise _SdkApiError(
            f"TeraBox file create failed (errno={code}, message={message})"
        )


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
        region_hint = getattr(cookies, "region_hint", None)
        await self._ensure_session()
        try:
            self._client = _RegionalAccountClient("", "", self._session, cookies=cookies)
            regional = bool(region_hint)
            regional_prefix = region_hint
            alternate = False
            if regional:
                alternate = await self._bootstrap_regional_session(regional_prefix)
            else:
                await self._bootstrap_session()
            try:
                await self._validate_session(regional=regional)
            except Exception as first_error:
                if regional:
                    if isinstance(first_error, TeraboxError):
                        raise first_error
                    if alternate or not regional_prefix:
                        raise first_error
                    await self._bootstrap_alternate_regional_session(regional_prefix)
                    await self._validate_session(regional=True)
                    return
                regional_prefix = self._client.detected_region_prefix
                if not regional_prefix:
                    raise first_error
                alternate = await self._bootstrap_regional_session(regional_prefix)
                try:
                    await self._validate_session(regional=True)
                except TeraboxError:
                    raise
                except Exception as regional_error:
                    if alternate:
                        raise regional_error
                    await self._bootstrap_alternate_regional_session(regional_prefix)
                    await self._validate_session(regional=True)
        except TeraboxError:
            await self.aclose()
            raise
        except Exception as error:
            await self.aclose()
            if _is_rejected_session(error):
                raise TeraboxError(
                    "TeraBox session cookie was rejected; sign in again and export "
                    "a fresh Netscape cookies.txt file containing ndus"
                ) from None
            raise TeraboxError(
                "TeraBox authentication validation failed "
                f"({_bootstrap_failure_reason(error)}); all available account "
                "routes were exhausted"
            ) from None

    async def _bootstrap_regional_session(self, prefix: str) -> bool:
        if not self._client.use_region(prefix):
            raise TeraboxError("TeraBox returned an unusable regional endpoint")
        try:
            await self._bootstrap_session(regional=True)
        except TeraboxError:
            await self._bootstrap_alternate_regional_session(prefix)
            return True
        return False

    async def _bootstrap_alternate_regional_session(self, prefix: str):
        if not self._client.use_region(prefix, alternate=True):
            raise TeraboxError(
                "TeraBox alternate regional endpoint was already exhausted"
            )
        await self._bootstrap_session(regional=True, alternate=True)

    async def _bootstrap_session(
        self,
        *,
        regional: bool = False,
        alternate: bool = False,
    ):
        try:
            await self._client.refresh_cookies()
        except Exception as error:
            if alternate:
                endpoint = "alternate regional TeraBox endpoint"
            elif regional:
                endpoint = "regional TeraBox endpoint"
            else:
                endpoint = "TeraBox"
            raise TeraboxError(
                f"TeraBox session bootstrap failed on the {endpoint} "
                f"({_bootstrap_failure_reason(error)}). The cookie file was parsed "
                "successfully; check TeraBox reachability, proxy settings, and the "
                "installed aioterabox version"
            ) from None

    async def _validate_session(self, *, regional: bool = False):
        try:
            await self._client.ensure_logged_in()
            quota = await self._client.get_storage_quota()
        except Exception as error:
            if _is_rejected_session(error):
                location = "regional endpoint" if regional else "account endpoint"
                raise TeraboxError(
                    f"TeraBox session cookie was rejected by the {location}; sign in "
                    "again and export a fresh Netscape cookies.txt file containing ndus"
                ) from None
            raise
        if not isinstance(quota, dict) or quota.get("errno") != 0:
            if isinstance(quota, dict) and quota.get("errno") == -6:
                location = "regional endpoint" if regional else "account endpoint"
                raise TeraboxError(
                    f"TeraBox session cookie was rejected by the {location}; sign in "
                    "again and export a fresh Netscape cookies.txt file containing ndus"
                )
            raise TeraboxError(
                "TeraBox authenticated quota validation returned an unexpected response"
            )
        return quota

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
        except TeraboxError:
            raise
        except ValueError as error:
            raise TeraboxError(str(error)) from None
        except Exception as error:
            if _is_rejected_session(error):
                raise TeraboxError(
                    "TeraBox rejected the upload session; authenticate again using "
                    "the bot server's network"
                ) from None
            raise TeraboxError(
                f"TeraBox upload API failed ({type(error).__name__}); no remote "
                "completion was reported"
            ) from None
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
