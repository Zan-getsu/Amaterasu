import json
import os
import re
import time
from contextlib import contextmanager
from hashlib import sha256

from bot import DOWNLOAD_DIR


_BASE_DIR = os.path.join(DOWNLOAD_DIR, ".merge_plans")
_STALE_AFTER_SECONDS = 6 * 60 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


def _is_safe_id(value):
    return bool(isinstance(value, str) and _SAFE_ID.fullmatch(value))


def _path(plan_id):
    return os.path.join(_BASE_DIR, f"{plan_id}.json")


@contextmanager
def _plan_lock(plan_id):
    os.makedirs(_BASE_DIR, exist_ok=True)
    lock_path = f"{_path(plan_id)}.lock"
    descriptor = None
    for _ in range(200):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > 30:
                    os.remove(lock_path)
                    continue
            except OSError:
                pass
            time.sleep(0.01)
    if descriptor is None:
        raise TimeoutError("Timed out while locking the merge plan")
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            os.remove(lock_path)
        except OSError:
            pass


def _write_unlocked(plan_id, data):
    target = _path(plan_id)
    tmp = f"{target}.{os.getpid()}.{time.time_ns()}.tmp"
    data["updated_at"] = int(time.time())
    data["revision"] = int(data.get("revision", 0)) + 1
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp, target)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def read_plan(plan_id):
    if not _is_safe_id(plan_id):
        return None
    try:
        with open(_path(plan_id), encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def create_plan(plan_id, owner_id, chat_id, title, expected_sources=1):
    if not _is_safe_id(plan_id):
        return False
    cleanup_stale_plans()
    now = int(time.time())
    data = {
        "version": 1,
        "owner_id": int(owner_id),
        "chat_id": int(chat_id),
        "title": str(title or "Merged video")[:240],
        "expected_sources": max(1, int(expected_sources or 1)),
        "status": "collecting",
        "locked": False,
        "items": [],
        "created_at": now,
        "updated_at": now,
        "revision": 0,
    }
    try:
        with _plan_lock(plan_id):
            if os.path.exists(_path(plan_id)):
                return True
            return _write_unlocked(plan_id, data)
    except (OSError, TimeoutError):
        return False


def _source_placeholder(source_id, position, label):
    return {
        "id": f"{source_id}_source",
        "source_id": source_id,
        "name": str(label or f"Item {position}")[:500],
        "path": "",
        "original_index": max(1, int(position)),
        "ready": False,
        "placeholder": True,
    }


def register_source(plan_id, source_id, position, label):
    if not (_is_safe_id(plan_id) and _is_safe_id(source_id)):
        return None
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None or data.get("locked"):
                return data
            items = data.get("items", [])
            if not any(item.get("source_id") == source_id for item in items):
                items.append(_source_placeholder(source_id, position, label))
                items.sort(key=lambda item: int(item.get("original_index", 0)))
            data["items"] = items
            sources = {item.get("source_id") for item in items}
            if len(sources) >= int(data.get("expected_sources", 1)):
                data["status"] = "downloading"
            _write_unlocked(plan_id, data)
            return data
    except (OSError, TimeoutError):
        return None


def _normalized_file_items(source_id, files, position=1, ready=False):
    normalized = []
    for ordinal, item in enumerate(files, start=1):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        item_ordinal = max(1, int(item.get("ordinal") or ordinal))
        item_key = str(item.get("key") or "").replace("\\", "/").casefold()
        item_suffix = (
            sha256(item_key.encode("utf-8")).hexdigest()[:16]
            if item_key
            else f"{item_ordinal:06d}"
        )
        normalized.append(
            {
                "id": f"{source_id}_{item_suffix}",
                "source_id": source_id,
                "name": str(item.get("name") or f"Item {item_ordinal}")[:500],
                "path": str(item.get("path") or ""),
                "original_index": max(1, int(position)) * 1_000_000 + item_ordinal,
                "ready": bool(item.get("ready", ready)),
                "placeholder": False,
            }
        )
    return normalized


def replace_source_files(plan_id, source_id, files, position=1, ready=False):
    if not (_is_safe_id(plan_id) and _is_safe_id(source_id)):
        return None
    replacements = _normalized_file_items(source_id, files, position, ready)
    if not replacements:
        return read_plan(plan_id)
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None or data.get("locked"):
                return data
            items = data.get("items", [])
            indexes = [
                index
                for index, item in enumerate(items)
                if item.get("source_id") == source_id
            ]
            insert_at = indexes[0] if indexes else len(items)
            old_by_id = {
                item.get("id"): item
                for item in items
                if item.get("source_id") == source_id
            }
            old_files = [
                item for item in old_by_id.values() if not item.get("placeholder")
            ]
            old_by_index = {
                int(item.get("original_index", 0)): item for item in old_files
            }
            preserve_ordinals = len(old_files) == len(replacements)
            for replacement in replacements:
                old = old_by_id.get(replacement["id"])
                if old is None and preserve_ordinals:
                    old = old_by_index.get(replacement["original_index"])
                if old:
                    replacement["id"] = old["id"]
                    replacement["original_index"] = old.get(
                        "original_index", replacement["original_index"]
                    )
            replacement_by_id = {item["id"]: item for item in replacements}
            ordered_replacements = [
                replacement_by_id[item.get("id")]
                for item in items
                if item.get("source_id") == source_id
                and item.get("id") in replacement_by_id
            ]
            ordered_ids = {item["id"] for item in ordered_replacements}
            ordered_replacements.extend(
                item for item in replacements if item["id"] not in ordered_ids
            )
            items = [item for item in items if item.get("source_id") != source_id]
            items[insert_at:insert_at] = ordered_replacements
            data["items"] = items
            _write_unlocked(plan_id, data)
            return data
    except (OSError, TimeoutError):
        return None


def sync_final_files(plan_id, files):
    if not _is_safe_id(plan_id):
        return None
    grouped = {}
    positions = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "")
        if not _is_safe_id(source_id):
            continue
        grouped.setdefault(source_id, []).append(item)
        positions.setdefault(source_id, int(item.get("position") or 1))
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None:
                return None
            old_items = data.get("items", [])
            old_positions = {}
            for old in old_items:
                original_index = max(1, int(old.get("original_index", 1)))
                old_positions.setdefault(
                    old.get("source_id"),
                    original_index // 1_000_000
                    if original_index >= 1_000_000
                    else original_index,
                )
            final_by_id = {}
            final_by_source = {}
            for source_id, source_files in grouped.items():
                normalized = _normalized_file_items(
                    source_id,
                    source_files,
                    old_positions.get(source_id, positions[source_id]),
                    ready=True,
                )
                old_source_files = [
                    item
                    for item in old_items
                    if item.get("source_id") == source_id
                    and not item.get("placeholder")
                ]
                if len(old_source_files) == len(normalized):
                    old_by_index = {
                        int(item.get("original_index", 0)): item
                        for item in old_source_files
                    }
                    for item in normalized:
                        old = old_by_index.get(item["original_index"])
                        if old:
                            item["id"] = old["id"]
                final_by_source[source_id] = normalized
                final_by_id.update({item["id"]: item for item in normalized})

            ordered = []
            seen = set()
            expanded_sources = set()
            for old in old_items:
                item_id = old.get("id")
                source_id = old.get("source_id")
                if item_id in final_by_id and item_id not in seen:
                    ordered.append(final_by_id[item_id])
                    seen.add(item_id)
                    expanded_sources.add(source_id)
                elif source_id in final_by_source and source_id not in expanded_sources:
                    for item in final_by_source[source_id]:
                        if item["id"] not in seen:
                            ordered.append(item)
                            seen.add(item["id"])
                    expanded_sources.add(source_id)
            for source_id, source_files in final_by_source.items():
                if source_id in expanded_sources:
                    continue
                for item in source_files:
                    if item["id"] not in seen:
                        ordered.append(item)
                        seen.add(item["id"])

            data["items"] = ordered
            data["status"] = "merging"
            data["locked"] = True
            _write_unlocked(plan_id, data)
            return data
    except (OSError, TimeoutError):
        return None


def update_order(plan_id, order, revision=None):
    if not _is_safe_id(plan_id) or not isinstance(order, list):
        return None, "Invalid merge order."
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None:
                return None, "Merge plan not found or expired."
            if data.get("locked"):
                return data, "This merge has already started."
            if revision is not None and int(revision) != int(data.get("revision", 0)):
                return data, "The file list changed. Review the updated order and retry."
            items = data.get("items", [])
            by_id = {item.get("id"): item for item in items}
            if len(order) != len(by_id) or set(order) != set(by_id):
                return data, "Include every current item exactly once."
            data["items"] = [by_id[item_id] for item_id in order]
            _write_unlocked(plan_id, data)
            return data, ""
    except (OSError, TimeoutError, TypeError, ValueError):
        return None, "Could not save the merge order."


def set_plan_status(plan_id, status, *, locked=None, error=""):
    if not _is_safe_id(plan_id):
        return False
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None:
                return False
            data["status"] = str(status or data.get("status") or "downloading")
            if locked is not None:
                data["locked"] = bool(locked)
            data["error"] = str(error or "")[:1000]
            return _write_unlocked(plan_id, data)
    except (OSError, TimeoutError):
        return False


def public_plan(data):
    if not isinstance(data, dict):
        return None
    raw_items = data.get("items", [])
    items = []
    for item in raw_items:
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "original_index": item.get("original_index"),
                "ready": bool(item.get("ready")),
                "placeholder": bool(item.get("placeholder")),
            }
        )
    return {
        "title": data.get("title"),
        "status": data.get("status"),
        "locked": bool(data.get("locked")),
        "error": data.get("error", ""),
        "expected_sources": int(data.get("expected_sources", 1)),
        "source_count": len(
            {item.get("source_id") for item in raw_items if item.get("source_id")}
        ),
        "ready_count": sum(item["ready"] for item in items),
        "items": items,
        "revision": int(data.get("revision", 0)),
    }


def get_plan_owner_id(gid):
    plan_id = str(gid or "").removeprefix("merge_")
    data = read_plan(plan_id)
    return int(data["owner_id"]) if data and data.get("owner_id") is not None else None


def cleanup_stale_plans(max_age_seconds=_STALE_AFTER_SECONDS):
    if not os.path.isdir(_BASE_DIR):
        return 0
    deadline = time.time() - max_age_seconds
    removed = 0
    try:
        for entry in os.scandir(_BASE_DIR):
            if not entry.is_file() or not (
                entry.name.endswith(".json") or entry.name.endswith(".lock") or ".tmp" in entry.name
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
