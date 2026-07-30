import json
import os
import time

from bot import DOWNLOAD_DIR

_BASE_DIR = os.path.join(DOWNLOAD_DIR, ".terabox_selections")
_STALE_AFTER_SECONDS = 6 * 60 * 60


def _path(gid: str) -> str:
    return os.path.join(_BASE_DIR, f"{gid}.json")


def _is_safe_gid(gid: str) -> bool:
    return bool(
        isinstance(gid, str)
        and gid
        and all(char.isalnum() or char in "-_" for char in gid)
    )


def write_state(gid: str, file_list_metadata: list, selected_ids) -> bool:
    if not _is_safe_gid(gid):
        return False
    tmp = ""
    try:
        os.makedirs(_BASE_DIR, exist_ok=True)
        target = _path(gid)
        tmp = f"{target}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
        payload = {
            "file_list": file_list_metadata,
            "selected_ids": list(selected_ids),
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp, target)
        return True
    except OSError:
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def read_state(gid: str) -> dict | None:
    if not _is_safe_gid(gid):
        return None
    try:
        with open(_path(gid), encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def update_selected_ids(gid: str, selected_ids) -> bool:
    data = read_state(gid)
    if data is None:
        return False
    file_list = data.get("file_list", [])
    file_list = file_list if isinstance(file_list, list) else []
    allowed_ids = {
        str(item["id"])
        for item in file_list
        if isinstance(item, dict) and item.get("id") is not None
    }
    requested_ids = [str(value) for value in selected_ids]
    if any(value not in allowed_ids for value in requested_ids):
        return False
    return write_state(
        gid,
        file_list,
        list(dict.fromkeys(requested_ids)),
    )


def delete_state(gid: str) -> None:
    if _is_safe_gid(gid):
        try:
            os.remove(_path(gid))
        except (FileNotFoundError, OSError):
            pass


def get_file_list(gid: str) -> list | None:
    data = read_state(gid)
    file_list = data.get("file_list") if data else None
    return file_list if isinstance(file_list, list) else None


def get_selected_ids(gid: str) -> list:
    data = read_state(gid)
    selected = data.get("selected_ids", []) if data else []
    return selected if isinstance(selected, list) else []


def cleanup_stale_states(max_age_seconds: int = _STALE_AFTER_SECONDS) -> int:
    if not os.path.isdir(_BASE_DIR):
        return 0
    deadline = time.time() - max_age_seconds
    removed = 0
    try:
        for entry in os.scandir(_BASE_DIR):
            if not entry.is_file() or not (
                entry.name.endswith(".json") or ".tmp" in entry.name
            ):
                continue
            try:
                if entry.stat().st_mtime < deadline:
                    os.remove(entry.path)
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed
