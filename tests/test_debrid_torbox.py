"""Tests for Phase 1 port P1 — TorBox debrid resolver.

Covers:
  - API key prefix parsing for all 5 providers (rd:, ad:, pm:, dl:, tb:)
  - Backward compat: bare key assumed debrid-link
  - Empty config: returns (None, None)
  - _torbox() success path (mocked HTTP)
  - _torbox() API error path (success=false)
  - _torbox() network error path
  - debrid_unrestrict() dispatches to _torbox when provider is torbox
  - TORBOX_SUPPORTED_SITES list contains expected hosts
"""

from unittest.mock import MagicMock, patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import debrid_utils
from bot.helper.mirror_leech_utils.download_utils.debrid_utils import (
    TORBOX_SUPPORTED_SITES,
    _parse_api_key,
    _torbox,
    debrid_unrestrict,
)

# ---------- _parse_api_key tests ----------

def test_parse_empty_returns_none():
    """Rule 2: silent absence for unconfigured features."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", ""):
        provider, key = _parse_api_key()
        assert provider is None
        assert key is None


def test_parse_none_returns_none():
    """Rule 2: None config (unset) must also be silent."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", None):
        provider, key = _parse_api_key()
        assert provider is None
        assert key is None


def test_parse_real_debrid_prefix():
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:abc123"):
        provider, key = _parse_api_key()
        assert provider == "real-debrid"
        assert key == "abc123"


def test_parse_alldebrid_prefix():
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "ad:xyz789"):
        provider, key = _parse_api_key()
        assert provider == "alldebrid"
        assert key == "xyz789"


def test_parse_premiumize_prefix():
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "pm:pm_key"):
        provider, key = _parse_api_key()
        assert provider == "premiumize"
        assert key == "pm_key"


def test_parse_debrid_link_prefix():
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "dl:dl_key"):
        provider, key = _parse_api_key()
        assert provider == "debrid-link"
        assert key == "dl_key"


def test_parse_torbox_prefix():
    """Phase 1 port P1 — TorBox prefix 'tb:'."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "tb:tb_key_456"):
        provider, key = _parse_api_key()
        assert provider == "torbox"
        assert key == "tb_key_456"


def test_parse_bare_key_backward_compat():
    """Bare key (no prefix) assumed debrid-link — v1.5.0 backward compat."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "bare_key_no_prefix"):
        provider, key = _parse_api_key()
        assert provider == "debrid-link"
        assert key == "bare_key_no_prefix"


def test_parse_strips_whitespace():
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "  tb:  spaced_key  "):
        provider, key = _parse_api_key()
        assert provider == "torbox"
        assert key == "spaced_key"


# ---------- TORBOX_SUPPORTED_SITES tests ----------

def test_torbox_supported_sites_contains_expected_hosts():
    """Sanity check: the list contains the canonical premium hosts."""
    expected = [
        "rapidgator.net",
        "nitroflare.com",
        "keep2share.cc",
        "katfile.com",
        "turbobit.net",
        "depositfiles.com",
        "filefactory.com",
        "1fichier.com",
    ]
    for host in expected:
        assert host in TORBOX_SUPPORTED_SITES, f"Missing: {host}"


def test_torbox_supported_sites_is_list_of_strings():
    """Type contract: must be a list of strings."""
    assert isinstance(TORBOX_SUPPORTED_SITES, list)
    for entry in TORBOX_SUPPORTED_SITES:
        assert isinstance(entry, str)
        assert entry  # non-empty


def test_torbox_supported_sites_no_duplicates():
    """No duplicate entries — would cause dispatcher confusion."""
    assert len(TORBOX_SUPPORTED_SITES) == len(set(TORBOX_SUPPORTED_SITES))


def test_torbox_supported_sites_count_meets_threshold():
    """We expect at least 50 hosts to call this a meaningful list."""
    assert len(TORBOX_SUPPORTED_SITES) >= 50


# ---------- _torbox() function tests ----------

def _make_response(data):
    """Build a mock cloudscraper response object."""
    resp = MagicMock()
    resp.json.return_value = data
    return resp


def test_torbox_success_returns_download_url():
    """Happy path: TorBox returns success=true with a download_url."""
    mock_response = _make_response({
        "success": True,
        "data": {"download_url": "https://dl.torbox.app/dl/abc123/file.zip"},
    })
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = _torbox("https://rapidgator.net/file/abc", "fake_key")
        assert result == "https://dl.torbox.app/dl/abc123/file.zip"


def test_torbox_success_with_download_url_1_fallback():
    """Some TorBox responses use download_url_1 instead of download_url."""
    mock_response = _make_response({
        "success": True,
        "data": {"download_url_1": "https://dl.torbox.app/dl/xyz/file.rar"},
    })
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = _torbox("https://katfile.com/abc", "fake_key")
        assert result == "https://dl.torbox.app/dl/xyz/file.rar"


def test_torbox_api_error_raises_direct_download_link_exception():
    """TorBox returns success=false — must raise DirectDownloadLinkException."""
    mock_response = _make_response({
        "success": False,
        "detail": "Invalid API key",
    })
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        with pytest.raises(DirectDownloadLinkException, match="TorBox: Invalid API key"):
            _torbox("https://rapidgator.net/file/abc", "bad_key")


def test_torbox_api_error_with_msg_field():
    """Some TorBox errors use 'msg' instead of 'detail'."""
    mock_response = _make_response({
        "success": False,
        "msg": "Rate limited",
    })
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        with pytest.raises(DirectDownloadLinkException, match="TorBox: Rate limited"):
            _torbox("https://rapidgator.net/file/abc", "fake_key")


def test_torbox_missing_download_url_raises():
    """Success=true but no download_url — must raise."""
    mock_response = _make_response({
        "success": True,
        "data": {},
    })
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        with pytest.raises(DirectDownloadLinkException, match="no download URL"):
            _torbox("https://rapidgator.net/file/abc", "fake_key")


def test_torbox_network_error_wrapped():
    """Network/transport errors must be wrapped in DirectDownloadLinkException."""
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.side_effect = ConnectionError("DNS failed")
        with pytest.raises(DirectDownloadLinkException, match="TorBox: DNS failed"):
            _torbox("https://rapidgator.net/file/abc", "fake_key")


def test_torbox_json_parse_error_wrapped():
    """Malformed JSON response must be wrapped."""
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("not JSON")
    with patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        with pytest.raises(DirectDownloadLinkException, match="TorBox:"):
            _torbox("https://rapidgator.net/file/abc", "fake_key")


# ---------- debrid_unrestrict() dispatch tests ----------

def test_debrid_unrestrict_dispatches_to_torbox():
    """Verify the main dispatcher routes 'tb:' config to _torbox()."""
    mock_response = _make_response({
        "success": True,
        "data": {"download_url": "https://dl.torbox.app/dl/test/file.zip"},
    })
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "tb:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = debrid_unrestrict("https://rapidgator.net/file/abc")
        assert result == "https://dl.torbox.app/dl/test/file.zip"


def test_debrid_unrestrict_no_key_raises():
    """Empty config must raise a clear error (Rule 2 doesn't apply here —
    the function was explicitly called)."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", ""):
        with pytest.raises(DirectDownloadLinkException, match="No debrid API key"):
            debrid_unrestrict("https://rapidgator.net/file/abc")


def test_debrid_unrestrict_none_key_raises():
    """None config must also raise."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", None):
        with pytest.raises(DirectDownloadLinkException, match="No debrid API key"):
            debrid_unrestrict("https://rapidgator.net/file/abc")


def test_debrid_unrestrict_error_message_lists_all_prefixes():
    """Error message must mention tb: so operators know it's supported."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", ""):
        try:
            debrid_unrestrict("https://rapidgator.net/file/abc")
        except DirectDownloadLinkException as e:
            msg = str(e)
            assert "rd:" in msg
            assert "ad:" in msg
            assert "pm:" in msg
            assert "dl:" in msg
            assert "tb:" in msg  # Phase 1 port P1
        else:
            pytest.fail("Expected DirectDownloadLinkException")


# ---------- Backward compatibility tests ----------

def test_debrid_unrestrict_real_debrid_still_works():
    """Existing Real-Debrid config must continue to work after P1 port."""
    mock_response = _make_response({"download": "https://rd.example.com/file.zip"})
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:rd_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = debrid_unrestrict("https://rapidgator.net/file/abc")
        assert result == "https://rd.example.com/file.zip"


def test_debrid_unrestrict_alldebrid_still_works():
    """Existing AllDebrid config must continue to work after P1 port."""
    mock_response = _make_response({
        "status": "success",
        "data": {"link": "https://ad.example.com/file.zip"},
    })
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "ad:ad_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = debrid_unrestrict("https://rapidgator.net/file/abc")
        assert result == "https://ad.example.com/file.zip"


def test_debrid_unrestrict_premiumize_still_works():
    """Existing Premiumize config must continue to work after P1 port."""
    mock_response = _make_response({
        "status": "success",
        "transfers": [{"id": "tr_abc"}],
    })
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "pm:pm_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = debrid_unrestrict("https://rapidgator.net/file/abc")
        assert "premiumize.me/transfers" in result


def test_debrid_unrestrict_debrid_link_still_works():
    """Existing Debrid-Link config must continue to work after P1 port."""
    mock_response = _make_response({
        "success": True,
        "value": {"downloadUrl": "https://dl.example.com/file.zip"},
    })
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "dl:dl_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = debrid_unrestrict("https://rapidgator.net/file/abc")
        assert result == "https://dl.example.com/file.zip"


def test_debrid_unrestrict_bare_key_still_debrid_link():
    """v1.5.0 backward compat: bare key (no prefix) must still route to
    Debrid-Link, NOT to TorBox. This is the most critical regression test."""
    mock_response = _make_response({
        "success": True,
        "value": {"downloadUrl": "https://dl.example.com/file.zip"},
    })
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "bare_key_v150"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = debrid_unrestrict("https://rapidgator.net/file/abc")
        assert result == "https://dl.example.com/file.zip"
