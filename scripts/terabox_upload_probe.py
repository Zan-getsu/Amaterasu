"""Run one redacted, controlled TeraBox multipart upload probe.

This command does not import or start Telegram. It creates one unique temporary
remote file, verifies it through metadata, and deletes only that exact path.
Cookie and token values are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from terabox import TeraboxClient, _SdkNotFoundError, __version__


_PROBE_BYTES = 12 * 1024 * 1024 + 123
_WRITE_BLOCK = bytes(range(256)) * 4096


def _safe_json_payload(raw: bytes) -> dict:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_message(payload: dict) -> str:
    value = payload.get("errmsg") or payload.get("error_msg") or payload.get("msg")
    message = str(value or "").lower()
    if not message:
        return ""
    categories = (
        (("auth", "cookie", "login", "session", "token"), "authentication rejected"),
        (("filename", "file name"), "invalid filename"),
        (("path",), "invalid path"),
        (("block", "md5", "checksum"), "invalid block list"),
        (("size", "length"), "invalid size"),
        (("missing", "required"), "missing parameter"),
        (("parameter", "param"), "parameter rejected"),
        (("server", "internal"), "server error"),
    )
    for needles, category in categories:
        if any(needle in message for needle in needles):
            return category
    return "present"


def _safe_code(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return text if re.fullmatch(r"[-A-Za-z0-9_.]{1,32}", text) else "present"


def _block_count(data) -> int | None:
    if not isinstance(data, dict):
        return None
    try:
        blocks = json.loads(data.get("block_list", "[]"))
    except (TypeError, ValueError):
        return None
    return len(blocks) if isinstance(blocks, list) else None


def _emit(stage: str, **details) -> None:
    print(json.dumps({"stage": stage, **details}, sort_keys=True), flush=True)


def _install_redacted_trace(account) -> None:
    original_request = account._request

    @asynccontextmanager
    async def traced_request(method: str, url: str, **kwargs):
        parsed = urlsplit(str(url))
        endpoint = parsed.path
        interesting = endpoint in {
            "/api/precreate",
            "/api/create",
            "/rest/2.0/pcs/superfile2",
        }
        async with original_request(method, url, **kwargs) as response:
            if interesting:
                raw = await response.read()
                payload = _safe_json_payload(raw)
                query = parse_qs(parsed.query)
                data = kwargs.get("data")
                event = {
                    "endpoint": endpoint,
                    "http_status": int(getattr(response, "status", 0) or 0),
                    "content_type": str(
                        getattr(response, "headers", {}).get("Content-Type", "")
                    ).split(";", 1)[0],
                    "response_bytes": len(raw),
                    "errno": _safe_code(
                        payload.get("errno", payload.get("error_code"))
                    ),
                    "message": _safe_message(payload),
                    "request_id_present": bool(payload.get("request_id")),
                }
                if endpoint == "/api/precreate":
                    event.update(
                        {
                            "protocol": "query-auth/form-metadata",
                            "form_keys": sorted(data) if isinstance(data, dict) else [],
                            "block_count": _block_count(data),
                            "has_upload_id": bool(payload.get("uploadid")),
                            "return_type": _safe_code(payload.get("return_type")),
                            "requested_parts": len(payload.get("block_list") or [])
                            if isinstance(payload.get("block_list"), list)
                            else None,
                        }
                    )
                elif endpoint == "/api/create":
                    query_keys = sorted((kwargs.get("params") or {}).keys())
                    form_keys = sorted(data) if isinstance(data, dict) else []
                    event.update(
                        {
                            "protocol": "query" if query_keys else "body",
                            "query_keys": query_keys,
                            "form_keys": form_keys,
                            "block_count": _block_count(data),
                            "has_fs_id": bool(payload.get("fs_id")),
                        }
                    )
                else:
                    request_params = kwargs.get("params") or {}
                    partseq = request_params.get("partseq")
                    if partseq is None:
                        partseq = query.get("partseq", [None])[0]
                    event.update(
                        {
                            "partseq": int(partseq) if str(partseq).isdigit() else None,
                            "has_md5": bool(payload.get("md5")),
                        }
                    )
                _emit("response", **event)
            yield response

    account._request = traced_request


def _write_probe_file(path: str, size: int) -> None:
    remaining = size
    with open(path, "wb") as output:
        while remaining:
            block = _WRITE_BLOCK[: min(remaining, len(_WRITE_BLOCK))]
            output.write(block)
            remaining -= len(block)


async def _remote_metadata(account, remote_path: str) -> tuple[str, dict | None]:
    try:
        records = await account.get_files_meta([remote_path])
    except _SdkNotFoundError:
        return "missing", None
    except Exception:
        return "unknown", None
    for record in records if isinstance(records, list) else []:
        if str(record.get("path") or "") == remote_path:
            return "found", record
    return "missing", None


async def _run(cookie_file: str, keep_remote: bool) -> int:
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    remote_path = f"/amaterasu_probe_{suffix}_{secrets.token_hex(3)}.bin"
    local_path = ""
    client = TeraboxClient(cookie_file)
    uploaded = False
    verified = False
    cleanup_ok = False
    try:
        with tempfile.NamedTemporaryFile(
            prefix="amaterasu-terabox-probe-", suffix=".bin", delete=False
        ) as temporary:
            local_path = temporary.name
        await asyncio.to_thread(_write_probe_file, local_path, _PROBE_BYTES)
        _emit(
            "probe_start",
            adapter_version=__version__,
            expected_chunk_sizes=[4194304, 4194304, 4194304, 123],
            local_size=_PROBE_BYTES,
            remote_name=Path(remote_path).name,
            live_write_acknowledged=True,
        )

        await client.ensure_upload_ready()
        account = client._client
        _emit(
            "authentication",
            authenticated=True,
            account_origin=str(getattr(account, "base_url", "")),
            region_prefix=str(getattr(account, "detected_region_prefix", "") or ""),
            js_token_present=bool(getattr(account, "js_token", "")),
            bds_token_present=bool(getattr(account, "bds_token", "")),
        )
        _install_redacted_trace(account)

        try:
            result = await client.upload_file(local_path, remote_path)
            uploaded = bool(isinstance(result, dict) and result.get("fs_id"))
            _emit("upload_return", success=uploaded, has_fs_id=uploaded)
        except Exception as error:
            _emit("upload_return", success=False, error_type=type(error).__name__)

        metadata_state, metadata = await _remote_metadata(account, remote_path)
        verified = bool(metadata and int(metadata.get("size") or 0) == _PROBE_BYTES)
        _emit(
            "remote_verification",
            found=bool(metadata),
            lookup_state=metadata_state,
            size_matches=verified,
            has_fs_id=bool(metadata and metadata.get("fs_id")),
        )

        if keep_remote:
            _emit(
                "cleanup",
                deleted=False,
                intentionally_kept=True,
                lookup_state=metadata_state,
            )
        elif metadata_state in {"found", "unknown"}:
            try:
                await account._filemanager("delete", [remote_path])
                cleanup_state, _ = await _remote_metadata(account, remote_path)
                cleanup_ok = cleanup_state == "missing"
            except _SdkNotFoundError:
                cleanup_ok = True
                _emit("cleanup", deleted=True, lookup_state="missing")
            except Exception as error:
                _emit("cleanup", deleted=False, error_type=type(error).__name__)
            else:
                _emit(
                    "cleanup",
                    deleted=cleanup_ok,
                    lookup_state=cleanup_state,
                )
        else:
            cleanup_ok = metadata_state == "missing"
            _emit(
                "cleanup",
                deleted=False,
                lookup_state=metadata_state,
                remote_file_absent=cleanup_ok,
            )

        success = uploaded and verified and (keep_remote or cleanup_ok)
        _emit("probe_complete", success=success)
        return 0 if success else 1
    except Exception as error:
        _emit("probe_aborted", error_type=type(error).__name__)
        return 1
    finally:
        await client.aclose()
        if local_path:
            try:
                os.unlink(local_path)
            except FileNotFoundError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one redacted TeraBox multipart upload and cleanup probe."
    )
    parser.add_argument("--cookie-file", default="terabox.txt")
    parser.add_argument(
        "--yes-live-write",
        action="store_true",
        help="Required acknowledgement that the probe uploads and deletes one file.",
    )
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="Keep the successfully created remote probe file instead of deleting it.",
    )
    args = parser.parse_args()
    if not args.yes_live_write:
        parser.error("--yes-live-write is required")
    cookie_file = os.path.abspath(args.cookie_file)
    if not os.path.isfile(cookie_file):
        parser.error("cookie file was not found")
    return asyncio.run(_run(cookie_file, args.keep_remote))


if __name__ == "__main__":
    raise SystemExit(main())
