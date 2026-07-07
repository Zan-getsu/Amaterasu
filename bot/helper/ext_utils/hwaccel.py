"""Phase 3.1 — FFmpeg hardware acceleration auto-detection.

At bot startup, probes for NVENC (NVIDIA), QSV (Intel), VAAPI (AMD/Intel
Linux), VideoToolbox (macOS). Exposes get_best_hw_encoder() returning
the encoder name or 'libx264' (software fallback).

Config override: FFMPEG_HW_ACCEL (string: 'auto', 'nvenc', 'qsv',
'vaapi', 'none', default 'auto').

Logs the detected encoder at startup: 'FFmpeg encoder: [nvenc|libx264|...]'.

Used in media_utils.py encode calls.
"""

from asyncio import create_subprocess_exec, create_subprocess_shell
from asyncio.subprocess import PIPE
from logging import getLogger

LOGGER = getLogger(__name__)

# Detected encoder — populated on first call to get_best_hw_encoder()
_detected_encoder = None
_detection_done = False


async def _run_cmd(cmd):
    """Run a shell command and return (stdout, stderr). Returns ('', '')
    on any error — never raises."""
    try:
        if isinstance(cmd, str):
            proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
        else:
            proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", "ignore") if stdout else ""
    except Exception:
        return ""


async def _probe_nvenc():
    """Check for NVIDIA NVENC support. Returns encoder name or None."""
    out = await _run_cmd("ffmpeg -hide_banner -encoders 2>/dev/null | grep -i nvenc")
    if "h264_nvenc" in out:
        return "h264_nvenc"
    return None


async def _probe_qsv():
    """Check for Intel Quick Sync Video support. Returns encoder name or None."""
    out = await _run_cmd("ffmpeg -hide_banner -encoders 2>/dev/null | grep -i qsv")
    if "h264_qsv" in out:
        return "h264_qsv"
    return None


async def _probe_vaapi():
    """Check for VAAPI (AMD/Intel Linux) support. Returns encoder name or None."""
    out = await _run_cmd("ffmpeg -hide_banner -encoders 2>/dev/null | grep -i vaapi")
    if "h264_vaapi" in out:
        return "h264_vaapi"
    return None


async def _probe_videotoolbox():
    """Check for macOS VideoToolbox support. Returns encoder name or None."""
    out = await _run_cmd("ffmpeg -hide_banner -encoders 2>/dev/null | grep -i videotoolbox")
    if "h264_videotoolbox" in out:
        return "h264_videotoolbox"
    return None


async def _detect_encoder():
    """Probe for hardware encoders and return the best available.

    Priority order: NVENC (NVIDIA, fastest) → QSV (Intel) → VAAPI
    (AMD/Intel Linux) → VideoToolbox (macOS) → libx264 (software fallback).
    """
    # Check config override first
    from bot.core.config_manager import Config
    override = getattr(Config, "FFMPEG_HW_ACCEL", "auto").lower().strip()

    if override == "none":
        LOGGER.info("FFmpeg encoder: libx264 (software, FFMPEG_HW_ACCEL=none)")
        return "libx264"
    if override == "nvenc":
        encoder = await _probe_nvenc()
        if encoder:
            LOGGER.info(f"FFmpeg encoder: {encoder} (NVIDIA NVENC, configured)")
            return encoder
        LOGGER.warning("FFMPEG_HW_ACCEL=nvenc but NVENC not available — falling back to libx264")
        return "libx264"
    if override == "qsv":
        encoder = await _probe_qsv()
        if encoder:
            LOGGER.info(f"FFmpeg encoder: {encoder} (Intel QSV, configured)")
            return encoder
        LOGGER.warning("FFMPEG_HW_ACCEL=qsv but QSV not available — falling back to libx264")
        return "libx264"
    if override == "vaapi":
        encoder = await _probe_vaapi()
        if encoder:
            LOGGER.info(f"FFmpeg encoder: {encoder} (VAAPI, configured)")
            return encoder
        LOGGER.warning("FFMPEG_HW_ACCEL=vaapi but VAAPI not available — falling back to libx264")
        return "libx264"

    # auto — probe in priority order
    for probe_fn, label in [
        (_probe_nvenc, "NVIDIA NVENC"),
        (_probe_qsv, "Intel QSV"),
        (_probe_vaapi, "VAAPI"),
        (_probe_videotoolbox, "VideoToolbox"),
    ]:
        encoder = await probe_fn()
        if encoder:
            LOGGER.info(f"FFmpeg encoder: {encoder} ({label}, auto-detected)")
            return encoder

    LOGGER.info("FFmpeg encoder: libx264 (software fallback, no hardware encoder detected)")
    return "libx264"


async def get_best_hw_encoder():
    """Return the best available hardware encoder name.

    Caches the result after first detection. Returns 'libx264' as the
    software fallback if no hardware encoder is available.

    For HEVC encoding, append '_hevc' variants when available — call
    get_best_hevc_encoder() instead.
    """
    global _detected_encoder, _detection_done
    if _detection_done:
        return _detected_encoder
    _detected_encoder = await _detect_encoder()
    _detection_done = True
    return _detected_encoder


async def get_best_hevc_encoder():
    """Return the best available HEVC hardware encoder name.

    Mirrors get_best_hw_encoder() but for H.265/HEVC. Returns
    'libx265' as the software fallback.
    """
    from bot.core.config_manager import Config
    override = getattr(Config, "FFMPEG_HW_ACCEL", "auto").lower().strip()

    if override == "none":
        return "libx265"

    # Probe for HEVC variants
    out = await _run_cmd("ffmpeg -hide_banner -encoders 2>/dev/null")
    if "hevc_nvenc" in out and override in ("auto", "nvenc"):
        return "hevc_nvenc"
    if "hevc_qsv" in out and override in ("auto", "qsv"):
        return "hevc_qsv"
    if "hevc_vaapi" in out and override in ("auto", "vaapi"):
        return "hevc_vaapi"
    if "hevc_videotoolbox" in out and override in ("auto",):
        return "hevc_videotoolbox"
    return "libx265"


def get_detected_encoder_sync():
    """Return the cached detected encoder (or None if not yet detected).

    Synchronous — for use in code paths that can't await. Call
    get_best_hw_encoder() at startup to populate the cache.
    """
    return _detected_encoder


async def init_hwaccel_detection():
    """Entry point — called from bot/__main__.py at startup to pre-warm
    the detection cache so the first encode doesn't pay the probe cost."""
    await get_best_hw_encoder()
