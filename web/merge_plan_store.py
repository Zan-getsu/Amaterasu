import json
import os
import re
import time
from contextlib import contextmanager
from hashlib import sha256

if os.name == "nt":
    import msvcrt
else:
    import fcntl

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
    # Keep the inode stable: deleting an age-based lock can let two processes
    # believe they both own the plan while a slow but live holder is working.
    handle = open(lock_path, "a+b")
    deadline = time.monotonic() + 2
    try:
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out while locking the merge plan") from None
                time.sleep(0.01)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _write_unlocked(plan_id, data, *, order_change=False):
    target = _path(plan_id)
    tmp = f"{target}.{os.getpid()}.{time.time_ns()}.tmp"
    data["updated_at"] = int(time.time())
    data["revision"] = int(data.get("revision", 0)) + 1
    if order_change:
        data["order_revision"] = int(data.get("order_revision", 0)) + 1
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


def create_plan(plan_id, owner_id, chat_id, title, expected_sources=1, mode="copy", profile_name=""):
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
        "mode": "encode" if mode == "encode" else "copy",
        "profile_name": str(profile_name or "")[:100],
        "locked": False,
        "enumeration_complete": False,
        "order_saved": False,
        "items": [],
        "created_at": now,
        "updated_at": now,
        "revision": 0,
        "order_revision": 0,
    }
    try:
        with _plan_lock(plan_id):
            if os.path.exists(_path(plan_id)):
                return True
            return _write_unlocked(plan_id, data, order_change=True)
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
            changed_order = False
            if not any(item.get("source_id") == source_id for item in items):
                pending_index = next(
                    (
                        index
                        for index, item in enumerate(items)
                        if item.get("placeholder")
                        and str(item.get("source_id", "")).startswith("pending_")
                        and int(item.get("original_index", 0)) == int(position)
                    ),
                    None,
                )
                replacement = _source_placeholder(source_id, position, label)
                if pending_index is None:
                    items.append(replacement)
                    if not data.get("order_saved"):
                        items.sort(key=lambda item: int(item.get("original_index", 0)))
                else:
                    # Keep the user's current drag order while binding the
                    # placeholder to the real task that has just started.
                    items[pending_index] = replacement
                changed_order = True
            data["items"] = items
            sources = {
                item.get("source_id")
                for item in items
                if item.get("source_id") and not item["source_id"].startswith("pending_")
            }
            if len(sources) >= int(data.get("expected_sources", 1)):
                data["enumeration_complete"] = True
                data["status"] = "downloading"
            _write_unlocked(plan_id, data, order_change=changed_order)
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
        # Preserve case and occurrence: two Linux paths differing only by case
        # and repeated provider items must never collapse into one timeline ID.
        item_key = str(item.get("key") or f"ordinal:{item_ordinal}").replace("\\", "/")
        item_suffix = (
            sha256(item_key.encode("utf-8")).hexdigest()[:16]
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
    if len({item["id"] for item in replacements}) != len(replacements):
        return None
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None or data.get("locked"):
                return data
            items = data.get("items", [])
            old_files = [
                item for item in items
                if item.get("source_id") == source_id and not item.get("placeholder")
            ]
            replacement_by_id = {item["id"]: item for item in replacements}
            old_ids = {item["id"] for item in old_files}
            if data.get("order_saved") and not old_ids.issubset(replacement_by_id):
                data["inventory_error"] = (
                    "A selected file changed identity after the order was saved. "
                    "The merge cannot silently substitute another file."
                )
                _write_unlocked(plan_id, data)
                return data
            data.pop("inventory_error", None)
            updated = []
            seen = set()
            source_slot = None
            for item in items:
                if item.get("source_id") != source_id:
                    updated.append(item)
                    continue
                if source_slot is None:
                    source_slot = len(updated)
                replacement = replacement_by_id.get(item.get("id"))
                if replacement is not None and replacement["id"] not in seen:
                    updated.append(replacement)
                    seen.add(replacement["id"])
            if source_slot is None:
                source_slot = len(updated)
            remaining = [item for item in replacements if item["id"] not in seen]
            # A placeholder reserves the insertion point. Existing items from
            # this source keep their interleaved positions after a readiness
            # update; newly discovered items are inserted at the source slot.
            updated[source_slot:source_slot] = remaining
            old_order = [item.get("id") for item in items]
            data["items"] = updated
            _write_unlocked(
                plan_id,
                data,
                order_change=old_order != [item["id"] for item in updated],
            )
            return data
    except (OSError, TimeoutError):
        return None


def sync_final_files(plan_id, files):
    if not _is_safe_id(plan_id):
        return None
    grouped = {}
    positions = {}
    seen_paths = set()
    for item in files:
        if not isinstance(item, dict):
            return None
        source_id = str(item.get("source_id") or "")
        if not _is_safe_id(source_id):
            return None
        relative = str(item.get("path") or "").replace("\\", "/")
        if (
            not relative
            or relative.startswith("/")
            or ":" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or relative in seen_paths
        ):
            return None
        seen_paths.add(relative)
        grouped.setdefault(source_id, []).append(item)
        positions.setdefault(source_id, int(item.get("position") or 1))
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if (
                data is None
                or data.get("locked")
                or not data.get("enumeration_complete")
                or len(grouped) != int(data.get("expected_sources", 1))
            ):
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
                normalized_ids = {item["id"] for item in normalized}
                if len(normalized_ids) != len(normalized):
                    return None
                if data.get("order_saved") and any(
                    item["id"] not in normalized_ids for item in old_source_files
                ):
                    data["inventory_error"] = (
                        "A saved file identity no longer matches the downloaded "
                        "file. The merge stopped to preserve the chosen order."
                    )
                    _write_unlocked(plan_id, data)
                    return None
                final_by_source[source_id] = normalized
                final_by_id.update({item["id"]: item for item in normalized})

            if len(final_by_id) != len(files):
                return None

            ordered = []
            seen = set()
            expanded_sources = set()
            for old in old_items:
                item_id = old.get("id")
                source_id = old.get("source_id")
                if item_id in final_by_id and item_id not in seen:
                    ordered.append(final_by_id[item_id])
                    seen.add(item_id)
                elif old.get("placeholder") and source_id in final_by_source and source_id not in expanded_sources:
                    for item in final_by_source[source_id]:
                        if item["id"] not in seen:
                            ordered.append(item)
                            seen.add(item["id"])
                    expanded_sources.add(source_id)
            for source_id, source_files in final_by_source.items():
                remaining = [item for item in source_files if item["id"] not in seen]
                if remaining:
                    last = next(
                        (index for index in range(len(ordered) - 1, -1, -1)
                         if ordered[index]["source_id"] == source_id),
                        len(ordered) - 1,
                    )
                    ordered[last + 1:last + 1] = remaining
                    seen.update(item["id"] for item in remaining)

            if len(ordered) != len(files):
                return None

            data["items"] = ordered
            data["status"] = "planning"
            data["locked"] = True
            data["frozen_order"] = [item["id"] for item in ordered]
            data.pop("inventory_error", None)
            _write_unlocked(plan_id, data, order_change=True)
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
            if revision is None or int(revision) != int(data.get("order_revision", 0)):
                return data, "The file list changed. Review the updated order and retry."
            items = data.get("items", [])
            by_id = {item.get("id"): item for item in items}
            if (
                len(by_id) != len(items)
                or len(order) != len(items)
                or len(set(order)) != len(order)
                or set(order) != set(by_id)
            ):
                return data, "Include every current item exactly once."
            data["items"] = [by_id[item_id] for item_id in order]
            data["order_saved"] = True
            _write_unlocked(plan_id, data, order_change=True)
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
            if data.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return False
            data["status"] = str(status or data.get("status") or "downloading")
            if locked is not None:
                data["locked"] = bool(locked)
            data["error"] = str(error or "")[:1000]
            return _write_unlocked(plan_id, data)
    except (OSError, TimeoutError):
        return False


def set_plan_details(plan_id, *, duration_seconds=None, subtitle_summary=""):
    if not _is_safe_id(plan_id):
        return False
    try:
        with _plan_lock(plan_id):
            data = read_plan(plan_id)
            if data is None or data.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                return False
            if duration_seconds is not None:
                data["duration_seconds"] = max(0, min(float(duration_seconds), 10**9))
            data["subtitle_summary"] = str(subtitle_summary or "")[:200]
            return _write_unlocked(plan_id, data)
    except (OSError, TimeoutError, TypeError, ValueError):
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
        "mode": data.get("mode", "copy"),
        "profile_name": data.get("profile_name", ""),
        "duration_seconds": data.get("duration_seconds"),
        "subtitle_summary": data.get("subtitle_summary", ""),
        "locked": bool(data.get("locked")),
        "error": data.get("error", ""),
        "expected_sources": int(data.get("expected_sources", 1)),
        "enumeration_complete": bool(data.get("enumeration_complete")),
        "source_count": len(
            {item.get("source_id") for item in raw_items if item.get("source_id")}
        ),
        "ready_count": sum(item["ready"] for item in items),
        "pending_count": sum(item["placeholder"] for item in items),
        "items": items,
        "revision": int(data.get("revision", 0)),
        "order_revision": int(data.get("order_revision", 0)),
        "order_saved": bool(data.get("order_saved")),
        "inventory_error": data.get("inventory_error", ""),
    }


def get_plan_owner_id(gid):
    plan_id = str(gid or "").removeprefix("merge_")
    data = read_plan(plan_id)
    return int(data["owner_id"]) if data and data.get("owner_id") is not None else None


def mark_interrupted_plans():
    """Keep crash artifacts and make abandoned, nonterminal plans honest at boot."""
    if not os.path.isdir(_BASE_DIR):
        return 0
    changed = 0
    try:
        entries = [entry.name for entry in os.scandir(_BASE_DIR)
                   if entry.is_file() and entry.name.endswith(".json")]
    except OSError:
        return 0
    for name in entries:
        plan_id = name.removesuffix(".json")
        if not _is_safe_id(plan_id):
            continue
        try:
            with _plan_lock(plan_id):
                data = read_plan(plan_id)
                if data is None or data.get("status") in {
                    "completed", "failed", "cancelled", "interrupted"
                }:
                    continue
                data["status"] = "interrupted"
                data["locked"] = True
                data["error"] = (
                    "The bot restarted before this merge finished. Downloaded "
                    "files were kept for recovery; the task will not upload twice."
                )
                changed += bool(_write_unlocked(plan_id, data))
        except (OSError, TimeoutError):
            continue
    return changed


def cleanup_stale_plans(max_age_seconds=_STALE_AFTER_SECONDS):
    if not os.path.isdir(_BASE_DIR):
        return 0
    deadline = time.time() - max_age_seconds
    removed = 0
    try:
        for entry in os.scandir(_BASE_DIR):
            if not entry.is_file() or not entry.name.endswith(".json"):
                continue
            try:
                if entry.stat().st_mtime >= deadline:
                    continue
                with open(entry.path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if data.get("status") not in {
                    "completed", "failed", "cancelled", "interrupted"
                }:
                    continue
                plan_id = entry.name.removesuffix(".json")
                with _plan_lock(plan_id):
                    # Recheck under the same lock used by writers.
                    if os.path.getmtime(entry.path) >= deadline:
                        continue
                    current = read_plan(plan_id)
                    if current is None or current.get("status") not in {
                        "completed", "failed", "cancelled", "interrupted"
                    }:
                        continue
                    os.remove(entry.path)
                    removed += 1
            except (OSError, ValueError, json.JSONDecodeError, TimeoutError):
                continue
    except OSError:
        pass
    return removed
