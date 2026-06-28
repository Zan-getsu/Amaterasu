"""Tests for Phase 1 ports P7 & P8 — fembed and sbembed scrapers.

Both ports add new video-hosting scrapers to Amaterasu:

  P7 — fembed() supports 10 domains (FEMBED_DOMAINS):
       fembed.net, fembed.com, femax20.com, fcdn.stream, feurl.com,
       layarkacaxxi.icu, naniplay.nanime.in, naniplay.nanime.biz,
       naniplay.com, mm9842.com

  P8 — sbembed() supports 4 domains (SBEMBED_DOMAINS):
       sbembed.com, watchsb.com, streamsb.net, sbplay.org

Both implementations are dependency-free (no lk21) — they call the
public APIs directly and wrap all errors in DirectDownloadLinkException.

Coverage:
  - Domain lists contain expected hosts
  - fembed() success path (mocked API response)
  - fembed() API error (success=false)
  - fembed() network error wrapped
  - fembed() empty data array raises
  - fembed() missing video ID raises
  - sbembed() success path (mocked HTML with sources array)
  - sbembed() sources-not-found raises
  - sbembed() network error wrapped
  - sbembed() empty sources array raises
  - dispatcher routes fembed/sbembed URLs correctly
  - dispatcher does NOT route non-fembed/sbembed URLs to these functions
  - backward compat: existing scrapers still work
"""

from unittest.mock import MagicMock, patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg
from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import (
    FEMBED_DOMAINS,
    SBEMBED_DOMAINS,
    fembed,
    sbembed,
)

# ---------- Domain list tests ----------

def test_fembed_domains_contains_expected_hosts():
    """All 10 fembed-family domains must be present."""
    expected = [
        "fembed.net", "fembed.com", "femax20.com", "fcdn.stream",
        "feurl.com", "layarkacaxxi.icu", "naniplay.nanime.in",
        "naniplay.nanime.biz", "naniplay.com", "mm9842.com",
    ]
    for d in expected:
        assert d in FEMBED_DOMAINS, f"Missing fembed domain: {d}"


def test_fembed_domains_count():
    assert len(FEMBED_DOMAINS) == 10


def test_sbembed_domains_contains_expected_hosts():
    """All 4 sbembed-family domains must be present."""
    expected = ["sbembed.com", "watchsb.com", "streamsb.net", "sbplay.org"]
    for d in expected:
        assert d in SBEMBED_DOMAINS, f"Missing sbembed domain: {d}"


def test_sbembed_domains_count():
    assert len(SBEMBED_DOMAINS) == 4


def test_fembed_and_sbembed_lists_are_disjoint():
    """No domain should appear in both lists (would cause dispatcher ambiguity)."""
    overlap = set(FEMBED_DOMAINS) & set(SBEMBED_DOMAINS)
    assert not overlap, f"Overlap found: {overlap}"


# ---------- fembed() function tests ----------

def test_fembed_success_returns_last_stream_url():
    """Happy path: API returns success=true with multiple quality streams.
    fembed() must return the LAST (highest-quality) stream URL."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": [
            {"file": "https://cdn.fembed.com/360p.mp4", "label": "360p"},
            {"file": "https://cdn.fembed.com/720p.mp4", "label": "720p"},
            {"file": "https://cdn.fembed.com/1080p.mp4", "label": "1080p"},
        ],
    }
    with patch.object(dlg, "post", return_value=mock_response):
        result = fembed("https://fembed.com/v/abc123")
        assert result == "https://cdn.fembed.com/1080p.mp4"


def test_fembed_success_with_single_stream():
    """API returns success=true with one stream — return that stream."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": [{"file": "https://cdn.fembed.com/only.mp4", "label": "720p"}],
    }
    with patch.object(dlg, "post", return_value=mock_response):
        result = fembed("https://fembed.net/v/xyz")
        assert result == "https://cdn.fembed.com/only.mp4"


def test_fembed_api_returns_success_false():
    """API returns success=false — must raise with the API message."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "message": "Video not found",
    }
    with patch.object(dlg, "post", return_value=mock_response):
        with pytest.raises(DirectDownloadLinkException, match="Video not found"):
            fembed("https://fembed.com/v/nonexistent")


def test_fembed_api_returns_no_data():
    """API returns success=true but empty data array — must raise."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": [],
    }
    with patch.object(dlg, "post", return_value=mock_response):
        with pytest.raises(DirectDownloadLinkException, match="no playable streams"):
            fembed("https://fembed.com/v/empty")


def test_fembed_network_error_wrapped():
    """Network errors must be wrapped in DirectDownloadLinkException."""
    with patch.object(dlg, "post", side_effect=ConnectionError("DNS failed")):
        with pytest.raises(DirectDownloadLinkException, match="ConnectionError"):
            fembed("https://fembed.com/v/abc")


def test_fembed_json_parse_error_wrapped():
    """Malformed JSON response must be wrapped."""
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("not JSON")
    with patch.object(dlg, "post", return_value=mock_response):
        with pytest.raises(DirectDownloadLinkException, match="ValueError"):
            fembed("https://fembed.com/v/abc")


def test_fembed_missing_video_id_raises():
    """URL with no path (just domain) must raise clear error."""
    with pytest.raises(DirectDownloadLinkException, match="video ID"):
        fembed("https://fembed.com/")


def test_fembed_uses_correct_api_url():
    """Verify fembed() calls the right API endpoint: /api/source/{video_id}"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": [{"file": "https://cdn.example.com/file.mp4"}],
    }
    with patch.object(dlg, "post", return_value=mock_response) as mock_post:
        fembed("https://fembed.com/v/abc123")
        call_args = mock_post.call_args
        api_url = call_args.args[0] if call_args.args else call_args[0][0]
        assert "fembed.com" in api_url
        assert "/api/source/abc123" in api_url


# ---------- sbembed() function tests ----------

def test_sbembed_success_returns_last_source_url():
    """Happy path: HTML contains 'sources = [...]' — return last URL."""
    mock_response = MagicMock()
    mock_response.text = '''
        <html>
        <script>
            var player = new Clappr.Player({
                sources: [{"file":"https://cdn.sbembed.com/360p.mp4","label":"360p"},
                          {"file":"https://cdn.sbembed.com/720p.mp4","label":"720p"}]
            });
        </script>
        </html>
    '''
    with patch.object(dlg, "get", return_value=mock_response):
        result = sbembed("https://sbembed.com/e/abc123")
        assert result == "https://cdn.sbembed.com/720p.mp4"


def test_sbembed_success_with_single_source():
    """HTML with one source — return that source."""
    mock_response = MagicMock()
    mock_response.text = 'sources: [{"file":"https://cdn.sbembed.com/only.mp4"}]'
    with patch.object(dlg, "get", return_value=mock_response):
        result = sbembed("https://streamsb.net/e/abc")
        assert result == "https://cdn.sbembed.com/only.mp4"


def test_sbembed_sources_not_found_raises():
    """HTML has no 'sources' array — must raise clear error."""
    mock_response = MagicMock()
    mock_response.text = "<html><body>No video here</body></html>"
    with patch.object(dlg, "get", return_value=mock_response):
        with pytest.raises(DirectDownloadLinkException, match="sources array not found"):
            sbembed("https://sbembed.com/e/abc")


def test_sbembed_empty_sources_array_raises():
    """HTML has 'sources = []' — must raise clear error."""
    mock_response = MagicMock()
    mock_response.text = 'sources: []'
    with patch.object(dlg, "get", return_value=mock_response):
        with pytest.raises(DirectDownloadLinkException, match="empty"):
            sbembed("https://sbembed.com/e/abc")


def test_sbembed_network_error_wrapped():
    """Network errors must be wrapped."""
    with patch.object(dlg, "get", side_effect=ConnectionError("timeout")):
        with pytest.raises(DirectDownloadLinkException, match="ConnectionError"):
            sbembed("https://sbembed.com/e/abc")


def test_sbembed_malformed_json_raises():
    """HTML has 'sources = [{broken}]' — closing bracket present but
    JSON inside is unparseable. Must raise parse error."""
    mock_response = MagicMock()
    mock_response.text = 'sources: [{broken json}]'
    with patch.object(dlg, "get", return_value=mock_response):
        with pytest.raises(DirectDownloadLinkException, match="Could not parse"):
            sbembed("https://sbembed.com/e/abc")


# ---------- Dispatcher integration tests ----------

def test_dispatcher_routes_fembed_url_to_fembed_function():
    """fembed.com URL must route to fembed() — not to fallback error."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": [{"file": "https://cdn.example.com/file.mp4"}],
    }
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "post", return_value=mock_response):
        result = dlg.direct_link_generator("https://fembed.com/v/abc123")
        assert result == "https://cdn.example.com/file.mp4"


def test_dispatcher_routes_sbembed_url_to_sbembed_function():
    """sbembed.com URL must route to sbembed()."""
    mock_response = MagicMock()
    mock_response.text = 'sources: [{"file":"https://cdn.example.com/file.mp4"}]'
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "get", return_value=mock_response):
        result = dlg.direct_link_generator("https://sbembed.com/e/abc123")
        assert result == "https://cdn.example.com/file.mp4"


def test_dispatcher_routes_all_fembed_domains():
    """All 10 fembed-family domains must route to fembed()."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "data": [{"file": "https://cdn.example.com/file.mp4"}],
    }
    for domain in FEMBED_DOMAINS:
        with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
             patch.object(dlg, "post", return_value=mock_response):
            try:
                result = dlg.direct_link_generator(f"https://{domain}/v/test123")
                assert result == "https://cdn.example.com/file.mp4", \
                    f"Domain {domain} did not route to fembed()"
            except DirectDownloadLinkException as e:
                if "No Direct link function found" in str(e):
                    pytest.fail(f"Domain {domain} not routed: {e}")


def test_dispatcher_routes_all_sbembed_domains():
    """All 4 sbembed-family domains must route to sbembed()."""
    mock_response = MagicMock()
    mock_response.text = 'sources: [{"file":"https://cdn.example.com/file.mp4"}]'
    for domain in SBEMBED_DOMAINS:
        with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
             patch.object(dlg, "get", return_value=mock_response):
            try:
                result = dlg.direct_link_generator(f"https://{domain}/e/test123")
                assert result == "https://cdn.example.com/file.mp4", \
                    f"Domain {domain} did not route to sbembed()"
            except DirectDownloadLinkException as e:
                if "No Direct link function found" in str(e):
                    pytest.fail(f"Domain {domain} not routed: {e}")


def test_dispatcher_does_not_route_rapidgator_to_fembed():
    """Sanity: rapidgator.net must NOT route to fembed()."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "fembed") as mock_fembed:
        with pytest.raises(DirectDownloadLinkException, match="No Direct link function found"):
            dlg.direct_link_generator("https://rapidgator.net/file/abc")
        mock_fembed.assert_not_called()


# ---------- Backward compatibility ----------

def test_existing_mediafire_scraper_still_works():
    """mediafire.com must still route to mediafire() — not fembed/sbembed."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "mediafire", return_value="https://mediafire.example.com/file") as mock_mf:
        result = dlg.direct_link_generator("https://www.mediafire.com/file/abc/file.zip")
        assert result == "https://mediafire.example.com/file"
        mock_mf.assert_called_once()


def test_existing_pixeldrain_scraper_still_works():
    """pixeldrain.com must still route to pixeldrain() — not fembed/sbembed."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "pixeldrain", return_value="https://pixeldrain.example.com/file") as mock_pd:
        result = dlg.direct_link_generator("https://pixeldrain.com/u/abc123")
        assert result == "https://pixeldrain.example.com/file"
        mock_pd.assert_called_once()
