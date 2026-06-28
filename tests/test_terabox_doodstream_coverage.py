"""Tests for Phase 1 ports P5 & P6 — terabox and doodstream domain coverage.

Research finding: Amaterasu's existing terabox (17 domains) and
doodstream (23 domains) dispatcher branches are ALREADY supersets of
WZML-X's lists (7 terabox + 18 doodstream). No code changes needed.

This file locks in the current domain lists as regression tests so
future refactors cannot accidentally shrink coverage.

Verified against:
  - Amaterasu v1.6.3 (current main)
  - WZML-X master (downloaded June 2026)
"""

from unittest.mock import patch

import pytest

from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg

# ---------- terabox domain coverage (P5) ----------

# These 17 terabox-family domains are currently in Amaterasu's dispatcher.
# Every one of them MUST continue to route to the terabox() function.
TERABOX_DOMAINS = [
    "terabox.com",
    "nephobox.com",
    "4funbox.com",
    "mirrobox.com",
    "momerybox.com",
    "teraboxapp.com",
    "1024tera.com",
    "terabox.app",
    "gibibox.com",
    "goaibox.com",
    "terasharelink.com",
    "teraboxlink.com",
    "freeterabox.com",
    "1024terabox.com",
    "teraboxshare.com",
    "terafileshare.com",
    "terabox.club",
]


def test_terabox_domain_count_meets_threshold():
    """Amaterasu's terabox list must have at least 15 domains (currently 17).
    WZML-X has only 7; Amaterasu is the superset."""
    # Read the dispatcher source to count terabox domains
    import inspect
    src = inspect.getsource(dlg.direct_link_generator)
    # Count terabox-family domains in the dispatcher's terabox branch
    terabox_count = sum(1 for d in TERABOX_DOMAINS if d in src)
    assert terabox_count >= 15, \
        f"Only {terabox_count} terabox domains found; expected >= 15"


def test_terabox_dispatcher_routes_all_known_domains():
    """Every known terabox mirror domain must route to terabox() (not to
    the debrid branch, not to the 'no function found' error)."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""):
        for domain in TERABOX_DOMAINS:
            url = f"https://{domain}/sharing/link"
            # The dispatcher should NOT raise "No Direct link function found"
            # for any of these — it should route to terabox() which may
            # then raise a different error (e.g. "terabox.txt not found").
            try:
                dlg.direct_link_generator(url)
            except DirectDownloadLinkException as e:
                msg = str(e)
                # Acceptable: terabox() raised an error about cookies/etc.
                assert "No Direct link function found" not in msg, \
                    f"Domain {domain} not routed to terabox(): {msg}"
            except Exception as e:
                pytest.fail(
                    f"Domain {domain} raised unexpected {type(e).__name__}: {e}"
                )


def test_terabox_is_superset_of_wzml_x():
    """Amaterasu's terabox list must be a superset of WZML-X's
    7-domain list. WZML-X domains: terabox.com, nephobox.com,
    4funbox.com, mirrobox.com, momerybox.com, teraboxapp.com, 1024tera.com."""
    wzml_x_terabox = [
        "terabox.com", "nephobox.com", "4funbox.com", "mirrobox.com",
        "momerybox.com", "teraboxapp.com", "1024tera.com",
    ]
    import inspect
    src = inspect.getsource(dlg.direct_link_generator)
    for domain in wzml_x_terabox:
        assert domain in src, \
            f"WZML-X terabox domain '{domain}' missing from Amaterasu dispatcher"


# ---------- doodstream domain coverage (P6) ----------

# These 23 doodstream-family domains are currently in Amaterasu's dispatcher.
DOODSTREAM_DOMAINS = [
    "dood.watch",
    "doodstream.com",
    "dood.to",
    "dood.so",
    "dood.cx",
    "dood.la",
    "dood.ws",
    "dood.sh",
    "doodstream.co",
    "dood.pm",
    "dood.wf",
    "dood.re",
    "dood.video",
    "dooood.com",
    "dood.yt",
    "doods.yt",
    "dood.stream",
    "doods.pro",
    "ds2play.com",
    "d0o0d.com",
    "ds2video.com",
    "do0od.com",
    "d000d.com",
]


def test_doodstream_domain_count_meets_threshold():
    """Amaterasu's doodstream list must have at least 20 domains (currently 23).
    WZML-X has only 18; Amaterasu is the superset."""
    import inspect
    src = inspect.getsource(dlg.direct_link_generator)
    dood_count = sum(1 for d in DOODSTREAM_DOMAINS if d in src)
    assert dood_count >= 20, \
        f"Only {dood_count} doodstream domains found; expected >= 20"


def test_doodstream_dispatcher_routes_all_known_domains():
    """Every known doodstream mirror domain must route to doods()."""
    with patch.object(dlg.Config, "DEBRID_LINK_API", ""):
        for domain in DOODSTREAM_DOMAINS:
            url = f"https://{domain}/e/abc123"
            try:
                dlg.direct_link_generator(url)
            except DirectDownloadLinkException as e:
                msg = str(e)
                assert "No Direct link function found" not in msg, \
                    f"Domain {domain} not routed to doods(): {msg}"
            except Exception as e:
                pytest.fail(
                    f"Domain {domain} raised unexpected {type(e).__name__}: {e}"
                )


def test_doodstream_is_superset_of_wzml_x():
    """Amaterasu's doodstream list must be a superset of WZML-X's
    18-domain list."""
    wzml_x_doods = [
        "dood.watch", "doodstream.com", "dood.to", "dood.so", "dood.cx",
        "dood.la", "dood.ws", "dood.sh", "doodstream.co", "dood.pm",
        "dood.wf", "dood.re", "dood.video", "dooood.com", "dood.yt",
        "doods.yt", "dood.stream", "doods.pro",
    ]
    import inspect
    src = inspect.getsource(dlg.direct_link_generator)
    for domain in wzml_x_doods:
        assert domain in src, \
            f"WZML-X doodstream domain '{domain}' missing from Amaterasu dispatcher"


# ---------- Combined regression test ----------

def test_terabox_and_doodstream_lists_are_disjoint():
    """Sanity: no domain appears in both terabox and doodstream lists
    (would cause dispatcher ambiguity)."""
    terabox_set = set(TERABOX_DOMAINS)
    dood_set = set(DOODSTREAM_DOMAINS)
    overlap = terabox_set & dood_set
    assert not overlap, f"Overlap found: {overlap}"
