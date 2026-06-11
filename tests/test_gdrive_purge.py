import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_purge_class():
    googleapiclient = types.ModuleType("googleapiclient")
    google_errors = types.ModuleType("googleapiclient.errors")

    class HttpError(Exception):
        pass

    google_errors.HttpError = HttpError
    googleapiclient.errors = google_errors
    sys.modules["googleapiclient"] = googleapiclient
    sys.modules["googleapiclient.errors"] = google_errors

    tenacity = types.ModuleType("tenacity")

    def retry(**_):
        return lambda func: func

    tenacity.retry = retry
    tenacity.retry_if_exception_type = lambda *_: None
    tenacity.stop_after_attempt = lambda *_: None
    tenacity.wait_exponential = lambda **_: None
    sys.modules["tenacity"] = tenacity

    package_names = [
        "bot",
        "bot.helper",
        "bot.helper.mirror_leech_utils",
        "bot.helper.mirror_leech_utils.gdrive_utils",
    ]
    for package_name in package_names:
        package = types.ModuleType(package_name)
        package.__path__ = []
        sys.modules[package_name] = package

    helper_module = types.ModuleType(
        "bot.helper.mirror_leech_utils.gdrive_utils.helper"
    )

    class GoogleDriveHelper:
        G_DRIVE_DIR_MIME_TYPE = "application/vnd.google-apps.folder"

    helper_module.GoogleDriveHelper = GoogleDriveHelper
    sys.modules[helper_module.__name__] = helper_module

    module_name = "bot.helper.mirror_leech_utils.gdrive_utils.purge"
    module_path = (
        Path(__file__).resolve().parents[1]
        / "bot"
        / "helper"
        / "mirror_leech_utils"
        / "gdrive_utils"
        / "purge.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.GoogleDrivePurge


GoogleDrivePurge = _load_purge_class()
FOLDER_MIME = "application/vnd.google-apps.folder"


def _item(
    item_id,
    *,
    folder=False,
    parent="root",
    depth=0,
    size=0,
    old=True,
    can_delete=True,
    can_move=True,
):
    timestamp = datetime.now(timezone.utc) - timedelta(days=90 if old else 1)
    return {
        "id": item_id,
        "name": item_id,
        "mimeType": FOLDER_MIME if folder else "application/octet-stream",
        "parent_id": parent,
        "parents": [parent],
        "depth": depth,
        "size_int": size,
        "createdTime": timestamp.isoformat(),
        "modifiedTime": timestamp.isoformat(),
        "capabilities": {
            "canDelete": can_delete,
            "canMoveItemWithinDrive": can_move,
        },
    }


def _purge(files, folders, children=None, descendant_file_count=None):
    purge = GoogleDrivePurge.__new__(GoogleDrivePurge)
    purge.target_id = "root"
    purge.files = files
    purge.folders = folders
    purge.items = [*files, *folders]
    purge.item_by_id = {item["id"]: item for item in purge.items}
    purge.children = children or {}
    purge.descendant_file_count = descendant_file_count or {}
    return purge


class GoogleDrivePurgePlanTests(unittest.TestCase):
    def test_prepare_mirrors_del_service_account_token_fallback(self):
        purge = GoogleDrivePurge.__new__(GoogleDrivePurge)
        purge.alt_auth = False
        purge.use_sa = True
        purge.token_path = "accounts"
        purge.get_id_from_url = lambda target, user_id: target
        purge.authorize = lambda: object()
        attempts = []

        def validate():
            attempts.append(purge.use_sa)
            if len(attempts) == 1:
                raise PermissionError("insufficientFilePermissions")
            return {"id": "drive-id", "name": "Drive"}

        purge._validate_target = validate
        method_globals = purge._should_use_token_fallback.__func__.__globals__
        original_exists = method_globals["exists"]
        method_globals["exists"] = lambda _: True
        try:
            result = purge.prepare("drive-id", 123)
        finally:
            method_globals["exists"] = original_exists

        self.assertEqual(result["id"], "drive-id")
        self.assertEqual(attempts, [True, False])
        self.assertFalse(purge.use_sa)
        self.assertTrue(purge.alt_auth)
        self.assertEqual(purge.token_path, "token.pickle")

    def test_range_selects_only_requested_files(self):
        files = [_item(str(index), size=index) for index in range(5)]
        plan = _purge(files, []).build_plan("range", 3)
        self.assertEqual([item["id"] for item in plan["files"]], ["0", "1", "2"])
        self.assertEqual(plan["size"], 3)
        self.assertEqual(plan["folders"], [])

    def test_folder_only_moves_nested_files_but_preserves_root_files(self):
        root_file = _item("root-file", parent="root")
        nested_file = _item("nested-file", parent="folder")
        folder = _item("folder", folder=True, parent="root")
        plan = _purge([root_file, nested_file], [folder]).build_plan("folders")
        self.assertEqual([item["id"] for item in plan["move_files"]], ["nested-file"])
        self.assertEqual([item["id"] for item in plan["folders"]], ["folder"])
        self.assertEqual(plan["files"], [])

    def test_empty_folder_mode_removes_only_trees_without_files(self):
        empty = _item("empty", folder=True)
        contains_file = _item("contains-file", folder=True)
        plan = _purge(
            [],
            [empty, contains_file],
            descendant_file_count={"empty": 0, "contains-file": 2},
        ).build_plan("empty_folders")
        self.assertEqual([item["id"] for item in plan["folders"]], ["empty"])

    def test_age_mode_does_not_delete_folder_containing_newer_file(self):
        unsafe_folder = _item("unsafe-folder", folder=True, old=True)
        safe_folder = _item("safe-folder", folder=True, old=True)
        old_file = _item("old-file", parent="unsafe-folder", old=True)
        new_file = _item("new-file", parent="unsafe-folder", old=False)
        safe_old_file = _item("safe-old-file", parent="safe-folder", old=True)
        children = {
            "root": ["unsafe-folder", "safe-folder"],
            "unsafe-folder": ["old-file", "new-file"],
            "safe-folder": ["safe-old-file"],
        }
        plan = _purge(
            [old_file, new_file, safe_old_file],
            [unsafe_folder, safe_folder],
            children,
        ).build_plan("age", 30)
        self.assertEqual(
            {item["id"] for item in plan["files"]},
            {"old-file", "safe-old-file"},
        )
        self.assertEqual(
            {item["id"] for item in plan["folders"]},
            {"safe-folder"},
        )

    def test_plan_reports_delete_and_move_permission_blocks(self):
        blocked_file = _item("blocked-file", can_delete=False)
        blocked_move = _item(
            "blocked-move",
            parent="folder",
            can_move=False,
        )
        folder = _item("folder", folder=True)
        files_plan = _purge([blocked_file], []).build_plan("files")
        folder_plan = _purge([blocked_move], [folder]).build_plan("folders")
        self.assertEqual([item["id"] for item in files_plan["blocked_delete"]], ["blocked-file"])
        self.assertEqual([item["id"] for item in folder_plan["blocked_move"]], ["blocked-move"])

    def test_batch_delete_retries_failed_items_individually(self):
        purge = GoogleDrivePurge.__new__(GoogleDrivePurge)
        retried = []

        class Files:
            @staticmethod
            def delete(fileId, supportsAllDrives):
                self.assertTrue(supportsAllDrives)
                return fileId

        class Batch:
            def __init__(self, callback):
                self.callback = callback
                self.requests = []

            def add(self, request, request_id):
                self.requests.append((request, request_id))

            def execute(self):
                for _, request_id in self.requests:
                    error = RuntimeError("rate limited") if request_id == "retry" else None
                    self.callback(request_id, {}, error)

        class Service:
            @staticmethod
            def files():
                return Files()

            @staticmethod
            def new_batch_http_request(callback):
                return Batch(callback)

        purge.service = Service()
        purge.delete_item = lambda item_id: retried.append(item_id)
        completed, failed = purge.delete_batch(
            [{"id": "ok"}, {"id": "retry"}]
        )
        self.assertEqual(completed, {"ok", "retry"})
        self.assertEqual(failed, {})
        self.assertEqual(retried, ["retry"])

    def test_batch_delete_returns_unrecovered_failures(self):
        purge = GoogleDrivePurge.__new__(GoogleDrivePurge)

        class Files:
            @staticmethod
            def delete(fileId, supportsAllDrives):
                return fileId

        class Batch:
            def __init__(self, callback):
                self.callback = callback
                self.requests = []

            def add(self, request, request_id):
                self.requests.append((request, request_id))

            def execute(self):
                for _, request_id in self.requests:
                    self.callback(request_id, {}, RuntimeError("denied"))

        class Service:
            @staticmethod
            def files():
                return Files()

            @staticmethod
            def new_batch_http_request(callback):
                return Batch(callback)

        purge.service = Service()

        def fail_delete(_):
            raise RuntimeError("still denied")

        purge.delete_item = fail_delete
        completed, failed = purge.delete_batch([{"id": "blocked"}])
        self.assertEqual(completed, set())
        self.assertEqual(list(failed), ["blocked"])


if __name__ == "__main__":
    unittest.main()
