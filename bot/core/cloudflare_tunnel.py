from asyncio import TimeoutError, create_subprocess_exec, create_task, wait_for
from asyncio.subprocess import PIPE, STDOUT
from re import search
from shutil import which

from .. import LOGGER
from ..helper.ext_utils.db_handler import database
from .config_manager import Config


_proc = None
_log_task = None


def _auto_url_enabled():
    return bool(Config.CLOUDFLARE_TUNNEL_AUTO_URL)


def _target_url():
    if Config.CLOUDFLARE_TUNNEL_TARGET:
        return Config.CLOUDFLARE_TUNNEL_TARGET
    return f"http://127.0.0.1:{Config.PORT or 8080}"


async def _watch_logs(proc):
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", "ignore").strip()
        if not text:
            continue
        LOGGER.info(f"Cloudflare Tunnel: {text}")
        match = search(r"https://([a-zA-Z0-9-]+\.trycloudflare\.com)", text)
        if not match or not _auto_url_enabled():
            continue

        Config.BASE_URL = f"https://{match.group(1)}"
        Config.construct_base_url()
        LOGGER.info(f"Cloudflare quick tunnel URL set as BASE_URL: {Config.BASE_URL}")
        if database.db is not None:
            await database.update_config(
                {
                    "BASE_URL": Config.BASE_URL,
                    "FQDN": "",
                    "HAS_SSL": True,
                    "NO_PORT": True,
                    "BASE_URL_PORT": Config.PORT,
                    "CLOUDFLARE_TUNNEL_AUTO_FQDN": None,
                }
            )


async def stop_cloudflare_tunnel():
    global _proc, _log_task
    if _log_task and not _log_task.done():
        _log_task.cancel()
    _log_task = None
    if _proc and _proc.returncode is None:
        _proc.terminate()
        try:
            await wait_for(_proc.wait(), timeout=10)
        except (Exception, TimeoutError):
            _proc.kill()
    _proc = None


async def cloudflare_tunnel_booter():
    global _proc, _log_task
    await stop_cloudflare_tunnel()
    if not Config.CLOUDFLARE_TUNNEL_ENABLED:
        return

    if not which("cloudflared"):
        LOGGER.warning(
            "CLOUDFLARE_TUNNEL_ENABLED is True but cloudflared is not installed."
        )
        return

    metrics = Config.CLOUDFLARE_TUNNEL_METRICS or "127.0.0.1:49312"
    cmd = ["cloudflared", "tunnel", "--no-autoupdate", "--metrics", metrics]
    if Config.CLOUDFLARE_TUNNEL_TOKEN:
        cmd.extend(["run", "--token", Config.CLOUDFLARE_TUNNEL_TOKEN])
    else:
        cmd.extend(["--url", _target_url()])

    safe_cmd = " ".join(
        "<token>" if part == Config.CLOUDFLARE_TUNNEL_TOKEN else part
        for part in cmd
    )
    LOGGER.info(f"Starting Cloudflare Tunnel: {safe_cmd}")
    try:
        _proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=STDOUT)
        _log_task = create_task(_watch_logs(_proc))
    except Exception as e:
        LOGGER.error(f"Failed to start Cloudflare Tunnel: {e}")
        _proc = None
        _log_task = None
