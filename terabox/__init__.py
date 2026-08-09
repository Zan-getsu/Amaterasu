"""Source-visible, download-only TeraBox integration for Amaterasu.

The Apache-2.0 ``aioterabox`` package supplies authenticated account and HTTP
primitives. Regional routing, public-share resolution, account browsing,
resilient direct-link downloads, and cancellation remain ordinary Python.
TeraBox upload support is intentionally not provided.
"""

from __future__ import annotations

import json
import os
from asyncio import Event, Lock, sleep, to_thread
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from ipaddress import ip_address
from logging import getLogger
from pathlib import Path
from re import DOTALL, IGNORECASE
from re import compile as re_compile
from urllib.parse import urlsplit

import aiohttp
from aiofiles import open as aiopen
from aiofiles.os import makedirs
from aioterabox.api import FileInfo as _AccountFileInfo
from aioterabox.api import TeraboxClient as _AccountClient
from aioterabox.exceptions import TeraboxUnauthorizedError as _SdkUnauthorizedError

__version__ = "2.0.1-amaterasu"

_LOGGER = getLogger(__name__)

_DEFAULT_ACCOUNT_BASE_URL = "https://www.terabox.com"
_REGION_PREFIX = re_compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NON_REGIONAL_COOKIE_PREFIXES = {"www", "d", "data", "s3", "static"}
_REGIONAL_ACCOUNT_DOMAINS = ("terabox.com", "1024terabox.com")
_TEMPLATE_DATA = re_compile(
    r"<script>\s*var\s+templateData\s*=\s*(\{.*?\})\s*;</script>",
    DOTALL,
)
_ENCODED_JS_TOKEN = re_compile(r"%28%22(.*?)%22%29")
_PAGE_JS_TOKEN = re_compile(
    r"window\.jsToken%20%3D%20a%7D%3Bfn%28%22(.*?)%22%29"
)
_CONTENT_RANGE_TOTAL = re_compile(r"/([0-9]+)$")
_CONTENT_RANGE = re_compile(
    r"bytes\s+([0-9]+)-([0-9]+)/([0-9]+|\*)$",
    IGNORECASE,
)
_DOWNLOAD_ATTEMPTS = 4
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=30, sock_read=90)
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
_EXPIRED_LINK_HTTP = {401, 403, 404, 410}
_ACCOUNT_PAGE_SIZE = 1000
_ACCOUNT_ENTRY_LIMIT = 100_000


class TeraboxError(Exception):
    pass


class TeraboxPasswordError(TeraboxError):
    pass


class TeraboxCancelled(TeraboxError):
    pass


class _SessionRejected(_SdkUnauthorizedError):
    """An authenticated read rejection that may still be a route mismatch."""

    def __init__(self, location: str):
        super().__init__(f"TeraBox rejected session validation on {location}")
        self.location = location


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
    headers: list[str] | dict[str, str] | str = field(default_factory=list)


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
    if not normalized["ndus"]:
        raise TeraboxError("TeraBox cookie is missing the required ndus value")
    return normalized


def _cookie_region_hint(records) -> str | None:
    for cookie in records:
        domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
        for root in _REGIONAL_ACCOUNT_DOMAINS:
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
    normalized = (prefix or "").strip().lower()
    if domain not in _REGIONAL_ACCOUNT_DOMAINS or not _REGION_PREFIX.fullmatch(
        normalized
    ):
        return None
    return f"https://{normalized}.{domain}"


def _account_base_url(value: str) -> str | None:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        return None
    hostname = parsed.hostname.lower()
    for domain in _REGIONAL_ACCOUNT_DOMAINS:
        if hostname == f"www.{domain}":
            return f"https://{hostname}"
        suffix = f".{domain}"
        if not hostname.endswith(suffix):
            continue
        prefix = hostname[: -len(suffix)]
        if (
            "." not in prefix
            and prefix not in _NON_REGIONAL_COOKIE_PREFIXES
            and _REGION_PREFIX.fullmatch(prefix)
        ):
            return f"https://{hostname}"
    return None


def _is_rejected_session(error: Exception) -> bool:
    if isinstance(error, _SdkUnauthorizedError):
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "errno': -6",
            'errno": -6',
            "errno=-6",
            "error_code': -6",
            'error_code": -6',
            "error_code=-6",
            "4000020",
            "4000023",
            "need verify",
            "user not login",
            "invalid cookies",
        )
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


def _page_auth_data(page: str) -> dict[str, str]:
    """Extract page-derived session tokens from an account page."""
    match = _TEMPLATE_DATA.search(page)
    template = json.loads(match.group(1)) if match else {}
    js_token = str(template.get("jsToken") or "")
    if encoded := _ENCODED_JS_TOKEN.search(js_token):
        js_token = encoded.group(1)
    if not js_token and (encoded := _PAGE_JS_TOKEN.search(page)):
        js_token = encoded.group(1)
    if not match and not js_token:
        raise ValueError("TeraBox account page did not contain authentication data")
    return {
        "jstoken": js_token,
        "csrfToken": str(template.get("csrf") or ""),
    }


def _headers_dict(headers) -> dict[str, str]:
    if isinstance(headers, dict):
        return {str(key): str(value) for key, value in headers.items()}
    if isinstance(headers, str):
        headers = headers.splitlines()
    result = {}
    for header in headers or []:
        if ":" in header:
            key, value = header.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def _validated_download_url(value: str, *, account_only: bool = False) -> str:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme.lower() not in ({"https"} if account_only else {"http", "https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise TeraboxError("TeraBox returned an invalid download URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise TeraboxError("TeraBox returned a blocked local download URL")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise TeraboxError("TeraBox returned a blocked private download URL")
    if account_only and not any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in _REGIONAL_ACCOUNT_DOMAINS
    ):
        raise TeraboxError("TeraBox returned an untrusted account download host")
    return normalized


def _response_total(headers, fallback: int = 0) -> int:
    content_range = str(headers.get("Content-Range", ""))
    if match := _CONTENT_RANGE_TOTAL.search(content_range):
        return int(match.group(1))
    return int(headers.get("Content-Length", fallback) or fallback)


def _safe_transfer_reason(error: Exception) -> str:
    if isinstance(error, aiohttp.ClientResponseError):
        return f"HTTP {error.status}"
    if isinstance(error, TimeoutError):
        return "request timed out"
    if isinstance(error, aiohttp.ClientConnectorError):
        return "could not connect to the download host"
    if isinstance(error, (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError)):
        return "the download server disconnected"
    if isinstance(error, aiohttp.ClientError):
        return "network connection failed"
    if isinstance(error, OSError):
        return "local file operation failed"
    if isinstance(error, TeraboxError):
        return str(error)[:160]
    return type(error).__name__


class _RegionalAccountClient(_AccountClient):
    """Make the SDK's hard-coded account origin per-client and region-aware."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = _DEFAULT_ACCOUNT_BASE_URL
        self.detected_region_prefix: str | None = None
        self.proxy_url = _terabox_proxy_url()

    def _set_account_base_url(self, base_url: str) -> bool:
        if base_url == self.base_url:
            return False
        self.base_url = base_url
        self._base_headers["Origin"] = base_url
        self._base_headers["Referer"] = base_url + "/main"
        self.account["account_id"] = None
        self.is_vip = None
        self._signb = None
        self._public_key = None
        return True

    def use_region(self, prefix: str | None, *, alternate: bool = False) -> bool:
        domain = _REGIONAL_ACCOUNT_DOMAINS[1 if alternate else 0]
        base_url = _regional_base_url(prefix, domain)
        if not base_url:
            return False
        return self._set_account_base_url(base_url)

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
            if response_url := getattr(response, "url", None):
                if account_base := _account_base_url(str(response_url)):
                    self._set_account_base_url(account_base)
            yield response

    async def refresh_cookies(self) -> dict:
        async with self._request(
            "GET",
            f"{_DEFAULT_ACCOUNT_BASE_URL}/main",
            clean_cookies=False,
            timeout=10,
        ) as response:
            page = await response.text()
        auth_data = _page_auth_data(page)
        session_cookies = self._session_from_cookie_jar()
        derived_cookies = {
            key: auth_data[key]
            for key in ("jstoken", "csrfToken")
            if auth_data[key]
        }
        self._update_session(session_cookies, derived_cookies)
        return {"jstoken": self.js_token, "cookies": session_cookies}

    async def list_remote_directory(self, remote_dir: str) -> list[_AccountFileInfo]:
        """List every page instead of silently truncating directories at 1,000."""
        entries = []
        previous_signature = None
        page = 1
        while True:
            async with self._request(
                "GET",
                f"{_DEFAULT_ACCOUNT_BASE_URL}/api/list",
                params={
                    "app_id": "250528",
                    "web": "1",
                    "channel": "dubox",
                    "clienttype": "5",
                    "jsToken": self.js_token,
                    "dir": f"/{remote_dir.lstrip('/')}",
                    "num": str(_ACCOUNT_PAGE_SIZE),
                    "page": str(page),
                    "order": "time",
                    "desc": "1",
                    "showempty": "0",
                },
                timeout=10,
            ) as response:
                data = await response.json()
            if not isinstance(data, dict):
                raise TeraboxError("Account listing returned an invalid response")
            errno = data.get("errno", 0)
            if errno in {-7, -9}:
                raise TeraboxError("Remote directory was not found")
            if errno == -6:
                raise _SessionRejected("regional endpoint")
            if errno != 0:
                raise TeraboxError(f"Account listing failed (errno={errno})")
            items = data.get("list") or []
            if not isinstance(items, list):
                raise TeraboxError("Account listing returned an invalid file list")
            signature = tuple(
                (str(item.get("path", "")), str(item.get("fs_id", "")))
                for item in items
                if isinstance(item, dict)
            )
            if signature and signature == previous_signature:
                raise TeraboxError("Account listing repeated a page; pagination stopped")
            previous_signature = signature
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                entries.append(
                    _AccountFileInfo(
                        name=str(entry.get("server_filename") or "unnamed"),
                        path=str(entry.get("path") or ""),
                        size=int(entry.get("size") or 0),
                        is_dir=bool(entry.get("isdir")),
                    )
                )
                if len(entries) > _ACCOUNT_ENTRY_LIMIT:
                    raise TeraboxError(
                        f"Account directory exceeds {_ACCOUNT_ENTRY_LIMIT:,} entries"
                    )
            if len(items) < _ACCOUNT_PAGE_SIZE:
                return entries
            page += 1


class TeraboxClient:
    def __init__(self, cookie_file: str = "", session_path: str | None = None):
        del session_path
        self.cookie_file = cookie_file
        self.proxy_url = _terabox_proxy_url()
        self._session: aiohttp.ClientSession | None = None
        self._client: _AccountClient | None = None
        self._share_link = ""
        self._resolve_lock = Lock()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=_DOWNLOAD_TIMEOUT,
            )
        return self._session

    async def login(self):
        if not self.cookie_file:
            raise TeraboxError("A TeraBox cookie file is required for account browsing")
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
                    "TeraBox session cookie was rejected after token refresh and all "
                    "available account routes; sign in again and export a fresh "
                    "Netscape cookies.txt file containing ndus"
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
            raise TeraboxError("TeraBox alternate regional endpoint was exhausted")
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
            endpoint = (
                "alternate regional TeraBox endpoint"
                if alternate
                else "regional TeraBox endpoint"
                if regional
                else "TeraBox"
            )
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
                raise _SessionRejected(location) from None
            raise
        if not isinstance(quota, dict) or quota.get("errno") != 0:
            if isinstance(quota, dict) and quota.get("errno") == -6:
                location = "regional endpoint" if regional else "account endpoint"
                raise _SessionRejected(location)
            raise TeraboxError(
                "TeraBox authenticated quota validation returned an unexpected response"
            )
        return quota

    async def list_account_dir(self, path: str):
        if self._client is None:
            await self.login()
        try:
            entries = await self._client.list_remote_directory(path or "/")
            return [
                TeraboxFile(
                    name=entry.name,
                    path=entry.path,
                    fs_id=str(getattr(entry, "fs_id", "") or entry.path),
                    size=int(entry.size or 0),
                    is_dir=bool(entry.is_dir),
                )
                for entry in entries
            ]
        except TeraboxError:
            raise
        except Exception as error:
            raise TeraboxError(
                f"Account listing failed ({_safe_transfer_reason(error)})"
            ) from None

    async def walk_account_dir(self, path: str):
        files = []
        pending = [path or "/"]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            for entry in await self.list_account_dir(current):
                if entry.is_dir:
                    pending.append(entry.path)
                else:
                    files.append(entry)
                if len(files) + len(pending) > 100_000:
                    raise TeraboxError("Account selection exceeds 100,000 entries")
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

    async def _resolve_public_share(self, link: str) -> ResolveResult:
        try:
            from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import (
                terabox as resolve_share,
            )

            resolved = await to_thread(
                resolve_share,
                link,
                self.cookie_file,
                structured=True,
            )
        except Exception as error:
            message = str(error)
            if "password" in message.lower() or "passcode" in message.lower():
                raise TeraboxPasswordError(
                    "TeraBox rejected the share password or requires a valid password"
                ) from None
            if type(error).__name__ == "DirectDownloadLinkException":
                raise TeraboxError(message[:240] or "Public share resolution failed") from None
            raise TeraboxError(
                f"Public share resolution failed ({type(error).__name__})"
            ) from None
        return await self._normalize_resolved(resolved)

    async def _normalize_resolved(self, resolved) -> ResolveResult:
        if isinstance(resolved, str):
            resolved = _validated_download_url(resolved)
            name = Path(resolved.split("?", 1)[0]).name or "TeraBox"
            size = await self._remote_size(resolved)
            return ResolveResult(
                name,
                [TeraboxFile(name, f"/{name}", name, size=size, url=resolved)],
                False,
            )
        if isinstance(resolved, tuple) and len(resolved) == 2:
            url, headers = resolved
            url = _validated_download_url(str(url))
            name = Path(str(url).split("?", 1)[0]).name or "TeraBox"
            size = await self._remote_size(str(url), headers)
            return ResolveResult(
                name,
                [
                    TeraboxFile(
                        name,
                        f"/{name}",
                        name,
                        size=size,
                        url=str(url),
                        headers=headers,
                    )
                ],
                False,
            )
        if not isinstance(resolved, dict):
            raise TeraboxError("TeraBox resolver returned an unsupported response")
        contents = resolved.get("contents")
        if not isinstance(contents, list):
            raise TeraboxError("TeraBox resolver returned no file list")
        root = str(resolved.get("title") or "TeraBox").strip("/") or "TeraBox"
        files = []
        for index, item in enumerate(contents):
            if not isinstance(item, dict):
                continue
            name = str(item.get("filename") or f"file_{index + 1}")
            path = "/".join(
                part.strip("/")
                for part in (str(item.get("path") or ""), name)
                if part and part.strip("/")
            )
            url = str(item.get("url") or "")
            if not url:
                raise TeraboxError("A selected share file has no resolved download URL")
            url = _validated_download_url(url)
            files.append(
                TeraboxFile(
                    name=name,
                    path=f"/{path}",
                    fs_id=str(item.get("fs_id") or index),
                    size=int(item.get("size") or 0),
                    url=url,
                    headers=item.get("headers") or resolved.get("header") or [],
                )
            )
        if not files:
            raise TeraboxError("TeraBox share contains no downloadable files")
        is_folder = bool(resolved.get("is_folder", len(files) > 1))
        return ResolveResult(root, files, is_folder)

    async def resolve(self, link: str, recursive: bool = True):
        del recursive
        await self._ensure_session()
        normalized = str(link or "").strip()
        if not normalized:
            raise TeraboxError("TeraBox link is empty")
        async with self._resolve_lock:
            result = await self._resolve_public_share(normalized)
            self._share_link = normalized
            return result

    async def _remote_size(self, url: str, headers=None) -> int:
        request_headers = _headers_dict(headers)
        request_headers.setdefault("Accept-Encoding", "identity")
        try:
            async with self._session.head(
                url,
                headers=request_headers,
                allow_redirects=True,
                timeout=_DOWNLOAD_TIMEOUT,
                proxy=self.proxy_url,
            ) as response:
                if response.status < 400:
                    size = _response_total(response.headers)
                    if size:
                        return size
        except Exception as error:
            _LOGGER.debug("TeraBox size HEAD failed: %s", type(error).__name__)
        try:
            request_headers = {**request_headers, "Range": "bytes=0-0"}
            async with self._session.get(
                url,
                headers=request_headers,
                allow_redirects=True,
                timeout=_DOWNLOAD_TIMEOUT,
                proxy=self.proxy_url,
            ) as response:
                if response.status in {200, 206}:
                    return _response_total(response.headers)
        except Exception as error:
            _LOGGER.debug("TeraBox size range probe failed: %s", type(error).__name__)
        return 0

    async def reserve_files(self, destinations):
        seen = set()
        for destination, _size in destinations:
            absolute = os.path.abspath(destination)
            if absolute in seen:
                raise TeraboxError(f"Multiple files resolve to {os.path.basename(destination)}")
            seen.add(absolute)
            await makedirs(os.path.dirname(absolute), exist_ok=True)

    async def _account_download_url(self, file: TeraboxFile) -> str:
        if self._client is None:
            raise TeraboxError("No authenticated account download session is available")
        metadata = await self._client.get_files_meta([file.path])
        if not metadata:
            raise TeraboxError("TeraBox returned no metadata for the selected account file")
        first = metadata[0]
        url = first.get("dlink", "") if isinstance(first, dict) else getattr(first, "dlink", "")
        if not url:
            raise TeraboxError("TeraBox returned no download URL for the account file")
        return _validated_download_url(str(url), account_only=True)

    async def _refresh_file_url(self, file: TeraboxFile) -> bool:
        if not self._share_link:
            try:
                file.url = await self._account_download_url(file)
                return True
            except Exception:
                return False
        try:
            async with self._resolve_lock:
                refreshed = await self._resolve_public_share(self._share_link)
                match = next(
                    (
                        candidate
                        for candidate in refreshed.file_entries
                        if candidate.path == file.path
                        or candidate.fs_id == file.fs_id
                        or candidate.name == file.name
                    ),
                    None,
                )
                if not match:
                    return False
                file.url = match.url
                file.headers = match.headers
                file.size = match.size or file.size
                return bool(file.url)
        except Exception as error:
            _LOGGER.warning(
                "Could not refresh TeraBox direct link (%s)",
                _safe_transfer_reason(error),
            )
            return False

    async def download_file(
        self,
        file: TeraboxFile,
        destination: str,
        *,
        progress_cb=None,
        cancel_event: Event | None = None,
    ):
        await self._ensure_session()
        destination = os.path.abspath(destination)
        partial = destination + ".part"
        await makedirs(os.path.dirname(destination), exist_ok=True)
        last_error: Exception | None = None
        refresh_attempted = False
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            if cancel_event and cancel_event.is_set():
                raise TeraboxCancelled("Transfer cancelled")
            try:
                if not file.url:
                    file.url = await self._account_download_url(file)
                file.url = _validated_download_url(
                    file.url,
                    account_only=self._client is not None and not self._share_link,
                )
                offset = (
                    await to_thread(os.path.getsize, partial)
                    if os.path.exists(partial)
                    else 0
                )
                if file.size and offset == file.size:
                    await to_thread(os.replace, partial, destination)
                    if progress_cb:
                        progress_cb(file.size, file.size)
                    return
                if file.size and offset > file.size:
                    await to_thread(os.remove, partial)
                    offset = 0
                headers = _headers_dict(file.headers)
                headers.setdefault("Accept-Encoding", "identity")
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                account_cookies = (
                    self._client.request_cookies
                    if self._client is not None and not self._share_link
                    else None
                )
                if account_cookies:
                    base_headers = getattr(self._client, "_base_headers", {})
                    headers.setdefault(
                        "User-Agent",
                        str(base_headers.get("User-Agent") or "Mozilla/5.0"),
                    )
                    headers.setdefault(
                        "Referer",
                        str(
                            base_headers.get("Referer")
                            or getattr(self._client, "base_url", _DEFAULT_ACCOUNT_BASE_URL)
                            + "/main"
                        ),
                    )
                async with self._session.get(
                    file.url,
                    headers=headers,
                    cookies=account_cookies,
                    allow_redirects=True,
                    timeout=_DOWNLOAD_TIMEOUT,
                    proxy=self.proxy_url,
                ) as response:
                    if response.status == 416 and file.size and offset == file.size:
                        await to_thread(os.replace, partial, destination)
                        if progress_cb:
                            progress_cb(file.size, file.size)
                        return
                    if response.status in _EXPIRED_LINK_HTTP and not refresh_attempted:
                        refresh_attempted = True
                        if await self._refresh_file_url(file):
                            continue
                    if response.status in _RETRYABLE_HTTP:
                        raise aiohttp.ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message="retryable TeraBox response",
                            headers=response.headers,
                        )
                    response.raise_for_status()
                    if offset and response.status != 206:
                        offset = 0
                    elif offset and response.status == 206:
                        content_range = str(response.headers.get("Content-Range", ""))
                        if (
                            (range_match := _CONTENT_RANGE.fullmatch(content_range))
                            and int(range_match.group(1)) != offset
                        ):
                            await to_thread(os.remove, partial)
                            raise TeraboxError(
                                "The server returned a mismatched resume range"
                            )
                    mode = "ab" if offset and response.status == 206 else "wb"
                    total = _response_total(response.headers, file.size)
                    if response.status == 206 and not response.headers.get(
                        "Content-Range"
                    ):
                        remaining = int(response.headers.get("Content-Length", 0) or 0)
                        total = offset + remaining if remaining else file.size
                    content_type = str(response.headers.get("Content-Type", "")).lower()
                    if content_type.startswith("text/html"):
                        raise TeraboxError("The direct link returned an HTML error page")
                    written = offset
                    if progress_cb:
                        progress_cb(written, total)
                    async with aiopen(partial, mode) as output:
                        async for chunk in response.content.iter_chunked(
                            _DOWNLOAD_CHUNK_SIZE
                        ):
                            if cancel_event and cancel_event.is_set():
                                raise TeraboxCancelled("Transfer cancelled")
                            if not chunk:
                                continue
                            await output.write(chunk)
                            written += len(chunk)
                            if progress_cb:
                                progress_cb(written, total)
                actual = await to_thread(os.path.getsize, partial)
                expected = file.size or total
                if expected and actual != expected:
                    raise TeraboxError(
                        f"Incomplete transfer: received {actual} of {expected} bytes"
                    )
                await to_thread(os.replace, partial, destination)
                file.size = expected or actual
                if progress_cb:
                    progress_cb(file.size, file.size)
                return
            except TeraboxCancelled:
                raise
            except Exception as error:
                last_error = error
                if not refresh_attempted and isinstance(
                    error,
                    (TeraboxError, aiohttp.ClientError, TimeoutError),
                ):
                    refresh_attempted = True
                    await self._refresh_file_url(file)
                if attempt + 1 < _DOWNLOAD_ATTEMPTS:
                    await sleep(min(2**attempt, 8))
        raise TeraboxError(
            f"Download failed after {_DOWNLOAD_ATTEMPTS} attempts "
            f"({_safe_transfer_reason(last_error or TeraboxError('unknown error'))})"
        ) from None

    async def aclose(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._client = None


__all__ = [
    "ResolveResult",
    "TeraboxCancelled",
    "TeraboxClient",
    "TeraboxError",
    "TeraboxFile",
    "TeraboxPasswordError",
    "__version__",
]
