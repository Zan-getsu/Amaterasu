"""Tests for Phase 1 port P2 — Real-Debrid cached-magnet auto-resolve.

When the user sends a magnet link AND Real-Debrid is configured (rd:
prefix in DEBRID_LINK_API), this feature queries RD's
/torrents/instantAvailability/{hash} endpoint. If the torrent is cached,
it returns a multi-file direct-download dict that bypasses qBittorrent
entirely — no swarm participation, instant HTTP fetch.

Critical safety property: this function NEVER raises. On any non-success
path (not cached, network error, RD not configured, invalid magnet),
it returns None and the caller falls through to normal torrent handling.

Coverage:
  - extract_info_hash() with various magnet formats (v1 hex, v1 base32, v2)
  - real_debrid_cached_magnet() returns None when RD not configured
  - real_debrid_cached_magnet() returns None when other provider configured
  - real_debrid_cached_magnet() returns None when magnet has no hash
  - real_debrid_cached_magnet() returns None when RD API says not cached
  - real_debrid_cached_magnet() returns None on network error
  - real_debrid_cached_magnet() returns None on JSON parse error
  - real_debrid_cached_magnet() returns dict when RD has cached torrent
  - real_debrid_cached_magnet() picks the largest variant
  - real_debrid_cached_magnet() never raises (safety property)
"""

from unittest.mock import MagicMock, patch

import pytest

from bot.helper.ext_utils.links_utils import extract_info_hash
from bot.helper.mirror_leech_utils.download_utils import debrid_utils
from bot.helper.mirror_leech_utils.download_utils.debrid_utils import (
    real_debrid_cached_magnet,
)

# ---------- extract_info_hash() tests ----------

def test_extract_info_hash_v1_hex_uppercase():
    """v1 magnet with uppercase hex hash — return lowercase."""
    magnet = "magnet:?xt=urn:btih:ABCDEF0123456789ABCDEF0123456789ABCDEF01&dn=test"
    result = extract_info_hash(magnet)
    assert result == "abcdef0123456789abcdef0123456789abcdef01"


def test_extract_info_hash_v1_hex_lowercase():
    """v1 magnet with lowercase hex hash — return as-is."""
    magnet = "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01&dn=test"
    result = extract_info_hash(magnet)
    assert result == "abcdef0123456789abcdef0123456789abcdef01"


def test_extract_info_hash_v1_hex_mixed_case():
    """v1 magnet with mixed-case hex hash — return lowercase."""
    magnet = "magnet:?xt=urn:btih:AbCdEf0123456789AbCdEf0123456789AbCdEf01&dn=test"
    result = extract_info_hash(magnet)
    assert result == "abcdef0123456789abcdef0123456789abcdef01"


def test_extract_info_hash_with_multiple_xt_params():
    """Magnet with multiple xt= params — extract the btih one."""
    magnet = (
        "magnet:?xt=urn:btmh:1220abcd&"
        "xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01&dn=test"
    )
    result = extract_info_hash(magnet)
    assert result == "abcdef0123456789abcdef0123456789abcdef01"


def test_extract_info_hash_no_btih_returns_none():
    """Magnet without btih hash — return None."""
    magnet = "magnet:?xt=urn:btmh:1220abcd&dn=test"
    result = extract_info_hash(magnet)
    assert result is None


def test_extract_info_hash_empty_string_returns_none():
    assert extract_info_hash("") is None


def test_extract_info_hash_none_returns_none():
    assert extract_info_hash(None) is None


def test_extract_info_hash_non_string_returns_none():
    """Non-string input must not crash — return None."""
    assert extract_info_hash(123) is None
    assert extract_info_hash([]) is None
    assert extract_info_hash({}) is None


def test_extract_info_hash_v1_base32():
    """v1 magnet with 32-char base32 hash — decode to hex."""
    # Base32 "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" decodes to a specific hex
    import base64
    test_bytes = bytes.fromhex("abcdef0123456789abcdef0123456789abcdef01")
    b32 = base64.b32encode(test_bytes).decode("ascii")
    magnet = f"magnet:?xt=urn:btih:{b32}&dn=test"
    result = extract_info_hash(magnet)
    assert result == "abcdef0123456789abcdef0123456789abcdef01"


# ---------- real_debrid_cached_magnet() — feature-flag guard tests ----------

def test_rd_cached_magnet_returns_none_when_no_api_key():
    """Rule 1: empty DEBRID_LINK_API → return None immediately."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", ""):
        result = real_debrid_cached_magnet(
            "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01"
        )
        assert result is None


def test_rd_cached_magnet_returns_none_when_other_provider():
    """Rule 1: provider is TorBox (not Real-Debrid) → return None."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "tb:some_key"):
        result = real_debrid_cached_magnet(
            "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01"
        )
        assert result is None


def test_rd_cached_magnet_returns_none_when_alldebrid_configured():
    """Rule 1: provider is AllDebrid (not Real-Debrid) → return None."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "ad:some_key"):
        result = real_debrid_cached_magnet(
            "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01"
        )
        assert result is None


def test_rd_cached_magnet_returns_none_when_premiumize_configured():
    """Rule 1: provider is Premiumize (not Real-Debrid) → return None."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "pm:some_key"):
        result = real_debrid_cached_magnet(
            "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01"
        )
        assert result is None


def test_rd_cached_magnet_returns_none_when_debrid_link_configured():
    """Rule 1: provider is Debrid-Link (not Real-Debrid) → return None."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "dl:some_key"):
        result = real_debrid_cached_magnet(
            "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01"
        )
        assert result is None


# ---------- real_debrid_cached_magnet() — invalid input tests ----------

def test_rd_cached_magnet_returns_none_for_invalid_magnet():
    """Magnet without btih hash → return None (no API call)."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"):
        result = real_debrid_cached_magnet("magnet:?xt=urn:btmh:1220abcd&dn=test")
        assert result is None


def test_rd_cached_magnet_returns_none_for_empty_magnet():
    """Empty magnet string → return None."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"):
        result = real_debrid_cached_magnet("")
        assert result is None


def test_rd_cached_magnet_returns_none_for_non_magnet():
    """Non-magnet string → return None (no btih hash found)."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"):
        result = real_debrid_cached_magnet("https://example.com/file.zip")
        assert result is None


# ---------- real_debrid_cached_magnet() — API response tests ----------

INFO_HASH = "abcdef0123456789abcdef0123456789abcdef01"


def test_rd_cached_magnet_returns_dict_when_cached():
    """Happy path: RD has the torrent cached → return multi-file dict."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        INFO_HASH: {
            "rd": [
                {
                    "1": {
                        "filename": "movie.mp4",
                        "filesize": 1000000000,
                        "download": "https://real-debrid.com/d/abc123/movie.mp4",
                    }
                }
            ]
        }
    }
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is not None
        assert result["title"] == INFO_HASH
        assert result["total_size"] == 1000000000
        assert len(result["contents"]) == 1
        assert result["contents"][0]["filename"] == "movie.mp4"
        assert result["contents"][0]["url"] == "https://real-debrid.com/d/abc123/movie.mp4"


def test_rd_cached_magnet_picks_largest_variant():
    """When multiple variants are returned, pick the one with the largest
    total size (usually the complete torrent)."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        INFO_HASH: {
            "rd": [
                # Small variant (1 file, 500MB)
                {"1": {"filename": "preview.mp4", "filesize": 500_000_000,
                       "download": "https://rd.com/small.mp4"}},
                # Large variant (2 files, 2GB total)
                {"1": {"filename": "movie.mp4", "filesize": 1_500_000_000,
                       "download": "https://rd.com/movie.mp4"},
                 "2": {"filename": "subtitles.srt", "filesize": 500_000_000,
                       "download": "https://rd.com/subs.srt"}},
            ]
        }
    }
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is not None
        assert result["total_size"] == 2_000_000_000
        assert len(result["contents"]) == 2


def test_rd_cached_magnet_returns_none_when_not_cached():
    """RD returns empty dict (hash not in response) → return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}  # empty = not cached
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


def test_rd_cached_magnet_returns_none_when_no_rd_variants():
    """RD returns the hash but with empty 'rd' array → return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        INFO_HASH: {"rd": []}  # cached metadata but no downloadable variants
    }
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


def test_rd_cached_magnet_returns_none_when_variant_has_no_downloads():
    """RD returns a variant but files have no 'download' URL → return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        INFO_HASH: {
            "rd": [
                {"1": {"filename": "movie.mp4", "filesize": 1000}}  # no download
            ]
        }
    }
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


# ---------- real_debrid_cached_magnet() — error handling (safety property) ----------

def test_rd_cached_magnet_returns_none_on_network_error():
    """Network error → return None (NOT raise)."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.side_effect = ConnectionError("DNS failed")
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None  # NEVER raises


def test_rd_cached_magnet_returns_none_on_json_parse_error():
    """Malformed JSON response → return None (NOT raise)."""
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("not JSON")
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None  # NEVER raises


def test_rd_cached_magnet_returns_none_on_timeout():
    """Timeout error → return None (NOT raise)."""
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.side_effect = TimeoutError("RD API timed out")
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None  # NEVER raises


def test_rd_cached_magnet_never_raises_safety_property():
    """Critical safety property: this function NEVER raises, regardless of
    input or environment. It always returns either a dict or None.

    This is what makes it safe to call unconditionally from the
    torrent-handling code path — it can never break torrent downloads.
    """
    test_cases = [
        "",  # empty
        None,  # None
        "not a magnet",  # non-magnet
        "magnet:?xt=urn:btmh:1220abcd",  # magnet without btih
        f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test",  # valid magnet
        123,  # wrong type
        [],  # wrong type
    ]
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        # Make the scraper raise various errors
        mock_scraper.return_value.request.side_effect = Exception("any error")
        for case in test_cases:
            try:
                result = real_debrid_cached_magnet(case)
                # Must return None or a dict — never raise
                assert result is None or isinstance(result, dict)
            except Exception as e:
                pytest.fail(
                    f"SAFETY VIOLATION: real_debrid_cached_magnet({case!r}) "
                    f"raised {type(e).__name__}: {e}"
                )


# ---------- API URL construction test ----------

def test_rd_cached_magnet_calls_correct_api_endpoint():
    """Verify the function calls RD's /torrents/instantAvailability/{hash}."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}  # not cached
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        real_debrid_cached_magnet(f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test")
        call_args = mock_scraper.return_value.request.call_args
        method = call_args.args[0] if call_args.args else call_args[0][0]
        url = call_args.args[1] if len(call_args.args) > 1 else call_args[0][1]
        assert method == "GET"
        assert "api.real-debrid.com/rest/1.0/torrents/instantAvailability" in url
        assert INFO_HASH in url


def test_rd_cached_magnet_passes_bearer_token():
    """Verify the API key is passed as a Bearer token in Authorization header."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:my_secret_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        real_debrid_cached_magnet(f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test")
        call_kwargs = mock_scraper.return_value.request.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer my_secret_key"


# ---------- Malformed response tests (regression for "never raises" bug) ----------
# These tests verify that real_debrid_cached_magnet() handles malformed
# API responses gracefully by returning None instead of raising.
# This is the CRITICAL safety property: the function must NEVER raise,
# regardless of how malformed the RD response is.

def test_rd_cached_magnet_handles_hash_mapped_to_non_dict():
    """Regression: RD returns {hash: 'NOT_A_DICT'} — must return None,
    NOT raise AttributeError. This was a real bug found during deep
    recheck — the original code called .get('rd', []) on a string."""
    mock_response = MagicMock()
    mock_response.json.return_value = {INFO_HASH: "NOT_A_DICT"}
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None  # NEVER raises


def test_rd_cached_magnet_handles_hash_mapped_to_list():
    """RD returns {hash: [1, 2, 3]} (list, not dict) — must return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = {INFO_HASH: [1, 2, 3]}
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


def test_rd_cached_magnet_handles_hash_mapped_to_none():
    """RD returns {hash: None} — must return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = {INFO_HASH: None}
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


def test_rd_cached_magnet_handles_rd_field_not_list():
    """RD returns {hash: {rd: 'NOT_A_LIST'}} — must return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = {INFO_HASH: {"rd": "NOT_A_LIST"}}
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


def test_rd_cached_magnet_handles_variant_not_dict():
    """RD returns a variant that is a string, not a dict — must return None
    OR skip the bad variant and try the next one. Either way, must not raise."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        INFO_HASH: {
            "rd": [
                "NOT_A_DICT",  # malformed variant
                {"1": {"filename": "ok.mp4", "filesize": 100,
                       "download": "https://rd.com/ok.mp4"}},
            ]
        }
    }
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        try:
            result = real_debrid_cached_magnet(
                f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
            )
            # Either None (if all variants rejected) or a valid dict (if
            # the bad variant was skipped). Both are acceptable.
            assert result is None or isinstance(result, dict)
        except Exception as e:
            pytest.fail(
                f"SAFETY VIOLATION: raised {type(e).__name__}: {e}"
            )


def test_rd_cached_magnet_handles_file_entry_not_dict():
    """RD returns a variant where a file entry is a string — must skip
    that entry, not raise."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        INFO_HASH: {
            "rd": [
                {
                    "1": "NOT_A_DICT",  # malformed file entry
                    "2": {"filename": "ok.mp4", "filesize": 100,
                          "download": "https://rd.com/ok.mp4"},
                }
            ]
        }
    }
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        # Should skip the bad entry and return the good one
        assert result is not None
        assert len(result["contents"]) == 1
        assert result["contents"][0]["filename"] == "ok.mp4"


def test_rd_cached_magnet_handles_completely_garbled_response():
    """RD returns a completely garbled response (list instead of dict) —
    must return None, not raise."""
    mock_response = MagicMock()
    mock_response.json.return_value = ["garbled", "response", 123]
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None  # 'in' check on list returns False, so None


def test_rd_cached_magnet_handles_response_as_string():
    """RD returns a plain string instead of JSON dict — must return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = "just a string"
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None


def test_rd_cached_magnet_handles_response_as_int():
    """RD returns an int — must return None."""
    mock_response = MagicMock()
    mock_response.json.return_value = 42
    with patch.object(debrid_utils.Config, "DEBRID_LINK_API", "rd:test_key"), \
         patch.object(debrid_utils, "create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = real_debrid_cached_magnet(
            f"magnet:?xt=urn:btih:{INFO_HASH}&dn=test"
        )
        assert result is None
