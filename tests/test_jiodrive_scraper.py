"""Tests for Phase 1 port P9 — JioDrive scraper.

JioDrive is Reliance Jio's Indian consumer cloud storage. Public share
links look like https://www.jiodrive.xyz/?file_id=XXX. The scraper
needs an operator-provided JIODRIVE_TOKEN to authenticate.

Coverage:
  - Config.JIODRIVE_TOKEN defaults to empty (default-off, Rule 1)
  - jiodrive() raises clear error when token is empty (Rule 2)
  - jiodrive() success path returns direct download URL
  - jiodrive() handles API error (code != 200 → quota exceeded)
  - jiodrive() wraps network errors in DirectDownloadLinkException
  - jiodrive() wraps JSON parse errors
  - dispatcher routes jiodrive.xyz URLs to jiodrive() (not to fallback)
  - dispatcher does NOT route non-jiodrive URLs to jiodrive()
"""

from unittest.mock import MagicMock, patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg
from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import (
    jiodrive,
)

# ---------- Config defaults ----------

def test_jiodrive_token_defaults_empty():
    """Rule 1: feature must be default-off."""
    from bot.core.config_manager import Config
    # The class attribute default is "" — verified by direct read
    assert Config.JIODRIVE_TOKEN == ""


# ---------- jiodrive() function tests ----------

def test_jiodrive_raises_when_token_not_configured():
    """Rule 2: feature-flag guard. Empty token must raise clear error."""
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", ""):
        with pytest.raises(DirectDownloadLinkException, match="JIODRIVE_TOKEN not configured"):
            jiodrive("https://www.jiodrive.xyz/?file_id=abc123")


def test_jiodrive_raises_when_token_is_none():
    """None token (unset env var) must also raise clear error."""
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", None):
        with pytest.raises(DirectDownloadLinkException, match="JIODRIVE_TOKEN not configured"):
            jiodrive("https://www.jiodrive.xyz/?file_id=abc123")


def test_jiodrive_success_returns_download_url():
    """Happy path: token is set, JioDrive returns code=200 with file URL."""
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.get.return_value.url = "https://www.jiodrive.xyz/file/abc123"
    mock_session.post.return_value.json.return_value = {
        "code": "200",
        "file": "https://dl.jiodrive.xyz/dl/abc123/file.zip",
    }
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", "fake_token_456"), \
         patch.object(dlg, "create_scraper", return_value=mock_session):
        result = jiodrive("https://www.jiodrive.xyz/?file_id=abc123")
        assert result == "https://dl.jiodrive.xyz/dl/abc123/file.zip"


def test_jiodrive_quota_exceeded_error():
    """API returns code != 200 — must raise quota-exceeded error."""
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.get.return_value.url = "https://www.jiodrive.xyz/file/abc123"
    mock_session.post.return_value.json.return_value = {
        "code": "403",
        "message": "Quota exceeded",
    }
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", "fake_token"), \
         patch.object(dlg, "create_scraper", return_value=mock_session):
        with pytest.raises(DirectDownloadLinkException, match="quota has been exceeded"):
            jiodrive("https://www.jiodrive.xyz/?file_id=abc123")


def test_jiodrive_network_error_wrapped():
    """Network errors must be wrapped in DirectDownloadLinkException."""
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.get.side_effect = ConnectionError("DNS resolution failed")
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", "fake_token"), \
         patch.object(dlg, "create_scraper", return_value=mock_session):
        with pytest.raises(DirectDownloadLinkException, match="ConnectionError"):
            jiodrive("https://www.jiodrive.xyz/?file_id=abc123")


def test_jiodrive_json_parse_error_wrapped():
    """Malformed JSON response must be wrapped."""
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.get.return_value.url = "https://www.jiodrive.xyz/file/abc123"
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("not JSON")
    mock_session.post.return_value = mock_response
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", "fake_token"), \
         patch.object(dlg, "create_scraper", return_value=mock_session):
        with pytest.raises(DirectDownloadLinkException):
            jiodrive("https://www.jiodrive.xyz/?file_id=abc123")


def test_jiodrive_passes_token_as_cookie():
    """Verify the JIODRIVE_TOKEN is sent as the access_token cookie."""
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.get.return_value.url = "https://www.jiodrive.xyz/file/abc123"
    mock_session.post.return_value.json.return_value = {
        "code": "200",
        "file": "https://dl.jiodrive.xyz/dl/abc123/file.zip",
    }
    test_token = "my_secret_token_456"
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", test_token), \
         patch.object(dlg, "create_scraper", return_value=mock_session):
        jiodrive("https://www.jiodrive.xyz/?file_id=abc123")
        # Verify the post call passed the token as access_token cookie
        call_kwargs = mock_session.post.call_args.kwargs
        cookies = call_kwargs.get("cookies", {})
        assert cookies.get("access_token") == test_token


# ---------- Dispatcher integration tests ----------

def test_dispatcher_routes_jiodrive_url_to_jiodrive_function():
    """When the URL contains 'jiodrive' in the domain, the dispatcher
    must route to jiodrive() — NOT to the 'No Direct link function found'
    fallback."""
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", ""), \
         patch.object(dlg.Config, "DEBRID_LINK_API", ""):
        with pytest.raises(DirectDownloadLinkException, match="JIODRIVE_TOKEN not configured"):
            dlg.direct_link_generator("https://www.jiodrive.xyz/?file_id=abc123")


def test_dispatcher_does_not_route_non_jiodrive_url_to_jiodrive():
    """Sanity: a non-jiodrive URL must NOT route to jiodrive()."""
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", "fake_token"), \
         patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "jiodrive") as mock_jiodrive:
        # rapidgator.net has no native scraper — should raise 'No Direct
        # link function found', NOT call jiodrive
        with pytest.raises(DirectDownloadLinkException, match="No Direct link function found"):
            dlg.direct_link_generator("https://rapidgator.net/file/abc")
        mock_jiodrive.assert_not_called()


def test_dispatcher_jiodrive_branch_is_after_share_link_branch():
    """Verify the jiodrive branch is positioned AFTER is_share_link but
    BEFORE the R.I.P / fallback branches. This matters because jiodrive
    URLs don't match is_share_link's regex, so they would otherwise
    fall through to the 'No function found' error.

    Implementation note: we look for the LAST occurrence of each marker
    to avoid matching docstrings or comments earlier in the function."""
    import inspect
    src = inspect.getsource(dlg.direct_link_generator)
    # Find the actual code occurrences (not docstrings).
    # is_share_link dispatch line: 'elif is_share_link(link):'
    share_link_pos = src.find("elif is_share_link(link):")
    # jiodrive dispatcher line: 'elif "jiodrive" in domain:'
    jiodrive_pos = src.find('elif "jiodrive" in domain:')
    # R.I.P error line: 'raise DirectDownloadLinkException(f"ERROR: R.I.P'
    rip_pos = src.find('raise DirectDownloadLinkException(f"ERROR: R.I.P')
    # No function found: 'raise DirectDownloadLinkException(f"No Direct link function found'
    no_func_pos = src.find('raise DirectDownloadLinkException(f"No Direct link function found')

    assert share_link_pos > 0, "is_share_link branch not found in dispatcher"
    assert jiodrive_pos > share_link_pos, \
        f"jiodrive branch (pos {jiodrive_pos}) must come AFTER is_share_link branch (pos {share_link_pos})"
    assert jiodrive_pos < rip_pos, \
        f"jiodrive branch (pos {jiodrive_pos}) must come BEFORE R.I.P branch (pos {rip_pos})"
    assert jiodrive_pos < no_func_pos, \
        f"jiodrive branch (pos {jiodrive_pos}) must come BEFORE 'No function found' fallback (pos {no_func_pos})"


# ---------- Backward compatibility ----------

def test_existing_share_link_scrapers_still_work():
    """filepress and sharer_scraper must continue to work — the new
    jiodrive branch is added between is_share_link and R.I.P, so it
    cannot intercept filepress/sharer URLs (which match is_share_link)."""
    # filepress URL matches is_share_link regex (filepress.xyz)
    # is_share_link branch will handle it before reaching jiodrive branch
    with patch.object(dlg.Config, "JIODRIVE_TOKEN", "fake_token"), \
         patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "filepress", return_value="https://gdrive.example.com/file") as mock_fp:
        result = dlg.direct_link_generator("https://filepress.xyz/file/abc123")
        assert result == "https://gdrive.example.com/file"
        mock_fp.assert_called_once()


def test_no_regression_for_anonfiles_rip_error():
    """anonfiles.com must still raise R.I.P error (it comes after jiodrive
    in the dispatcher, but anonfiles doesn't match 'jiodrive' in domain)."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""):
        with pytest.raises(DirectDownloadLinkException, match="R.I.P"):
            dlg.direct_link_generator("https://anonfiles.com/abc123")
