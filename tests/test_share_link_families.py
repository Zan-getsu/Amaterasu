"""Tests for Phase 1 port P4 — expanded share-link family recognition.

The is_share_link() regex now recognizes 5 new drive share-link
families: drivelinks, hubdrive, katdrive, kolop, sharerpp. These
families don't have dedicated scrapers — they route to the existing
sharer_scraper() fallback, which extracts the underlying Google Drive
URL using the generic share-link bypass logic.

Coverage:
  - All 5 new families are recognized by is_share_link()
  - All 4 original families still recognized (no regression)
  - gdtot with subdomain still recognized
  - Non-share URLs return False (no false positives)
  - Dispatcher routes new families to sharer_scraper()
  - Dispatcher routes filepress to filepress() (unchanged)
  - Dispatcher routes gdtot to sharer_scraper() (unchanged)
"""

from unittest.mock import patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.ext_utils.links_utils import is_share_link
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg

# ---------- is_share_link() — new families recognized ----------

NEW_FAMILIES = [
    "drivelinks",
    "hubdrive",
    "katdrive",
    "kolop",
    "sharerpp",
]


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_new_share_link_families_recognized(family):
    """Each of the 5 new families must be recognized by is_share_link()."""
    url = f"https://{family}.xyz/file/abc123"
    assert is_share_link(url), f"Family '{family}' not recognized as share link"


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_new_families_with_various_tlds(family):
    """The regex must match regardless of TLD (.com, .xyz, .co, .org)."""
    for tld in ["com", "xyz", "co", "org", "net", "info"]:
        url = f"https://{family}.{tld}/file/abc123"
        assert is_share_link(url), \
            f"Family '{family}' not recognized with TLD .{tld}"


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_new_families_with_www_prefix_not_matched_backward_compat(family):
    """www.{family}.com must NOT match — this is the original v1.6.3 behavior.
    The regex requires the bare domain (no www. or subdomain).
    This is preserved for backward compatibility.

    Note: the dispatcher extracts the hostname via urlparse and checks
    'filepress' in domain for filepress routing — it does NOT rely on
    is_share_link to match www. variants.
    """
    url = f"https://www.{family}.com/file/abc123"
    assert not is_share_link(url), \
        f"www.{family}.com should NOT match (backward compat)"


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_new_families_with_subdomain_not_matched_backward_compat(family):
    """sub.{family}.com must NOT match — same backward-compat reason."""
    url = f"https://sub.{family}.com/file/abc123"
    assert not is_share_link(url), \
        f"sub.{family}.com should NOT match (backward compat)"


# ---------- is_share_link() — original families still recognized ----------

ORIGINAL_FAMILIES = [
    "filepress",
    "filebee",
    "appdrive",
    "gdflix",
]


@pytest.mark.parametrize("family", ORIGINAL_FAMILIES)
def test_original_families_still_recognized(family):
    """All 4 original families must still be recognized (no regression)."""
    url = f"https://{family}.xyz/file/abc123"
    assert is_share_link(url), f"Original family '{family}' no longer recognized"


def test_gdtot_with_subdomain_recognized():
    """gdtot uses a different regex pattern (*.gdtot.*) — verify it still works."""
    assert is_share_link("https://new.gdtot.cc/file/abc123")
    assert is_share_link("https://my.gdtot.xyz/file/abc123")


def test_gdtot_without_subdomain_not_recognized():
    """gdtot requires a subdomain (the .+ before .gdtot. is mandatory).
    A bare 'gdtot.cc' should NOT match (the regex requires .+\\.gdtot\\.)."""
    # The regex is: https?:\/\/.+\.gdtot\.\S+
    # '.+' requires at least one char before .gdtot.
    # So 'https://gdtot.cc/...' should NOT match.
    assert not is_share_link("https://gdtot.cc/file/abc123")


# ---------- is_share_link() — false positive checks ----------

NON_SHARE_URLS = [
    "https://www.google.com/search?q=test",
    "https://drive.google.com/file/d/abc/view",
    "https://rapidgator.net/file/abc",
    "https://mediafire.com/file/abc",
    "https://fembed.com/v/abc",
    "https://sbembed.com/e/abc",
    "https://jiodrive.xyz/?file_id=abc",
    "https://terabox.com/sharing/link",
    "https://example.com/drivelinks",  # has 'drivelinks' in path, not domain
    "https://example.com/?ref=hubdrive",  # has 'hubdrive' in query, not domain
    "",
    "not a url",
    "https://",
    "ftp://katdrive.xyz/file",  # not http/https
]


@pytest.mark.parametrize("url", NON_SHARE_URLS)
def test_non_share_urls_not_recognized(url):
    """Sanity: non-share-link URLs must NOT match (no false positives)."""
    assert not is_share_link(url), \
        f"False positive: '{url}' should NOT be a share link"


# ---------- Dispatcher integration tests ----------

def test_dispatcher_routes_new_family_to_sharer_scraper():
    """When a new-family URL is sent to the dispatcher, it must route to
    sharer_scraper() (the fallback for share links)."""
    fake_url = "https://gdrive.example.com/file/abc"
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "sharer_scraper", return_value=fake_url) as mock_sharer:
        result = dlg.direct_link_generator("https://drivelinks.xyz/file/abc123")
        assert result == fake_url
        mock_sharer.assert_called_once_with("https://drivelinks.xyz/file/abc123")


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_dispatcher_routes_all_new_families_to_sharer_scraper(family):
    """All 5 new families must route to sharer_scraper()."""
    fake_url = "https://gdrive.example.com/file/abc"
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "sharer_scraper", return_value=fake_url) as mock_sharer:
        url = f"https://{family}.xyz/file/abc123"
        result = dlg.direct_link_generator(url)
        assert result == fake_url
        mock_sharer.assert_called_once_with(url)


def test_dispatcher_routes_filepress_to_filepress_function_unchanged():
    """filepress URLs must still route to filepress() (not sharer_scraper)."""
    fake_url = "https://gdrive.example.com/file/abc"
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
         patch.object(dlg, "filepress", return_value=fake_url) as mock_fp, \
         patch.object(dlg, "sharer_scraper") as mock_sharer:
        result = dlg.direct_link_generator("https://filepress.xyz/file/abc123")
        assert result == fake_url
        mock_fp.assert_called_once()
        mock_sharer.assert_not_called()


def test_dispatcher_routes_non_filepress_share_links_to_sharer():
    """gdtot, filebee, appdrive, gdflix + 5 new families all route to
    sharer_scraper(). Verify the dispatcher logic:
        return filepress(link) if "filepress" in domain else sharer_scraper(link)
    """
    families_to_test = ["gdtot.xyz", "filebee.xyz", "appdrive.xyz",
                        "gdflix.xyz"] + [f"{f}.xyz" for f in NEW_FAMILIES]
    # Note: gdtot uses a subdomain pattern, so we need a subdomain for it
    families_to_test[0] = "new.gdtot.cc"

    fake_url = "https://gdrive.example.com/file/abc"
    for domain in families_to_test:
        with patch.object(dlg.Config, "DEBRID_LINK_API", ""), \
             patch.object(dlg, "sharer_scraper", return_value=fake_url) as mock_sharer:
            url = f"https://{domain}/file/abc123"
            try:
                result = dlg.direct_link_generator(url)
                assert result == fake_url, f"Domain {domain} did not route correctly"
                mock_sharer.assert_called_once()
            except DirectDownloadLinkException as e:
                if "No Direct link function found" in str(e):
                    pytest.fail(f"Domain {domain} not routed to sharer_scraper: {e}")


# ---------- Backward compatibility ----------

def test_no_false_positive_for_rapidgator():
    """rapidgator.net must NOT match is_share_link (would cause it to be
    routed to sharer_scraper instead of falling through to debrid/fallback)."""
    assert not is_share_link("https://rapidgator.net/file/abc")
    assert not is_share_link("https://www.rapidgator.net/file/abc")


def test_no_false_positive_for_terabox():
    """terabox.com must NOT match is_share_link."""
    assert not is_share_link("https://terabox.com/sharing/link")
    assert not is_share_link("https://1024tera.com/file/abc")


def test_no_false_positive_for_doodstream():
    """doodstream.com must NOT match is_share_link."""
    assert not is_share_link("https://doodstream.com/e/abc")


def test_no_false_positive_for_fembed():
    """fembed.com must NOT match is_share_link."""
    assert not is_share_link("https://fembed.com/v/abc")


def test_is_share_link_handles_none_input():
    """None input must not crash — return False (defensive guard)."""
    assert not is_share_link(None)


def test_is_share_link_handles_empty_input():
    """Empty string must return False."""
    assert not is_share_link("")


def test_is_share_link_handles_non_string_input():
    """Non-string input must not crash — return False."""
    assert not is_share_link(123)
    assert not is_share_link([])
    assert not is_share_link({})
