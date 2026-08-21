from importlib import import_module
from pickle import dump, load
from sys import modules
from types import ModuleType
from unittest.mock import patch

import pytest
from google.auth.exceptions import RefreshError

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg


@pytest.fixture
def gdrive_modules(monkeypatch):
    """Load Drive helpers without requiring the local optional API wheel."""
    package = ModuleType("googleapiclient")
    package.__path__ = []
    discovery = ModuleType("googleapiclient.discovery")
    discovery.build = lambda *_args, **_kwargs: object()
    tenacity = ModuleType("tenacity")

    def retry(*_args, **_kwargs):
        return lambda function: function

    tenacity.RetryError = type("RetryError", (Exception,), {})
    tenacity.retry = retry
    tenacity.retry_if_exception = lambda *_args, **_kwargs: object()
    tenacity.retry_if_exception_type = lambda *_args, **_kwargs: object()
    tenacity.stop_after_attempt = lambda *_args, **_kwargs: object()
    tenacity.wait_exponential = lambda *_args, **_kwargs: object()

    monkeypatch.setitem(modules, "googleapiclient", package)
    monkeypatch.setitem(modules, "googleapiclient.discovery", discovery)
    monkeypatch.setitem(modules, "tenacity", tenacity)

    helper_name = "bot.helper.mirror_leech_utils.gdrive_utils.helper"
    modules.pop(helper_name, None)
    helper = import_module(helper_name)
    yield helper
    modules.pop(helper_name, None)


class _RevokedCredentials:
    valid = False
    refresh_token = "revoked-refresh-token"

    def refresh(self, _request):
        raise RefreshError("invalid_grant: Bad Request")


class _RefreshableCredentials:
    valid = False
    refresh_token = "working-refresh-token"

    def refresh(self, _request):
        self.valid = True


class _Response:
    def __init__(self, *, text="", data=None, status_code=200):
        self.text = text
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class _IndexSession:
    def __init__(
        self,
        pages,
        *,
        html="<title>Google Drive Index</title>",
        get_failures=0,
        post_failures=None,
    ):
        self.pages = pages
        self.html = html
        self.get_failures = get_failures
        self.post_failures = dict(post_failures or {})
        self.get_calls = 0
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url, **_kwargs):
        self.get_calls += 1
        if self.get_failures:
            self.get_failures -= 1
            raise ConnectionError("network is unreachable")
        return _Response(text=self.html)

    def post(self, url, json, **_kwargs):
        self.posts.append((url, json.copy()))
        key = (url, json["page_token"])
        if self.post_failures.get(key, 0):
            self.post_failures[key] -= 1
            raise ConnectionError("network is unreachable")
        return _Response(data=self.pages[key])


def test_invalid_grant_is_a_permanent_actionable_authentication_error(gdrive_modules):
    helper = gdrive_modules
    error = helper.GoogleDriveCredentialError(
        "('invalid_grant: Bad Request', {'error': 'invalid_grant'})"
    )

    assert helper.is_gdrive_auth_error(error)
    assert helper.should_retry_gdrive_error(error) is False
    assert "/tokengen" in helper.gdrive_auth_error_message("tokens/123.pickle")
    assert "bot owner" in helper.gdrive_auth_error_message("token.pickle")
    assert hasattr(helper.GoogleDriveHelper, "switch_service_account")
    assert hasattr(helper.GoogleDriveHelper, "get_id_from_url")


def test_revoked_oauth_token_fails_during_preflight(
    tmp_path,
    monkeypatch,
    gdrive_modules,
):
    helper = gdrive_modules
    token_path = tmp_path / "user-token.pickle"
    with token_path.open("wb") as token_file:
        dump(_RevokedCredentials(), token_file)
    monkeypatch.setattr(helper, "Request", lambda: object())

    with pytest.raises(
        helper.GoogleDriveCredentialError,
        match="expired or was revoked",
    ):
        helper.validate_gdrive_oauth_token(str(token_path))


def test_preflight_persists_successfully_refreshed_oauth_token(
    tmp_path,
    monkeypatch,
    gdrive_modules,
):
    helper = gdrive_modules
    token_path = tmp_path / "user-token.pickle"
    with token_path.open("wb") as token_file:
        dump(_RefreshableCredentials(), token_file)
    monkeypatch.setattr(helper, "Request", lambda: object())

    helper.validate_gdrive_oauth_token(str(token_path))

    with token_path.open("rb") as token_file:
        refreshed = load(token_file)
    assert refreshed.valid is True


def _page(files, *, next_token=None, page_index=0):
    return {
        "nextPageToken": next_token,
        "curPageIndex": page_index,
        "data": {"files": files},
    }


def test_google_drive_index_recurses_and_preserves_paginated_folder_structure():
    root = "https://index.example/0:/Collection/"
    season = f"{root}Season%201/"
    pages = {
        (root, ""): _page(
            [
                {
                    "name": "Season 1",
                    "mimeType": "application/vnd.google-apps.folder",
                    "link": None,
                },
                {
                    "name": "root poster.jpg",
                    "mimeType": "image/jpeg",
                    "size": "25",
                    "link": "/download?temporary=1",
                },
            ],
            next_token="page-two",
        ),
        (root, "page-two"): _page(
            [
                {
                    "name": "notes.txt",
                    "mimeType": "text/plain",
                    "size": "5",
                    "link": "/download?temporary=2",
                }
            ],
            page_index=1,
        ),
        (season, ""): _page(
            [
                {
                    "name": "Episode 01: Pilot.mkv",
                    "mimeType": "video/x-matroska",
                    "size": "100",
                    "link": "/download?expired-soon=1",
                }
            ]
        ),
    }
    session = _IndexSession(pages)

    with patch.object(dlg, "Session", return_value=session):
        result = dlg.google_drive_index(root)

    assert result["title"] == "Collection"
    assert result["total_size"] == 130
    assert result["contents"] == [
        {
            "path": "Season 1",
            "filename": "Episode 01_ Pilot.mkv",
            "url": f"{season}Episode%2001%3A%20Pilot.mkv",
        },
        {
            "path": "",
            "filename": "root poster.jpg",
            "url": f"{root}root%20poster.jpg",
        },
        {
            "path": "",
            "filename": "notes.txt",
            "url": f"{root}notes.txt",
        },
    ]
    assert session.posts[1][1]["page_token"] == ""
    assert session.posts[2][1]["page_token"] == "page-two"
    assert session.posts[2][1]["page_index"] == 1


def test_google_drive_index_non_index_page_keeps_generic_fallback_behavior():
    session = _IndexSession({}, html="<html><title>Ordinary site</title></html>")

    with patch.object(dlg, "Session", return_value=session):
        with pytest.raises(DirectDownloadLinkException, match="No Direct link function found"):
            dlg.google_drive_index("https://example.com/folder/")

    assert session.posts == []


def test_google_drive_index_reports_password_protection():
    root = "https://index.example/0:/Private/"
    session = _IndexSession(
        {
            (root, ""): {
                "error": {"code": "401", "message": "Unauthorized"},
            }
        }
    )

    with patch.object(dlg, "Session", return_value=session):
        with pytest.raises(DirectDownloadLinkException, match="password protected"):
            dlg.google_drive_index(root)


def test_dispatcher_checks_trailing_slash_urls_for_drive_index_folders():
    manifest = {"contents": [], "title": "Folder", "total_size": 0}
    link = "https://index.example/0:/Folder/"

    with (
        patch.object(dlg.Config, "DEBRID_LINK_API", ""),
        patch.object(dlg, "google_drive_index", return_value=manifest) as resolver,
    ):
        assert dlg.direct_link_generator(link) is manifest

    resolver.assert_called_once_with(link)


def test_google_drive_index_retries_transient_get_and_folder_api_failures():
    root = "https://index.example/0:/Collection/"
    pages = {
        (root, ""): _page(
            [
                {
                    "name": "episode.mkv",
                    "mimeType": "video/x-matroska",
                    "size": "10",
                    "link": "/download?temporary=1",
                }
            ]
        )
    }
    session = _IndexSession(
        pages,
        get_failures=2,
        post_failures={(root, ""): 2},
    )

    with (
        patch.object(dlg, "Session", return_value=session),
        patch.object(dlg, "sleep") as retry_sleep,
    ):
        result = dlg.google_drive_index(root)

    assert len(result["contents"]) == 1
    assert session.get_calls == 3
    assert len(session.posts) == 3
    assert retry_sleep.call_count == 4


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://index.example/0:/Collection/", True),
        ("https://index.example/12:/", True),
        ("https://example.com/folder/", False),
        ("https://index.example/0:/file.mkv", False),
    ],
)
def test_google_drive_index_link_detection(link, expected):
    assert dlg.is_google_drive_index_link(link) is expected
