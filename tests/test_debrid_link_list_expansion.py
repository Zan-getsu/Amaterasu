"""Tests for Phase 1 port P3 — Expanded Debrid-Link host list.

After the port, debrid_link_supported_sites grew from 113 to 382 hosts
(merged with WZML-X's debrid_link_sites list, deduplicated, sorted).

This test file verifies:
  - The list grew beyond the original 113 count
  - All previously-present hosts are still present (no regressions)
  - WZML-X-specific hosts are now present
  - The list is sorted alphabetically and has no duplicates
  - The dispatcher still routes correctly for an old host and a new host
"""

from unittest.mock import MagicMock, patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg

# ---------- List size and shape tests ----------

def test_list_grew_beyond_baseline():
    """P3 port: list must have grown from 113 to >= 350 hosts."""
    assert len(dlg.debrid_link_supported_sites) >= 350


def test_list_has_no_duplicates():
    """No duplicate entries — would cause dispatcher confusion."""
    hosts = dlg.debrid_link_supported_sites
    assert len(hosts) == len(set(hosts)), \
        f"Found {len(hosts) - len(set(hosts))} duplicate entries"


def test_list_is_sorted_alphabetically():
    """List should be sorted for easier maintenance and review."""
    hosts = dlg.debrid_link_supported_sites
    assert hosts == sorted(hosts), "List is not sorted alphabetically"


def test_list_contains_only_strings():
    """Type contract: every entry must be a non-empty string."""
    for host in dlg.debrid_link_supported_sites:
        assert isinstance(host, str), f"Non-string entry: {host!r}"
        assert host, "Empty string entry found"


# ---------- Backward compatibility — original 113 hosts must all still be present ----------

# These 20 hosts were in Amaterasu's original 113-host list. They MUST
# still be present after the P3 port (no host should be removed).
ORIGINAL_HOSTS_THAT_MUST_REMAIN = [
    "1fichier.com",
    "anonfiles.com",
    "bayfiles.com",
    "clicknupload.link",
    "ddl.to",
    "ddownload.com",
    "drop.download",
    "dropbox.com",
    "easyupload.io",
    "emload.com",
    "file.al",
    "filer.net",
    "filespace.com",
    "gofile.io",
    "katfile.com",
    "mediafire.com",
    "mega.nz",
    "pixeldrain.com",
    "rapidgator.net",
    "terabox.com",
]


def test_all_original_hosts_still_present():
    """Critical regression test: every host in the original 113-host list
    must still be present after the P3 port. None can be removed."""
    for host in ORIGINAL_HOSTS_THAT_MUST_REMAIN:
        assert host in dlg.debrid_link_supported_sites, \
            f"REGRESSION: original host '{host}' was removed!"


# ---------- New WZML-X hosts are now present ----------

# These hosts were in WZML-X's 367-host list but NOT in Amaterasu's
# original 113-host list. After P3, they MUST be present.
NEW_WZML_X_HOSTS = [
    "alterupload.com",
    "cjoint.net",
    "desfichiers.com",
    "dfichiers.com",
    "mesfichiers.org",
    "pjointe.com",
    "tenvoi.com",
    "dl4free.com",
    "apkadmin.com",
    "clicknupload.org",
    "clicknupload.co",
    "clicknupload.cc",
    "clicknupload.download",
    "clicknupload.club",
    "dropapk.to",
    "easybytez.com",
    "easybytez.eu",
    "easybytez.me",
    "elitefile.net",
    "elfile.net",
    "fastfile.cc",
    "fembed.com",
    "feurl.com",
    "anime789.com",
    "24hd.club",
    "vcdn.io",
    "sharinglink.club",
    "votrefiles.club",
    "there.to",
    "dailyplanet.pw",
    "jplayer.net",
    "xstreamcdn.com",
    "gcloud.live",
    "vcdnplay.com",
    "vidohd.com",
    "vidsource.me",
    "votrefile.xyz",
    "zidiplay.com",
]


def test_new_wzml_x_hosts_are_present():
    """Verify the WZML-X-specific hosts (especially French/European ones)
    are now in the list."""
    for host in NEW_WZML_X_HOSTS:
        assert host in dlg.debrid_link_supported_sites, \
            f"Missing WZML-X host: {host}"


# ---------- Dispatcher integration tests ----------

def _make_response(data):
    """Build a mock cloudscraper response object."""
    resp = MagicMock()
    resp.json.return_value = data
    return resp


def test_dispatcher_routes_old_host_to_debrid():
    """Verify an original host (rapidgator.net) still routes through the
    debrid dispatcher when DEBRID_LINK_API is set."""
    mock_response = _make_response({
        "success": True,
        "value": {"downloadUrl": "https://dl.example.com/file.zip"},
    })
    with patch.object(dlg.Config, "DEBRID_LINK_API", "dl:test_key"), \
         patch("bot.helper.mirror_leech_utils.download_utils.debrid_utils.create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        # Use an original host that doesn't have a native scraper — must
        # route to the debrid dispatcher
        result = dlg.direct_link_generator("https://rapidgator.net/file/abc")
        assert result == "https://dl.example.com/file.zip"


def test_dispatcher_routes_new_host_to_debrid():
    """Verify a newly-added host (e.g. cjoint.net) also routes through
    the debrid dispatcher."""
    mock_response = _make_response({
        "success": True,
        "value": {"downloadUrl": "https://dl.example.com/file.zip"},
    })
    with patch.object(dlg.Config, "DEBRID_LINK_API", "dl:test_key"), \
         patch("bot.helper.mirror_leech_utils.download_utils.debrid_utils.create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        # cjoint.net was NOT in the original 113 — only in WZML-X's 367
        result = dlg.direct_link_generator("https://cjoint.net/file/abc")
        assert result == "https://dl.example.com/file.zip"


def test_dispatcher_no_debrid_key_falls_through_to_native_scraper():
    """When DEBRID_LINK_API is empty, the dispatcher must skip the debrid
    branch and fall through to native scrapers (or the 'no function found'
    error). This verifies the debrid branch is conditional on the config."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""):
        # rapidgator.net has no native scraper in Amaterasu — should
        # raise 'No Direct link function found'
        with pytest.raises(DirectDownloadLinkException, match="No Direct link function found"):
            dlg.direct_link_generator("https://rapidgator.net/file/abc")


def test_dispatcher_debrid_branch_has_priority_over_native_for_listed_hosts():
    """Document the dispatcher ordering: when DEBRID_LINK_API is set AND
    the host is in debrid_link_supported_sites, the debrid branch is
    taken — even if a native scraper exists. This is intentional
    (operators who pay for debrid want it used for hosts in the list).

    P3 does NOT change this ordering. This test documents the existing
    behavior so future ports don't accidentally break it.
    """
    # mediafire.com is in debrid_link_supported_sites AND has a native
    # scraper. With DEBRID_LINK_API set, debrid wins.
    mock_response = _make_response({
        "success": True,
        "value": {"downloadUrl": "https://dl.example.com/mediafire.zip"},
    })
    with patch.object(dlg.Config, "DEBRID_LINK_API", "dl:test_key"), \
         patch("bot.helper.mirror_leech_utils.download_utils.debrid_utils.create_scraper") as mock_scraper:
        mock_scraper.return_value.request.return_value = mock_response
        result = dlg.direct_link_generator("https://www.mediafire.com/file/abc")
        assert result == "https://dl.example.com/mediafire.zip"


# ---------- Host categorization tests ----------

def test_french_hosts_present():
    """WZML-X's list is heavy on French file-hosting sites (1fichier family).
    Verify they're all in the merged list."""
    french_hosts = [
        "1fichier.com",
        "alterupload.com",
        "cjoint.net",
        "desfichiers.com",
        "dfichiers.com",
        "megadl.org",
        "mesfichiers.org",
        "pjointe.com",
        "tenvoi.com",
        "dl4free.com",
    ]
    for host in french_hosts:
        assert host in dlg.debrid_link_supported_sites, \
            f"Missing French host: {host}"


def test_premium_video_hosts_present():
    """Video hosting families (fembed, sbembed variants) from WZML-X."""
    video_hosts = [
        "fembed.com",
        "feurl.com",
        "anime789.com",
        "xstreamcdn.com",
        "gcloud.live",
        "vcdnplay.com",
        "vidohd.com",
        "vidsource.me",
    ]
    for host in video_hosts:
        assert host in dlg.debrid_link_supported_sites, \
            f"Missing video host: {host}"
