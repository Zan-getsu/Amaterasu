from unittest.mock import patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg


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
