from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from json import loads
from logging import getLogger
from os.path import exists
from random import uniform
from re import fullmatch
from time import sleep, time

from googleapiclient.errors import HttpError

from .helper import GoogleDriveHelper

LOGGER = getLogger(__name__)

API_MAX_RETRIES = 7
API_MAX_BACKOFF = 64
API_MAX_RETRY_AFTER = 300
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
RETRYABLE_DRIVE_REASONS = {
    "backendError",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}


class GoogleDrivePurge(GoogleDriveHelper):
    def __init__(self):
        super().__init__()
        self.target_id = ""
        self.target_name = ""
        self.items = []
        self.item_by_id = {}
        self.files = []
        self.folders = []
        self.children = {}
        self.descendant_file_count = {}
        self.started_at = time()

    def prepare(self, target, user_id):
        try:
            self.target_id = self.resolve_target_id(target, user_id)
        except (KeyError, IndexError):
            raise ValueError("Google Drive ID could not be found in the provided target")
        self.service = self.authorize()
        try:
            return self._validate_target()
        except Exception as err:
            if self._should_use_token_fallback(err):
                self.alt_auth = True
                self.use_sa = False
                self.token_path = "token.pickle"
                LOGGER.warning(
                    "Purge target is unavailable through service accounts. "
                    "Retrying with token.pickle."
                )
                self.service = self.authorize()
                return self._validate_target()
            raise

    def resolve_target_id(self, target, user_id=""):
        target = str(target).strip()
        if target.startswith("mtp:"):
            self.use_sa = False
            self.token_path = f"tokens/{user_id}.pickle"
            target = target[4:]
        elif target.startswith("sa:"):
            self.use_sa = True
            target = target[3:]
        elif target.startswith("tp:"):
            self.use_sa = False
            target = target[3:]
        if target == "root" or fullmatch(r"[A-Za-z0-9_-]{10,}", target):
            return target
        return self.get_id_from_url(target)

    def _validate_target(self):
        meta = self.get_target_metadata(self.target_id)
        mime_type = meta.get("mimeType")
        if self.target_id != "root" and mime_type != self.G_DRIVE_DIR_MIME_TYPE:
            raise ValueError("Drive purge target must be a folder or Drive root")
        capabilities = meta.get("capabilities", {})
        if capabilities.get("canListChildren") is False:
            raise PermissionError("The configured Google Drive account cannot list this target")
        if (
            capabilities
            and capabilities.get("canDeleteChildren") is False
            and capabilities.get("canRemoveChildren") is False
        ):
            raise PermissionError(
                "The configured Google Drive account cannot delete items from this target"
            )
        self.target_name = meta.get("name") or self.target_id
        return meta

    def _should_use_token_fallback(self, error):
        if self.alt_auth or not self.use_sa or not exists("token.pickle"):
            return False
        if isinstance(error, PermissionError):
            return True
        error_text = str(error)
        return isinstance(error, HttpError) and (
            "File not found" in error_text
            or "insufficientFilePermissions" in error_text
            or "notFound" in error_text
        )

    @staticmethod
    def _http_error_reason(error):
        content = getattr(error, "content", b"")
        if isinstance(content, bytes):
            content = content.decode("utf-8", "ignore")
        try:
            payload = loads(content or "{}")
            details = payload.get("error", {}).get("errors", [])
            if details:
                return details[0].get("reason", "")
        except (TypeError, ValueError):
            pass
        return ""

    @classmethod
    def _is_retryable_error(cls, error):
        if isinstance(error, (TimeoutError, ConnectionError)):
            return True
        if not isinstance(error, HttpError):
            return False
        status = getattr(getattr(error, "resp", None), "status", None)
        return status in RETRYABLE_HTTP_STATUSES or (
            status == 403 and cls._http_error_reason(error) in RETRYABLE_DRIVE_REASONS
        )

    @staticmethod
    def _retry_after_seconds(error):
        response = getattr(error, "resp", None)
        if response is None:
            return 0
        value = response.get("retry-after")
        if not value:
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                remaining = retry_at - datetime.now(timezone.utc)
                return max(0, int(remaining.total_seconds()))
            except (TypeError, ValueError, OverflowError):
                return 0

    def _execute_with_backoff(self, request, operation):
        for attempt in range(API_MAX_RETRIES + 1):
            try:
                return request.execute()
            except Exception as error:
                if attempt >= API_MAX_RETRIES or not self._is_retryable_error(error):
                    raise
                retry_after = min(
                    self._retry_after_seconds(error),
                    API_MAX_RETRY_AFTER,
                )
                backoff = min((2**attempt) + uniform(0, 1), API_MAX_BACKOFF)
                delay = max(retry_after, backoff)
                reason = self._http_error_reason(error) or getattr(
                    getattr(error, "resp", None),
                    "status",
                    type(error).__name__,
                )
                LOGGER.warning(
                    "Drive purge %s throttled; retrying in %.2fs "
                    "(attempt %s/%s, reason=%s)",
                    operation,
                    delay,
                    attempt + 1,
                    API_MAX_RETRIES,
                    reason,
                )
                sleep(delay)

    def get_target_metadata(self, file_id):
        request = (
            self.service.files()
            .get(
                fileId=file_id,
                supportsAllDrives=True,
                fields=(
                    "id, name, mimeType, "
                    "capabilities(canListChildren, canDeleteChildren, canRemoveChildren)"
                ),
            )
        )
        return self._execute_with_backoff(request, "target metadata request")

    def get_children(self, folder_id):
        page_token = None
        files = []
        q = f"'{folder_id}' in parents and trashed = false"
        while True:
            request = (
                self.service.files()
                .list(
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    q=q,
                    spaces="drive",
                    pageSize=1000,
                    fields=(
                        "nextPageToken, files("
                        "id, name, mimeType, size, createdTime, modifiedTime, parents, "
                        "capabilities(canDelete, canMoveItemWithinDrive))"
                    ),
                    orderBy="folder, createdTime",
                    pageToken=page_token,
                )
            )
            response = self._execute_with_backoff(request, "folder listing")
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if page_token is None:
                break
        return files

    def scan(self):
        self.items.clear()
        self.item_by_id.clear()
        self.files.clear()
        self.folders.clear()
        self.children.clear()
        self.descendant_file_count.clear()
        self.proc_bytes = 0
        self.total_files = 0
        self.total_folders = 0
        self._scan_folder(self.target_id, 0)
        self._compute_descendant_file_count(self.target_id)
        return self.summary()

    def _scan_folder(self, folder_id, depth):
        children = self.get_children(folder_id)
        self.children[folder_id] = []
        for item in children:
            item["parent_id"] = folder_id
            item["depth"] = depth
            item["size_int"] = int(item.get("size", 0) or 0)
            self.items.append(item)
            self.item_by_id[item["id"]] = item
            self.children[folder_id].append(item["id"])
            if item.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
                self.total_folders += 1
                self.folders.append(item)
                self._scan_folder(item["id"], depth + 1)
            else:
                self.total_files += 1
                self.files.append(item)
                self.proc_bytes += item["size_int"]

    def _compute_descendant_file_count(self, folder_id):
        count = 0
        child_ids = self.children.get(folder_id, [])
        for child_id in child_ids:
            item = self.item_by_id[child_id]
            if item.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
                count += self._compute_descendant_file_count(child_id)
            else:
                count += 1
        self.descendant_file_count[folder_id] = count
        return count

    def summary(self):
        return {
            "target_id": self.target_id,
            "target_name": self.target_name,
            "files": self.total_files,
            "folders": self.total_folders,
            "size": self.proc_bytes,
            "undeletable": sum(
                1
                for item in self.items
                if item.get("capabilities", {}).get("canDelete") is False
            ),
        }

    def build_plan(self, mode, value=None):
        mode = mode.lower()
        if mode == "all":
            files = list(self.files)
            folders = list(self.folders)
            move_files = []
        elif mode == "age":
            files, folders = self._age_plan(float(value))
            move_files = []
        elif mode == "range":
            files = list(self.files[: int(value)])
            folders = []
            move_files = []
        elif mode == "files":
            files = list(self.files)
            folders = []
            move_files = []
        elif mode == "empty_folders":
            files = []
            folders = [
                folder
                for folder in self.folders
                if self.descendant_file_count.get(folder["id"], 0) == 0
            ]
            move_files = []
        elif mode == "folders":
            files = []
            folders = list(self.folders)
            move_files = [
                item for item in self.files if item.get("parent_id") != self.target_id
            ]
        else:
            raise ValueError(f"Unknown purge mode: {mode}")

        folder_ids = {folder["id"] for folder in folders}
        folders = sorted(folders, key=lambda item: item.get("depth", 0), reverse=True)
        size = sum(item.get("size_int", 0) for item in files)
        blocked_delete = [
            item
            for item in [*files, *folders]
            if item.get("capabilities", {}).get("canDelete") is False
        ]
        blocked_move = [
            item
            for item in move_files
            if item.get("capabilities", {}).get("canMoveItemWithinDrive") is False
        ]
        return {
            "mode": mode,
            "value": value,
            "files": files,
            "folders": folders,
            "folder_ids": folder_ids,
            "move_files": move_files,
            "blocked_delete": blocked_delete,
            "blocked_move": blocked_move,
            "size": size,
            "total": len(files) + len(folders),
        }

    def _age_plan(self, days):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        old_file_ids = {
            item["id"] for item in self.files if self._is_older_than(item, cutoff)
        }
        old_folder_ids = {
            item["id"] for item in self.folders if self._is_older_than(item, cutoff)
        }
        safe_folder_ids = set()
        for folder in sorted(
            self.folders, key=lambda item: item.get("depth", 0), reverse=True
        ):
            if folder["id"] not in old_folder_ids:
                continue
            can_delete = True
            for child_id in self.children.get(folder["id"], []):
                child = self.item_by_id[child_id]
                if child.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
                    if child_id not in safe_folder_ids:
                        can_delete = False
                        break
                elif child_id not in old_file_ids:
                    can_delete = False
                    break
            if can_delete:
                safe_folder_ids.add(folder["id"])
        files = [item for item in self.files if item["id"] in old_file_ids]
        folders = [item for item in self.folders if item["id"] in safe_folder_ids]
        return files, folders

    @staticmethod
    def _is_older_than(item, cutoff):
        dates = []
        for key in ("createdTime", "modifiedTime"):
            value = item.get(key)
            if value:
                dates.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        return bool(dates) and max(dates) < cutoff

    def delete_item(self, item_id):
        try:
            request = (
                self.service.files()
                .delete(fileId=item_id, supportsAllDrives=True)
            )
            return self._execute_with_backoff(request, "item deletion")
        except HttpError as err:
            if getattr(getattr(err, "resp", None), "status", None) == 404:
                return {}
            raise

    def delete_batch(self, items):
        if not items:
            return
        completed = set()
        failed = {}

        def callback(request_id, _, exception):
            if exception:
                failed[request_id] = exception
            else:
                completed.add(request_id)

        batch = self.service.new_batch_http_request(callback=callback)
        for item in items:
            batch.add(
                self.service.files().delete(
                    fileId=item["id"],
                    supportsAllDrives=True,
                ),
                request_id=item["id"],
            )
        try:
            batch.execute()
        except Exception as err:
            LOGGER.warning(
                "Google Drive batch delete failed; retrying unconfirmed items "
                "individually: %s",
                err,
            )

        retry_items = [
            item
            for item in items
            if item["id"] not in completed or item["id"] in failed
        ]
        for item in retry_items:
            try:
                self.delete_item(item["id"])
                completed.add(item["id"])
                failed.pop(item["id"], None)
            except Exception as err:
                failed[item["id"]] = err
        return completed, failed

    def move_file_to_target_root(self, item):
        parents = item.get("parents") or [item.get("parent_id")]
        remove_parents = ",".join(
            parent
            for parent in parents
            if parent and parent != self.target_id
        )
        if not remove_parents:
            return {"id": item["id"], "parents": [self.target_id]}
        request = (
            self.service.files()
            .update(
                fileId=item["id"],
                addParents=self.target_id,
                removeParents=remove_parents,
                fields="id, parents",
                supportsAllDrives=True,
            )
        )
        return self._execute_with_backoff(request, "item move")

    @staticmethod
    def log_operation(user, target, mode, deleted_files, deleted_folders, size, elapsed):
        username = getattr(user, "username", None) or getattr(user, "title", None) or ""
        LOGGER.info(
            "Drive purge operation | "
            f"user_id={getattr(user, 'id', '')} | "
            f"username={username} | "
            f"target_drive_id={target.get('target_id')} | "
            f"target_drive_name={target.get('target_name')} | "
            f"mode={mode} | "
            f"deleted_files={deleted_files} | "
            f"deleted_folders={deleted_folders} | "
            f"recovered_size={size} | "
            f"execution_time={elapsed:.2f}s | "
            f"timestamp={datetime.now(timezone.utc).isoformat()}"
        )
