"""Amaterasu's source-based TeraBox compatibility layer.

The pinned Apache-2.0 ``aioterabox`` package supplies reusable account and HTTP
primitives.  Current regional routing and write-auth/upload behavior live here
as ordinary Python so the complete runtime path remains inspectable.  Public
share links reuse Amaterasu's existing resolver, keeping this package portable
across Python versions and CPU architectures.
"""

from __future__ import annotations

import json
import os
from asyncio import (
    FIRST_COMPLETED,
    CancelledError,
    Event,
    create_task,
    sleep,
    to_thread,
    wait,
)
from asyncio import gather as asyncio_gather
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import md5
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from re import DOTALL
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
from aioterabox.exceptions import TeraboxNotFoundError as _SdkNotFoundError
from aioterabox.exceptions import TeraboxUnauthorizedError as _SdkUnauthorizedError

__version__ = "1.0.6-amaterasu"

_DEFAULT_ACCOUNT_BASE_URL = "https://www.terabox.com"
_REGION_PREFIX = re_compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NON_REGIONAL_COOKIE_PREFIXES = {"www", "d", "data", "s3", "static"}
_REGIONAL_ACCOUNT_DOMAINS = ("terabox.com", "1024terabox.com")
_FREE_MAX_FILE_SIZE = 4 * 1024**3
_VIP_MAX_FILE_SIZE = 20 * 1024**3 - 1
_UPLOAD_CONTROL_TIMEOUT = 30
_UPLOAD_FINALIZE_TIMEOUT = 30
_UPLOAD_NETWORK_ATTEMPTS = 3
_UPLOAD_AUTH_ERROR_CODES = {-6, 4000020, 4000023}
_REMOTE_SNAPSHOT_UNKNOWN = object()
_TEMPLATE_DATA = re_compile(
    r"<script>\s*var\s+templateData\s*=\s*(\{.*?\})\s*;</script>",
    DOTALL,
)
_ENCODED_JS_TOKEN = re_compile(r"%28%22(.*?)%22%29")
_PAGE_JS_TOKEN = re_compile(
    r"window\.jsToken%20%3D%20a%7D%3Bfn%28%22(.*?)%22%29"
)
_INVALID_REMOTE_NAME = re_compile(r'[\\:*?"<>|\x00-\x1f]')


class TeraboxError(Exception):
    pass


class TeraboxPasswordError(TeraboxError):
    pass


class TeraboxCancelled(TeraboxError):
    pass


class _UploadAuthRejected(_SdkUnauthorizedError):
    """A sanitized write-auth rejection with no cookie or token material."""

    def __init__(self, stage: str, code, message: str):
        super().__init__(f"TeraBox rejected upload {stage} auth")
        self.code = code
        self.api_message = message[:120]


class _UploadHttpRejected(TeraboxError):
    """A final-create HTTP rejection safe to expose and conditionally retry."""

    def __init__(self, status: int):
        super().__init__(f"TeraBox upload finalization returned HTTP {status}")
        self.status = status


class _UploadApiRejected(_SdkApiError):
    """A sanitized create rejection retaining only useful diagnostics."""

    def __init__(self, code, message: str, status: int | None = None):
        self.code = code
        self.api_message = message[:120]
        self.status = status
        status_detail = f", HTTP {status}" if status and status >= 400 else ""
        super().__init__(
            f"TeraBox file create failed (errno={code}, "
            f"message={self.api_message or 'unknown'}{status_detail})"
        )


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


def _account_base_url(value: str) -> str | None:
    """Return a safe TeraBox account origin from a final response URL."""
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


def _upload_rejection_reason(error: Exception) -> str:
    if not isinstance(error, _UploadAuthRejected):
        return ""
    return f"errno={error.code}, message={error.api_message or 'unknown'}"


def _finalization_rejection_reason(error: Exception) -> str:
    if isinstance(error, _UploadHttpRejected):
        return f"HTTP {error.status}"
    if isinstance(error, _UploadApiRejected):
        details = []
        if error.status and error.status >= 400:
            details.append(f"HTTP {error.status}")
        details.append(f"errno={error.code}")
        details.append(f"message={error.api_message or 'unknown'}")
        return ", ".join(details)
    return "API rejection"


def _terabox_proxy_url() -> str | None:
    proxy_url = os.getenv("TERABOX_PROXY", "").strip()
    if not proxy_url:
        return None
    parsed = urlsplit(proxy_url)
    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        return proxy_url
    return None


def sanitize_remote_path(remote_path: str) -> str:
    """Make every TeraBox path component portable without losing Unicode."""
    components = []
    for component in str(remote_path or "").split("/"):
        if not component:
            continue
        safe = _INVALID_REMOTE_NAME.sub("_", component).rstrip(" .")
        if safe in {"", ".", ".."}:
            safe = "_"
        components.append(safe)
    return "/" + "/".join(components) if components else "/"


def _page_auth_data(page: str) -> dict[str, str]:
    """Extract non-cookie write tokens from an authenticated account page."""
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
        "bdstoken": str(template.get("bdstoken") or ""),
        "csrfToken": str(template.get("csrf") or ""),
        "pcftoken": str(template.get("pcftoken") or ""),
    }


class _RegionalAccountClient(_AccountClient):
    """Make the SDK's hard-coded account origin per-client and region-aware."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = _DEFAULT_ACCOUNT_BASE_URL
        self.detected_region_prefix: str | None = None
        self.proxy_url = _terabox_proxy_url()
        self.bds_token = ""
        self.pcf_token = ""
        self.dp_logid = ""

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
            headers = response.headers
            self._remember_region(headers.get("Url-Domain-Prefix"))
            if logid := headers.get("logid") or headers.get("dp-logid"):
                self.dp_logid = str(logid)
            if response_url := getattr(response, "url", None):
                if account_base := _account_base_url(str(response_url)):
                    self._set_account_base_url(account_base)
            yield response

    async def get_max_file_size(self) -> int:
        """Correct aioterabox 0.2.3's reversed free/VIP size limits."""
        return _VIP_MAX_FILE_SIZE if await self.check_vip_status() else _FREE_MAX_FILE_SIZE

    async def refresh_cookies(self) -> dict:
        """Refresh cookies and retain the page-derived upload tokens."""
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
        self.bds_token = auth_data["bdstoken"]
        self.pcf_token = auth_data["pcftoken"]
        return {
            "bdstoken": self.bds_token,
            "pcftoken": self.pcf_token,
            "jstoken": self.js_token,
            "cookies": session_cookies,
        }

    async def upload_file(self, filename: str, destination_path: str) -> dict:
        """Upload every chunk, including the SDK's previously omitted remainder."""
        destination_path = sanitize_remote_path(destination_path)
        file_size = await to_thread(os.path.getsize, filename)
        local_mtime = int(await to_thread(os.path.getmtime, filename))
        max_file_size = await self._run_precontent_network_stage(
            "membership check",
            self.get_max_file_size,
        )
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

            upload_host = await self._run_precontent_network_stage(
                "host discovery",
                self._locate_upload_host,
            )
            md5_list = [digest for _path, _size, digest in chunks]
            upload_id = await self._run_precontent_network_stage(
                "precreate",
                self._precreate_file,
                destination_path,
                file_size,
                md5_list,
            )

            await self._upload_chunks(
                upload_host=upload_host,
                remote_path=destination_path,
                uploadid=upload_id,
                file_chunks_md5=chunks,
            )
            previous_remote = await self._remote_file_snapshot(destination_path)
            try:
                return await self._run_upload_stage_with_auth_refresh(
                    "finalization",
                    self._postcreate_file,
                    remote_path=destination_path,
                    uploadid=upload_id,
                    file_size=file_size,
                    md5_list_json=md5_list,
                    local_mtime=local_mtime,
                )
            except (_UploadHttpRejected, _SdkApiError) as primary_rejection:
                if recovered := await self._recover_finalization_timeout(
                    destination_path,
                    file_size,
                    previous_remote,
                ):
                    return recovered
                try:
                    return await self._run_upload_stage_with_auth_refresh(
                        "finalization compatibility",
                        self._postcreate_file,
                        remote_path=destination_path,
                        uploadid=upload_id,
                        file_size=file_size,
                        md5_list_json=md5_list,
                        local_mtime=local_mtime,
                        compatibility=True,
                    )
                except (TimeoutError, aiohttp.ClientError, OSError) as error:
                    if recovered := await self._recover_finalization_timeout(
                        destination_path,
                        file_size,
                        previous_remote,
                    ):
                        return recovered
                    raise TeraboxError(
                        "TeraBox upload compatibility finalization failed "
                        f"({_bootstrap_failure_reason(error)}); it was not retried "
                        "because remote completion could not be verified"
                    ) from None
                except _UploadHttpRejected as fallback_rejection:
                    if recovered := await self._recover_finalization_timeout(
                        destination_path,
                        file_size,
                        previous_remote,
                    ):
                        return recovered
                    raise TeraboxError(
                        "TeraBox upload finalization rejected both supported "
                        "protocols "
                        f"(primary={_finalization_rejection_reason(primary_rejection)}; "
                        "compatibility="
                        f"{_finalization_rejection_reason(fallback_rejection)}); chunks "
                        "were uploaded but remote completion was not reported"
                    ) from None
                except _SdkApiError as fallback_rejection:
                    if recovered := await self._recover_finalization_timeout(
                        destination_path,
                        file_size,
                        previous_remote,
                    ):
                        return recovered
                    raise TeraboxError(
                        "TeraBox upload finalization rejected both supported API "
                        "protocols "
                        f"(primary={_finalization_rejection_reason(primary_rejection)}; "
                        "compatibility="
                        f"{_finalization_rejection_reason(fallback_rejection)}); chunks "
                        "were uploaded but remote completion was not reported"
                    ) from None
            except (TimeoutError, aiohttp.ClientError, OSError) as error:
                if recovered := await self._recover_finalization_timeout(
                    destination_path,
                    file_size,
                    previous_remote,
                ):
                    return recovered
                raise TeraboxError(
                    "TeraBox upload finalization failed "
                    f"({_bootstrap_failure_reason(error)}); the request was not "
                    "retried because remote completion could not be verified and "
                    "a retry could create a duplicate"
                ) from None

    async def _run_precontent_network_stage(
        self,
        stage: str,
        operation,
        *args,
        **kwargs,
    ):
        """Retry transport failures only before any file content is uploaded."""
        last_error = None
        for _attempt in range(_UPLOAD_NETWORK_ATTEMPTS):
            try:
                return await self._run_upload_stage_with_auth_refresh(
                    stage,
                    operation,
                    *args,
                    **kwargs,
                )
            except (TimeoutError, aiohttp.ClientError, OSError) as error:
                last_error = error
        raise TeraboxError(
            f"TeraBox upload {stage} failed after {_UPLOAD_NETWORK_ATTEMPTS} "
            f"network attempts ({_bootstrap_failure_reason(last_error)}); no file "
            "content was sent"
        ) from None

    async def _run_upload_stage_with_auth_refresh(
        self,
        stage: str,
        operation,
        *args,
        **kwargs,
    ):
        """Retry one rejected write request after refreshing derived tokens."""
        try:
            return await operation(*args, **kwargs)
        except Exception as first_error:
            if not _is_rejected_session(first_error):
                raise
        try:
            await self.refresh_cookies()
        except Exception as refresh_error:
            raise TeraboxError(
                f"TeraBox upload {stage} rejected the session and token refresh "
                f"failed ({_bootstrap_failure_reason(refresh_error)})"
            ) from None
        try:
            return await operation(*args, **kwargs)
        except Exception as retry_error:
            if _is_rejected_session(retry_error):
                reason = _upload_rejection_reason(retry_error)
                detail = f" ({reason})" if reason else ""
                guidance = ""
                if isinstance(retry_error, _UploadAuthRejected) and (
                    retry_error.code == 4000023
                ):
                    guidance = (
                        "; TeraBox requires browser verification for this network, "
                        "so authenticate through the bot server's public IP or its "
                        "configured proxy and export cookies from that same route"
                    )
                raise TeraboxError(
                    f"TeraBox upload {stage} rejected the refreshed session; the "
                    "cookie is accepted for account reads but not for uploads"
                    f"{detail}{guidance}"
                ) from None
            raise

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
            try:
                result = await self._run_upload_stage_with_auth_refresh(
                    f"chunk {partseq + 1}",
                    self._upload_file_chunk,
                    upload_host=upload_host,
                    filename=chunk_path,
                    filesize=chunk_size,
                    remote_path=remote_path,
                    chunk_md5=chunk_md5,
                    uploadid=uploadid,
                    partseq=partseq,
                )
            except TeraboxError:
                raise
            except Exception as error:
                if isinstance(error, TimeoutError):
                    reason = "request timed out after the SDK's bounded retries"
                elif isinstance(error, aiohttp.ClientError):
                    reason = "network request failed after the SDK's bounded retries"
                elif isinstance(error, _SdkApiError):
                    reason = "the upload service rejected the chunk or retries expired"
                elif isinstance(error, OSError):
                    reason = "chunk transport or local file access failed"
                else:
                    reason = f"unexpected {type(error).__name__}"
                raise TeraboxError(
                    f"TeraBox upload chunk {partseq + 1} failed ({reason}); later "
                    "chunks and finalization were not started"
                ) from None
            results.append(result)
        return results

    async def _remote_file_snapshot(self, remote_path: str):
        """Return sanitized metadata for timeout recovery without changing state."""
        try:
            metadata = await self.get_files_meta([remote_path])
        except _SdkNotFoundError:
            return None
        except Exception:
            return _REMOTE_SNAPSHOT_UNKNOWN
        for item in metadata if isinstance(metadata, list) else []:
            if str(item.get("path") or "") != remote_path:
                continue
            return (
                str(item.get("fs_id") or ""),
                int(item.get("size") or 0),
                int(item.get("server_mtime") or 0),
            )
        return None

    async def _recover_finalization_timeout(
        self,
        remote_path: str,
        file_size: int,
        previous_remote,
    ) -> dict | None:
        """Confirm a lost final-create response through read-only metadata calls."""
        for delay in (0, 2, 5):
            if delay:
                await sleep(delay)
            current = await self._remote_file_snapshot(remote_path)
            if current in {None, _REMOTE_SNAPSHOT_UNKNOWN}:
                continue
            if current[1] != file_size:
                continue
            if previous_remote is _REMOTE_SNAPSHOT_UNKNOWN:
                continue
            if previous_remote is None or current != previous_remote:
                return {
                    "errno": 0,
                    "fs_id": current[0] or remote_path,
                    "path": remote_path,
                    "verified_after_timeout": True,
                }
        return None

    def _upload_auth_params(self, *, include_bdstoken: bool = False) -> dict[str, str]:
        params = {
            "app_id": "250528",
            "web": "1",
            "channel": "dubox",
            "clienttype": "0",
            "jsToken": self.js_token,
        }
        if self.dp_logid:
            params["dp-logid"] = self.dp_logid
        if include_bdstoken and self.bds_token:
            params["bdstoken"] = self.bds_token
        return params

    async def _locate_upload_host(self) -> str:
        """Resolve the upload host through the active regional account origin."""
        async with self._request(
            "GET",
            f"{_DEFAULT_ACCOUNT_BASE_URL}/rest/2.0/pcs/file",
            params={"method": "locateupload"},
            timeout=_UPLOAD_CONTROL_TIMEOUT,
        ) as response:
            result = await response.json(content_type=None)
        raw_host = str(result.get("host") or "").strip()
        parsed_host = urlsplit(
            raw_host if "://" in raw_host else f"//{raw_host}"
        )
        if (
            parsed_host.hostname
            and parsed_host.scheme in {"", "https"}
            and parsed_host.username is None
            and parsed_host.password is None
        ):
            return parsed_host.netloc
        code = result.get("errno", result.get("error_code", "unknown"))
        message = str(result.get("errmsg") or result.get("error_msg") or "unknown")
        if code in _UPLOAD_AUTH_ERROR_CODES or "need verify" in message.lower():
            raise _UploadAuthRejected("host discovery", code, message)
        raise _SdkApiError(
            f"TeraBox upload-host discovery failed (errno={code}, "
            f"message={message[:120]})"
        )

    async def _precreate_file(
        self,
        remote_path: str,
        file_size: int,
        md5_list_json: list[str],
    ) -> str:
        """Initialize the current web upload protocol using query auth tokens."""
        data = {
            "path": remote_path,
            "autoinit": "1",
            "size": str(file_size),
            "file_limit_switch_v34": "true",
            "rtype": "2",
            "target_path": os.path.dirname(remote_path).rstrip("/") or "/",
            "block_list": json.dumps(md5_list_json),
        }
        async with self._request(
            "POST",
            f"{_DEFAULT_ACCOUNT_BASE_URL}/api/precreate",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            params=self._upload_auth_params(),
            data=data,
            timeout=_UPLOAD_CONTROL_TIMEOUT,
        ) as response:
            result = await response.json()
        if result.get("errno") == 0 and result.get("uploadid"):
            return result["uploadid"]
        code = result.get("errno", "unknown")
        message = str(result.get("errmsg") or result.get("msg") or "unknown")[:120]
        if code in _UPLOAD_AUTH_ERROR_CODES:
            raise _UploadAuthRejected("precreate", code, message)
        raise _SdkApiError(
            f"TeraBox file precreate failed (errno={code}, message={message})"
        )

    async def _postcreate_file(
        self,
        remote_path: str,
        uploadid: str,
        file_size: int,
        md5_list_json: list[str],
        local_mtime: int | None = None,
        compatibility: bool = False,
    ) -> dict:
        """Finalize with either the browser-query or SDK-body protocol."""
        remote_dir = os.path.dirname(remote_path).rstrip("/") or "/"
        target_path = remote_dir if remote_dir == "/" else remote_dir + "/"
        data = {
            "path": remote_path,
            "uploadid": uploadid,
            "target_path": target_path,
            "size": str(file_size),
            "block_list": json.dumps(md5_list_json),
        }
        if local_mtime is not None:
            data["local_mtime"] = str(local_mtime)
        if compatibility:
            # aioterabox's original protocol submits all control and auth
            # fields in the form body.  Keep this as the bounded fallback.
            data.update(self._upload_auth_params())
            data.update({"isdir": "0", "rtype": "1"})
            params = None
        else:
            # Current web-compatible clients put create controls in the query
            # and authenticate with jsToken plus the session cookies.  A
            # page-derived bdstoken can be regional and must not be mixed in.
            params = self._upload_auth_params()
            params.update({"isdir": "0", "rtype": "1"})
        async with self._request(
            "POST",
            f"{_DEFAULT_ACCOUNT_BASE_URL}/api/create",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            params=params,
            data=data,
            timeout=_UPLOAD_FINALIZE_TIMEOUT,
        ) as response:
            status = int(getattr(response, "status", 200) or 200)
            try:
                result = await response.json(content_type=None)
            except (TypeError, ValueError):
                if status >= 400:
                    raise _UploadHttpRejected(status) from None
                raise _SdkApiError(
                    "TeraBox file create returned an unrecognized response"
                ) from None
        if not isinstance(result, dict):
            if status >= 400:
                raise _UploadHttpRejected(status)
            raise _SdkApiError("TeraBox file create returned an invalid response")
        if result.get("errno") == 0:
            return result
        code = result.get("errno", "unknown")
        message = str(result.get("errmsg") or result.get("msg") or "unknown")[:120]
        if code in _UPLOAD_AUTH_ERROR_CODES or "need verify" in message.lower():
            raise _UploadAuthRejected("finalization", code, message)
        raise _UploadApiRejected(code, message, status)


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
        remote_path = sanitize_remote_path(remote_path)
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
    "sanitize_remote_path",
]
