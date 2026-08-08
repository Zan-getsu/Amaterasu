"""Paths for mutable application state that must not live in the Git checkout."""

from os import environ
from pathlib import Path
from shutil import copyfile

APP_ROOT = Path(__file__).resolve().parents[2]
QBITTORRENT_TEMPLATE_PATH = (
    APP_ROOT / "configs/qbittorrent/qBittorrent/config/qBittorrent.conf"
)
SABNZBD_TEMPLATE_PATH = APP_ROOT / "configs/sabnzbd/SABnzbd.ini"


def _runtime_root():
    configured = environ.get("AMATERASU_RUNTIME_DIR")
    if configured:
        return Path(configured)

    docker_data = Path("/data")
    if docker_data.is_dir():
        return docker_data / "amaterasu"

    return APP_ROOT / ".runtime"


RUNTIME_ROOT = _runtime_root()
QBITTORRENT_RUNTIME_DIR = RUNTIME_ROOT / "qbittorrent"
QBITTORRENT_CONFIG_PATH = (
    QBITTORRENT_RUNTIME_DIR / "qBittorrent/config/qBittorrent.conf"
)
SABNZBD_RUNTIME_DIR = RUNTIME_ROOT / "sabnzbd"
SABNZBD_CONFIG_PATH = SABNZBD_RUNTIME_DIR / "SABnzbd.ini"


def ensure_qbittorrent_runtime_profile():
    """Create qBittorrent's writable profile from the tracked template once."""
    QBITTORRENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not QBITTORRENT_CONFIG_PATH.exists():
        copyfile(QBITTORRENT_TEMPLATE_PATH, QBITTORRENT_CONFIG_PATH)
    return QBITTORRENT_RUNTIME_DIR


def ensure_sabnzbd_runtime_config():
    """Create the mutable SABnzbd config from the tracked template once.

    Existing runtime configuration is never overwritten. MongoDB restoration and
    normal SABnzbd writes therefore persist independently of the source checkout.
    """
    SABNZBD_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not SABNZBD_CONFIG_PATH.exists():
        copyfile(SABNZBD_TEMPLATE_PATH, SABNZBD_CONFIG_PATH)
    return SABNZBD_CONFIG_PATH
