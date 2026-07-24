import re

from contextlib import suppress
from fractions import Fraction
from PIL import Image
from hashlib import md5
from aiofiles.os import remove, path as aiopath, makedirs
import json
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
    sleep,
)
from asyncio.subprocess import PIPE
from os import path as ospath
from re import search as re_search, escape
from shutil import which
from time import time, time_ns
from aioshutil import rmtree
from langcodes import Language
from niquests import AsyncSession

from ... import LOGGER, DOWNLOAD_DIR, threads, cores
from ...core.config_manager import BinConfig
from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive, is_archive_split
from .status_utils import time_to_seconds


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()


def _convert_image(src, dst):
    with Image.open(src) as im:
        im.convert("RGB").save(dst, "JPEG", quality=95)


def _prepare_telegram_thumbnail(src, dst):
    """Create a Telegram-compatible JPEG thumbnail.

    Telegram document/audio thumbnails must be JPEG, fit within 320x320, and
    remain below 200 KiB. Normalizing every custom/generated thumbnail here
    prevents WZGram from retrying the upload without an invalid thumbnail.
    """
    with Image.open(src) as image:
        thumb = image.convert("RGB")
        thumb.thumbnail((320, 320), Image.Resampling.LANCZOS)

    for quality in (90, 80, 70, 60, 50, 40):
        thumb.save(dst, "JPEG", quality=quality, optimize=True)
        if ospath.getsize(dst) < 200 * 1024:
            break
    return dst


def _prepare_hd_thumbnail(src, dst):
    """Create a high-resolution JPEG suitable for Telegram video covers."""
    with Image.open(src) as image:
        cover = image.convert("RGB")
        cover.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        cover.save(dst, "JPEG", quality=92, optimize=True)
    return dst


async def create_telegram_thumbnail(src):
    """Create the small legacy thumbnail used alongside an HD video cover."""
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time_ns()}_telegram.jpg")
    try:
        return await sync_to_async(_prepare_telegram_thumbnail, src, output)
    except Exception as e:
        LOGGER.warning(f"Could not prepare Telegram thumbnail from {src}: {e}")
        with suppress(Exception):
            await remove(output)
        return None


async def create_thumb(msg, _id=""):
    if not _id:
        _id = int(time() * 1000)
        path = f"{DOWNLOAD_DIR}thumbnails"
    else:
        path = "thumbnails"
    await makedirs(path, exist_ok=True)
    try:
        photo_dir = await msg.download()
    except Exception as e:
        LOGGER.error(f"Failed to download photo: {e}")
        return ""
    output = ospath.join(path, f"{_id}.jpg")
    await sync_to_async(_prepare_hd_thumbnail, photo_dir, output)
    await remove(photo_dir)
    return output


async def download_image_thumb(url):
    """Download an image from a URL and save it as a JPEG thumbnail.

    Validates that the URL points to an image via Content-Type header check.
    Returns the path to the saved thumbnail, or empty string on failure.
    """
    # Content types that are definitely NOT images
    NON_IMAGE_TYPES = (
        "text/",
        "application/json",
        "application/xml",
        "application/javascript",
        "video/",
        "audio/",
    )
    try:
        async with AsyncSession(timeout=30) as client:
            try:
                head_resp = await client.head(url, allow_redirects=True)
                ct = head_resp.headers.get("content-type", "")
                if ct and any(ct.startswith(t) for t in NON_IMAGE_TYPES):
                    LOGGER.error(f"Thumb URL is not an image: {ct}")
                    return ""
            except Exception:
                pass  # HEAD failed, will check during GET

            # Download the image
            resp = await client.get(url)
            if resp.status_code != 200:
                LOGGER.error(f"Failed to download thumb URL: HTTP {resp.status_code}")
                return ""

            # Only reject known non-image types; unknown types are allowed
            # PIL will validate the actual image data below
            content_type = resp.headers.get("content-type", "")
            if content_type and any(
                content_type.startswith(t) for t in NON_IMAGE_TYPES
            ):
                LOGGER.error(f"Thumb URL is not an image: {content_type}")
                return ""

            data = resp.content

            # Save and convert to JPEG
            path = f"{DOWNLOAD_DIR}thumbnails"
            await makedirs(path, exist_ok=True)
            tmp_path = ospath.join(path, f"{time()}_tmp")
            with open(tmp_path, "wb") as f:
                f.write(data)
            output = ospath.join(path, f"{time()}.jpg")

            try:
                await sync_to_async(_prepare_hd_thumbnail, tmp_path, output)
            except Exception as e:
                LOGGER.error(f"Failed to process thumb image: {e}")
                with suppress(Exception):
                    await remove(tmp_path)
                return ""
            with suppress(Exception):
                await remove(tmp_path)
            return output
    except Exception as e:
        LOGGER.error(f"Error downloading thumb from URL: {e}")
        return ""

async def download_custom_thumb(url):
    if url.startswith(("https://t.me/", "https://telegram.me/", "tg://")):
        try:
            from ..telegram_helper.message_utils import get_tg_link_message
            msg, _ = await get_tg_link_message(url)
            if isinstance(msg, list):
                msg = msg[0]
            if msg and (getattr(msg, "photo", None) or getattr(msg, "document", None)):
                path = f"{DOWNLOAD_DIR}thumbnails"
                await makedirs(path, exist_ok=True)
                tmp_path = ospath.join(path, f"{time()}_tmp")
                await msg.download(file_name=tmp_path)
                
                output = ospath.join(path, f"{time()}.jpg")
                try:
                    await sync_to_async(_prepare_hd_thumbnail, tmp_path, output)
                except Exception as e:
                    LOGGER.error(f"Failed to process telegram thumb image: {e}")
                    with suppress(Exception):
                        await remove(tmp_path)
                    return ""
                with suppress(Exception):
                    await remove(tmp_path)
                return output
        except Exception as e:
            LOGGER.error(f"Error downloading telegram thumb from URL: {e}")
            return ""
    return await download_image_thumb(url)


async def get_media_info(path, extra_info=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return (0, "", "", "") if extra_info else (0, None, None)
    if result[0] and result[2] == 0:
        try:
            ffresult = json.loads(result[0])
        except json.JSONDecodeError as e:
            LOGGER.error(f"get_media_info: invalid ffprobe JSON: {e}")
            return (0, "", "", "") if extra_info else (0, None, None)

        fields = ffresult.get("format")
        if fields is None:
            LOGGER.error(f"get_media_info: {result}")
            return (0, "", "", "") if extra_info else (0, None, None)
            
        duration = float(fields.get("duration", 0))
        if duration == 0 and "tags" in fields and "DURATION" in fields["tags"]:
            from ..ext_utils.status_utils import time_to_seconds
            duration = float(time_to_seconds(fields["tags"]["DURATION"]))
        if duration == 0 and "streams" in ffresult:
            for stream in ffresult["streams"]:
                if "duration" in stream:
                    duration = float(stream["duration"])
                    if duration > 0:
                        break
                if "tags" in stream and "DURATION" in stream["tags"]:
                    from ..ext_utils.status_utils import time_to_seconds
                    duration = float(time_to_seconds(stream["tags"]["DURATION"]))
                    if duration > 0:
                        break
        duration = round(duration)
        if extra_info:
            lang, qual, stitles = "", "", ""
            if (streams := ffresult.get("streams")) and streams[0].get(
                "codec_type"
            ) == "video":
                qual = int(streams[0].get("height"))
                qual = f"{480 if qual <= 480 else 540 if qual <= 540 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
                for stream in streams:
                    if stream.get("codec_type") == "audio" and (
                        lc := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            lc = Language.get(lc).display_name()
                        if lc not in lang:
                            lang += f"{lc}, "
                    if stream.get("codec_type") == "subtitle" and (
                        st := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            st = Language.get(st).display_name()
                        if st not in stitles:
                            stitles += f"{st}, "
            return duration, qual, lang[:-2], stitles[:-2]
        tags = fields.get("tags", {})
        artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
        title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        return duration, artist, title
    return (0, "", "", "") if extra_info else (0, None, None)


def _parse_frame_rate(rate):
    with suppress(Exception):
        if not rate or rate == "0/0":
            return 0
        return float(Fraction(rate))
    return 0


async def get_video_frame_count(path, duration=0):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-select_streams",
                "v:0",
                "-print_format",
                "json",
                "-show_entries",
                "stream=nb_frames,avg_frame_rate,r_frame_rate,duration:stream_tags=DURATION",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Video Frame Count: {e}. Mostly File not found! - File: {path}")
        return 0
    if not result[0] or result[2] != 0:
        return 0
    try:
        fields = json.loads(result[0]).get("streams") or []
    except json.JSONDecodeError as e:
        LOGGER.error(f"get_video_frame_count: invalid ffprobe JSON: {e}")
        return 0
    if not fields:
        return 0
    stream = fields[0]
    nb_frames = stream.get("nb_frames")
    if isinstance(nb_frames, str) and nb_frames.isdigit():
        return int(nb_frames)
    stream_duration = duration or 0
    with suppress(Exception):
        stream_duration = float(stream.get("duration") or stream_duration)
    if not stream_duration and (tag_duration := stream.get("tags", {}).get("DURATION")):
        stream_duration = time_to_seconds(tag_duration)
    frame_rate = _parse_frame_rate(stream.get("avg_frame_rate")) or _parse_frame_rate(
        stream.get("r_frame_rate")
    )
    if stream_duration and frame_rate:
        return max(1, round(stream_duration * frame_rate))
    return 0


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    path_lower = path.lower()
    if (
        is_archive(path_lower)
        or is_archive_split(path_lower)
        # Disk/firmware images can contain byte patterns that ffprobe sees as
        # media streams. Keep them as Telegram documents unless the user
        # explicitly converts/renames them to a media container.
        or re_search(r".+(\.|_)(rar|7z|zip|bin|img)(\.0*\d+)?$", path_lower)
    ):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith("image"):
        return False, False, True
    if mime_type.startswith("text"):
        return False, False, False
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ]
        )
        if result[1] and mime_type.startswith("video"):
            is_video = True
    except Exception as e:
        LOGGER.error(f"Get Document Type: {e}. Mostly File not found! - File: {path}")
        if mime_type.startswith("audio"):
            return False, True, False
        if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
            return is_video, is_audio, is_image
        if mime_type.startswith("video"):
            is_video = True
        return is_video, is_audio, is_image
    if result[0] and result[2] == 0:
        try:
            fields = json.loads(result[0]).get("streams")
        except json.JSONDecodeError as e:
            LOGGER.error(f"get_document_type: invalid ffprobe JSON: {e}")
            return is_video, is_audio, is_image
        if fields is None:
            LOGGER.error(f"get_document_type: {result}")
            return is_video, is_audio, is_image
        is_video = False
        for stream in fields:
            if stream.get("codec_type") == "video":
                codec_name = stream.get("codec_name", "").lower()
                if codec_name not in {"mjpeg", "png", "bmp"}:
                    is_video = True
            elif stream.get("codec_type") == "audio":
                is_audio = True
    return is_video, is_audio, is_image


def get_encode_output_path(input_path, codec):
    base, ext = ospath.splitext(input_path)
    suffix = "_encoded"
    return f"{base}{suffix}{ext}"


async def get_streams(file):
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        file,
    ]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting stream info: {stderr.decode().strip()}")
        return None

    try:
        return json.loads(stdout)["streams"]
    except KeyError:
        LOGGER.error(
            f"No streams found in the ffprobe output: {stdout.decode().strip()}",
        )
        return None


async def take_ss(video_file, ss_nb) -> bool:
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath, name = video_file.rsplit("/", 1)
        name, _ = ospath.splitext(name)
        dirpath = f"{dirpath}/{name}_mltbss"
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        cmds = []
        for i in range(ss_nb):
            output = f"{dirpath}/SS.{name}_{i:02}.png"
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{cap_time}",
                "-i",
                video_file,
                "-q:v",
                "1",
                "-frames:v",
                "1",
                "-threads",
                f"{threads}",
                output,
            ]
            cap_time += interval
            cmds.append(cmd_exec(cmd))
        try:
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating screenshots from video. Path: {video_file}. stderr: {resutls[0][1]}"
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except Exception:
            LOGGER.error(
                f"Error while creating screenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    else:
        LOGGER.error("take_ss: Can't get the duration of video")
        return False


async def get_audio_thumbnail(audio_file):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.warning(
                f"Could not extract thumbnail from audio. Name: {audio_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.warning(
            f"Could not extract thumbnail from audio. Name: {audio_file}. Timeout or ffmpeg issue."
        )
        return None
    try:
        await sync_to_async(_prepare_telegram_thumbnail, output, output)
    except Exception as e:
        LOGGER.warning(f"Could not normalize audio thumbnail {output}: {e}")
        return None
    return output


async def get_video_thumbnail(video_file, duration):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vf",
        "thumbnail,format=yuvj420p",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "image2",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.warning(
                f"Error while extracting thumbnail from video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.warning(
            f"Error while extracting thumbnail from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    try:
        await sync_to_async(_prepare_hd_thumbnail, output, output)
    except Exception as e:
        LOGGER.warning(f"Could not normalize video thumbnail {output}: {e}")
        return None
    return output


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    layout = re.sub(r"(\d+)\D+(\d+)", r"\1x\2", layout)
    ss_nb = layout.split("x")
    if len(ss_nb) != 2 or not ss_nb[0].isdigit() or not ss_nb[1].isdigit():
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    ss_nb = int(ss_nb[0]) * int(ss_nb[1])
    if ss_nb == 0:
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    dirpath = await take_ss(video_file, ss_nb)
    if not dirpath:
        return None
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while combining thumbnails for video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while combining thumbnails from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    finally:
        if not keep_screenshots:
            await rmtree(dirpath, ignore_errors=True)
    try:
        await sync_to_async(_prepare_hd_thumbnail, output, output)
    except Exception as e:
        LOGGER.warning(f"Could not normalize thumbnail layout {output}: {e}")
        return None
    return output


class FFMpeg:
    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._last_processed_bytes = 0
        self._processed_time = 0
        self._last_processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._total_time = 0
        self._total_frames = 0
        self._processed_frames = 0
        self._progress_keys = set()
        self._progress_keys_logged = False
        self._eta_raw = 0
        self._time_rate = 0.1
        self._start_time = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed_raw(self):
        return self._speed_raw

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    @staticmethod
    def _parse_progress_time(key, value):
        if key == "out_time":
            return time_to_seconds(value)
        if key in {"out_time_us", "out_time_ms"}:
            return int(value) / 1_000_000
        return None

    def _set_progress_percent(self, progress, *, eta=None):
        self._progress_raw = min(100, max(0, progress))
        if (
            hasattr(self._listener, "subsize")
            and self._listener.subsize
            and self._progress_raw > 0
        ):
            self._processed_bytes = int(
                self._listener.subsize * (self._progress_raw / 100)
            )
        elapsed = time() - self._start_time
        self._speed_raw = self._processed_bytes / elapsed if elapsed > 0 else 0
        if eta is not None:
            self._eta_raw = max(0, eta)
        elif self._progress_raw > 0 and elapsed > 0:
            self._eta_raw = max(0, elapsed * (100 - self._progress_raw) / self._progress_raw)
        else:
            self._eta_raw = 0

    def clear(self):
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._processed_frames = 0
        self._total_frames = 0
        self._progress_keys = set()
        self._progress_keys_logged = False
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

    async def _ffmpeg_progress(self):
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 60)
            except Exception:
                break
            line = line.decode().strip()
            if not line:
                await sleep(0.05)
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                self._progress_keys.add(key)
                if value != "N/A":
                    if key == "total_size":
                        with suppress(ValueError):
                            if self._progress_raw <= 0:
                                self._processed_bytes = (
                                    int(value) + self._last_processed_bytes
                                )
                                elapsed = time() - self._start_time
                                self._speed_raw = (
                                    self._processed_bytes / elapsed if elapsed > 0 else 0
                                )
                                if (
                                    hasattr(self._listener, "subsize")
                                    and self._listener.subsize
                                    and self._processed_bytes > 0
                                ):
                                    self._set_progress_percent(
                                        (self._processed_bytes * 100)
                                        / self._listener.subsize
                                    )
                    elif key == "frame":
                        with suppress(ValueError):
                            self._processed_frames = int(value)
                            if self._total_frames > 0:
                                self._set_progress_percent(
                                    (self._processed_frames * 100) / self._total_frames
                                )
                    elif key == "speed":
                        with suppress(ValueError):
                            self._time_rate = max(0.1, float(value.strip("x")))
                    elif key in {"out_time", "out_time_us", "out_time_ms"}:
                        with suppress(ValueError):
                            processed_time = self._parse_progress_time(key, value)
                            if processed_time is None:
                                continue
                            self._processed_time = (
                                processed_time + self._last_processed_time
                            )
                        if self._total_time > 0:
                            eta = (
                                self._total_time - self._processed_time
                            ) / self._time_rate
                            self._set_progress_percent(
                                (self._processed_time * 100) / self._total_time,
                                eta=eta,
                            )
                        else:
                            if self._progress_raw <= 0:
                                self._progress_raw = 0
                                self._eta_raw = 0
                    elif key == "progress" and not self._progress_keys_logged:
                        self._progress_keys_logged = True
                        LOGGER.info(
                            "FFmpeg progress keys: "
                            f"{', '.join(sorted(self._progress_keys))}; "
                            f"duration={self._total_time}; frames={self._total_frames}"
                        )
            await sleep(0.05)

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        self._total_time = (await get_media_info(f_path))[0]
        base_name, ext = ospath.splitext(f_path)
        dir, base_name = base_name.rsplit("/", 1)
        indices = [
            index
            for index, item in enumerate(ffmpeg)
            if item.startswith("mltb") or item == "mltb"
        ]
        outputs = []
        for index in indices:
            output_file = ffmpeg[index]
            if output_file != "mltb" and output_file.startswith("mltb"):
                bo, oext = ospath.splitext(output_file)
                if oext:
                    if ext == oext:
                        prefix = f"ffmpeg{index}." if bo == "mltb" else ""
                    else:
                        prefix = ""
                    ext = ""
                else:
                    prefix = ""
            else:
                prefix = f"ffmpeg{index}."
            output = f"{dir}/{prefix}{output_file.replace('mltb', base_name)}{ext}"
            outputs.append(output)
            ffmpeg[index] = output
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return outputs
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while running ffmpeg cmd, mostly file requires different/specific arguments. Path: {f_path}"
            )
            for op in outputs:
                if await aiopath.exists(op):
                    await remove(op)
            return False

    async def encode_video(self, input_file, profile, metadata=None):
        self.clear()
        self._total_time = (await get_media_info(input_file))[0]
        self._total_frames = await get_video_frame_count(input_file, self._total_time)
        v_codec = profile.get("video_codec", "libsvtav1")
        a_codec = profile.get("audio_codec", "libopus")
        v_params = profile.get("video_params", {})
        a_params = profile.get("audio_params", {})
        sub_mode = profile.get("subtitle_mode", "copy")

        output_file = get_encode_output_path(input_file, v_codec)

        # Merge profile metadata with task-specific metadata (task metadata overrides profile)
        prof_meta = profile.get("metadata", {})
        enc_meta = {**prof_meta, **(metadata or {})}

        rename_pattern = profile.get("rename", "")
        if rename_pattern:
            enc_meta["__internal_rename__"] = rename_pattern

        if enc_meta:
            from ..ext_utils.metadata_utils import MetadataProcessor
            processor = MetadataProcessor()
            enc_meta = await processor.process(enc_meta, input_file)
            
        if "__internal_rename__" in enc_meta:
            new_name = enc_meta.pop("__internal_rename__")
            if new_name:
                import os
                ext = os.path.splitext(output_file)[1]
                if not os.path.splitext(new_name)[1]:
                    new_name += ext
                dirpath = os.path.dirname(output_file)
                output_file = f"{dirpath}/{new_name}"

        v_track = enc_meta.pop("v_track", "0")
        a_track = enc_meta.pop("a_track", "?")
        s_track = enc_meta.pop("s_track", "?")

        # Download and inject custom cover image if present
        custom_thumb_path = None
        original_thumb = getattr(self._listener, "thumb", None)
        cover_url = profile.get("cover_image", "").strip()
        if (
            cover_url
            and getattr(self._listener, "_encode_cover_thumb", None)
            == original_thumb
        ):
            custom_thumb_path = None
        elif cover_url:
            custom_thumb_path = await download_custom_thumb(cover_url)
            if custom_thumb_path:
                self._listener.thumb = custom_thumb_path

        cmd = [
            "taskset", "-c", f"{cores}",
            BinConfig.FFMPEG_NAME,
            "-hide_banner", "-loglevel", "error", "-progress", "pipe:1",
            "-i", input_file,
        ]

        is_mkv = output_file.lower().endswith(('.mkv', '.mka'))

        if not is_mkv and hasattr(self._listener, "thumb") and self._listener.thumb:
            cmd.extend(["-i", self._listener.thumb])

        def add_map_flags(cmd_list, track_type, track_str):
            for t in str(track_str).split(","):
                t = t.strip()
                if not t:
                    continue
                if t in ["?", "*", "all"]:
                    cmd_list.extend(["-map", f"0:{track_type}?"])
                else:
                    opt = "" if t.endswith("?") else "?"
                    cmd_list.extend(["-map", f"0:{track_type}:{t}{opt}"])

        add_map_flags(cmd, "v", v_track)
        add_map_flags(cmd, "a", a_track)
        cmd.extend(["-c:v", v_codec])

        if sub_mode == "copy":
            add_map_flags(cmd, "s", s_track)
            cmd.extend(["-c:s", "copy"])

        if is_mkv:
            cmd.extend(["-map", "0:t?", "-c:t", "copy"])

        if not is_mkv and hasattr(self._listener, "thumb") and self._listener.thumb:
            cmd.extend(["-map", "1", "-c:v:1", "copy", "-disposition:v:1", "attached_pic"])

        crf = v_params.get("crf", 30)
        preset = v_params.get("preset", 4)
        pix_fmt = v_params.get("pix_fmt", "yuv420p10le")

        if v_codec == "libsvtav1":
            svt_params = f"preset={preset}:crf={crf}"
            if v_params.get("profile") is not None:
                svt_params += f":profile={v_params['profile']}"
            if v_params.get("level"):
                lvl = str(v_params['level']).replace(".", "")
                svt_params += f":level={lvl}"
            if v_params.get("extra_params"):
                svt_params += f":{v_params['extra_params']}"
            cmd.extend(["-pix_fmt", pix_fmt, "-svtav1-params", svt_params])
        elif v_codec == "libx265":
            x265_params = f"crf={crf}:preset={preset}"
            cmd.extend(["-pix_fmt", pix_fmt, "-x265-params", x265_params])
        elif v_codec == "libx264":
            cmd.extend(["-pix_fmt", pix_fmt, "-crf", str(crf), "-preset", str(preset)])

        if v_codec != "libsvtav1":
            if v_params.get("profile") is not None and str(v_params["profile"]).strip():
                cmd.extend(["-profile:v", str(v_params["profile"])])
            if v_params.get("level") is not None and str(v_params["level"]).strip():
                cmd.extend(["-level:v", str(v_params["level"])])

        if v_params.get("color_primaries"):
            cmd.extend(["-color_primaries", str(v_params["color_primaries"])])
        if v_params.get("color_trc"):
            cmd.extend(["-color_trc", str(v_params["color_trc"])])
        if v_params.get("colorspace"):
            cmd.extend(["-colorspace", str(v_params["colorspace"])])

        cmd.extend(["-c:a", a_codec])
        if a_codec != "copy":
            if a_params.get("bitrate"):
                cmd.extend(["-b:a", a_params["bitrate"]])
            if a_params.get("channels"):
                cmd.extend(["-ac", str(a_params["channels"])])
            if a_params.get("vbr"):
                cmd.extend(["-vbr", "on"])

        if enc_meta:
            for k, v in enc_meta.items():
                k = k.strip()
                if ":" in k:
                    cmd.extend([f"-metadata:{k}", v])
                else:
                    cmd.extend(["-metadata", f"{k}={v}"])

        # Apply disposition flags from profile
        disposition = profile.get("disposition", {})
        if disposition:
            for stream_spec, disp_value in disposition.items():
                cmd.extend([f"-disposition:{stream_spec.strip()}", disp_value.strip()])

        temp_cover_dir = None
        temp_cover_path = None
        cmd.extend(["-threads", f"{threads}"])
        if is_mkv and hasattr(self._listener, "thumb") and self._listener.thumb:
            import aioshutil
            from time import time
            temp_cover_dir = f"{DOWNLOAD_DIR}temp_cover_{time()}"
            await makedirs(temp_cover_dir, exist_ok=True)
            temp_cover_path = ospath.join(temp_cover_dir, "cover.jpg")
            await aioshutil.copy(self._listener.thumb, temp_cover_path)
            cmd.extend([
                "-attach", temp_cover_path,
                "-metadata:s:m:filename:cover.jpg", "mimetype=image/jpeg"
            ])
        cmd.extend([output_file])

        if self._listener.is_cancelled:
            if custom_thumb_path:
                await remove(custom_thumb_path)
                self._listener.thumb = original_thumb
            if temp_cover_dir:
                from aioshutil import rmtree
                with suppress(Exception):
                    await rmtree(temp_cover_dir)
            return False

        self._listener.subproc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if temp_cover_dir:
            from aioshutil import rmtree
            with suppress(Exception):
                await rmtree(temp_cover_dir)

        if self._listener.is_cancelled:
            if custom_thumb_path:
                await remove(custom_thumb_path)
                self._listener.thumb = original_thumb
            return False
        if code == 0:
            if custom_thumb_path:
                await remove(custom_thumb_path)
                self._listener.thumb = original_thumb
            return output_file
        elif code == -9:
            self._listener.is_cancelled = True
            if custom_thumb_path:
                await remove(custom_thumb_path)
                self._listener.thumb = original_thumb
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(f"{stderr}. Error encoding video. Path: {input_file}")
            if await aiopath.exists(output_file):
                await remove(output_file)
            if custom_thumb_path:
                await remove(custom_thumb_path)
                self._listener.thumb = original_thumb
            return False

    async def convert_video(self, video_file, ext, retry=False):
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        # Phase 3.1 — use hardware-accelerated encoder when available.
        # Falls back to libx264 (software) if no hardware encoder detected.
        from ..ext_utils.hwaccel import get_best_hw_encoder
        hw_encoder = await get_best_hw_encoder()
        if retry:
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                hw_encoder,
                "-c:a",
                "aac",
            ]
            if ext == "mp4":
                cmd.extend(["-c:s", "mov_text"])
            elif ext == "mkv":
                cmd.extend(["-c:s", "ass"])
            else:
                cmd.extend(["-c:s", "copy"])
            cmd.extend(["-threads", f"{threads}", output])
        else:
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output):
                await remove(output)
            if not retry:
                return await self.convert_video(video_file, ext, True)
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        self.clear()
        self._total_time = (await get_media_info(audio_file))[0]
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
        cmd = [
            "taskset",
            "-c",
            f"{cores}",
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            audio_file,
            "-threads",
            f"{threads}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        self.clear()
        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        # Phase 3.1 — use hardware-accelerated encoder for sample video too.
        from ..ext_utils.hwaccel import get_best_hw_encoder
        hw_encoder = await get_best_hw_encoder()
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            filter_complex += (
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
            )
            filter_complex += (
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
            )

        for i in range(len(segments)):
            filter_complex += f"[v{i}][a{i}]"

        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

        cmd = [
            "taskset",
            "-c",
            f"{cores}",
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            hw_encoder,
            "-c:a",
            "aac",
            "-threads",
            f"{threads}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            return output_file
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while creating sample video, mostly file is corrupted. Path: {video_file}"
            )
            if await aiopath.exists(output_file):
                await remove(output_file)
            return False

    async def split(self, f_path, file_, parts, split_size):
        self.clear()
        multi_streams = True
        self._total_time = duration = (await get_media_info(f_path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 3000000
        start_time = 0
        i = 1
        while i <= parts or start_time < duration - 4:
            out_path = f_path.replace(file_, f"{base_name}.part{i:03}{extension}")
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
            ]
            if multi_streams:
                cmd.extend(["-map", "0"])
            cmd.extend(
                [
                    "-map_chapters",
                    "-1",
                    "-async",
                    "1",
                    "-strict",
                    "-2",
                    "-c",
                    "copy",
                    "-threads",
                    f"{threads}",
                    out_path,
                ]
            )
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if self._listener.is_cancelled:
                return False
            if code == -9:
                self._listener.is_cancelled = True
                return False
            elif code != 0:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"
                with suppress(Exception):
                    await remove(out_path)
                if multi_streams:
                    LOGGER.warning(
                        f"{stderr}. Retrying without map, -map 0 not working in all situations. Path: {f_path}"
                    )
                    multi_streams = False
                    continue
                else:
                    LOGGER.warning(
                        f"{stderr}. Unable to split this video, if it's size less than {self._listener.max_split_size} will be uploaded as it is. Path: {f_path}"
                    )
                return False
            out_size = await aiopath.getsize(out_path)
            if out_size > self._listener.max_split_size:
                split_size -= (out_size - self._listener.max_split_size) + 5000000
                LOGGER.warning(
                    f"Part size is {out_size}. Trying again with lower split size!. Path: {f_path}"
                )
                await remove(out_path)
                continue
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting, mostly file is corrupted. Path: {f_path}"
                )
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}"
                )
                break
            elif lpd <= 3:
                await remove(out_path)
                break
            self._last_processed_time += lpd
            self._last_processed_bytes += out_size
            start_time += lpd - 3
            i += 1
        return True


section_dict = {"General": "🗒", "Video": "🎞", "Audio": "🔊", "Text": "🔠", "Menu": "🗃"}

def _format_duration(seconds):
    with suppress(Exception):
        seconds = int(float(seconds))
        hours, rem = divmod(seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours} h {minutes} min {seconds} s"
        if minutes:
            return f"{minutes} min {seconds} s"
        return f"{seconds} s"
    return ""


def _format_file_size(size):
    with suppress(Exception):
        size = int(float(size))
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.2f} {unit}" if unit != "B" else f"{size} B"
            value /= 1024
    return ""


def _add_mediainfo_field(lines, label, value, suffix=""):
    if value is not None and value != "":
        lines.append(f"{label:<42}: {value}{suffix}")


async def _ffprobe_mediainfo_output(des_path, file_size):
    stdout, stderr, code = await cmd_exec(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            des_path,
        ]
    )
    if code != 0 or not stdout:
        raise RuntimeError(stderr or "ffprobe could not read media info")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe returned invalid media info: {e}") from e

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    lines = ["General"]
    _add_mediainfo_field(lines, "Complete name", ospath.basename(des_path))
    _add_mediainfo_field(lines, "Format", fmt.get("format_long_name") or fmt.get("format_name"))
    _add_mediainfo_field(lines, "File size", _format_file_size(file_size or fmt.get("size")))
    _add_mediainfo_field(lines, "Duration", _format_duration(fmt.get("duration")))
    _add_mediainfo_field(lines, "Overall bit rate", fmt.get("bit_rate"), " b/s")

    counts = {"video": 0, "audio": 0, "subtitle": 0}
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type not in counts:
            continue
        counts[codec_type] += 1
        section = {
            "video": "Video",
            "audio": "Audio",
            "subtitle": "Text",
        }[codec_type]
        lines.extend(["", section if counts[codec_type] == 1 else f"{section} #{counts[codec_type]}"])
        _add_mediainfo_field(lines, "ID", stream.get("index"))
        _add_mediainfo_field(lines, "Format", stream.get("codec_long_name") or stream.get("codec_name"))
        _add_mediainfo_field(lines, "Codec ID", stream.get("codec_tag_string"))
        _add_mediainfo_field(lines, "Duration", _format_duration(stream.get("duration")))
        _add_mediainfo_field(lines, "Bit rate", stream.get("bit_rate"), " b/s")
        if codec_type == "video":
            _add_mediainfo_field(lines, "Width", stream.get("width"), " pixels")
            _add_mediainfo_field(lines, "Height", stream.get("height"), " pixels")
            _add_mediainfo_field(lines, "Frame rate", stream.get("avg_frame_rate"))
            _add_mediainfo_field(lines, "Color space", stream.get("color_space"))
            _add_mediainfo_field(lines, "Chroma subsampling", stream.get("chroma_location"))
        elif codec_type == "audio":
            _add_mediainfo_field(lines, "Channel(s)", stream.get("channels"))
            _add_mediainfo_field(lines, "Channel layout", stream.get("channel_layout"))
            _add_mediainfo_field(lines, "Sampling rate", stream.get("sample_rate"), " Hz")
        tags = stream.get("tags") or {}
        _add_mediainfo_field(lines, "Language", tags.get("language"))
        _add_mediainfo_field(lines, "Title", tags.get("title") or tags.get("handler_name"))
    return "\n".join(lines)


async def get_mediainfo_text(des_path, file_size=0):
    if not des_path or not await aiopath.exists(des_path):
        raise FileNotFoundError(des_path or "media file")
    if which("mediainfo"):
        try:
            stdout, stderr, code = await cmd_exec(["mediainfo", des_path])
            if code == 0 and stdout:
                return stdout
            LOGGER.warning(
                f"mediainfo failed for {des_path}; falling back to ffprobe: {stderr}"
            )
        except FileNotFoundError:
            LOGGER.warning("mediainfo binary not found; falling back to ffprobe")
    return await _ffprobe_mediainfo_output(des_path, file_size)


def parseinfo(out, size):
    tc, trigger = "", False
    size_line = f"File size                                 : {size / (1024 * 1024):.2f} MiB" if size else None
    for line in out.split("\n"):
        for section, emoji in section_dict.items():
            if line.startswith(section):
                trigger = True
                if not line.startswith("General"):
                    tc += "</pre><br>"
                tc += f"<h4>{emoji} {line.replace('Text', 'Subtitle')}</h4>"
                break
        if size_line and line.startswith("File size"):
            line = size_line
        if trigger:
            tc += "<br><pre>"
            trigger = False
        else:
            tc += line + "\n"
    tc += "</pre><br>"
    return tc

async def generate_telegraph_mediainfo(des_path, file_size):
    from .telegraph_helper import telegraph
    if not des_path or not await aiopath.exists(des_path):
        return None
    try:
        tc = await generate_mediainfo_content(des_path, file_size)
        link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]
        return f"https://graph.org/{link_id}"
    except Exception as e:
        LOGGER.error(f"Failed to generate telegraph mediainfo: {e}")
    return None


async def generate_mediainfo_content(des_path, file_size=0):
    stdout = await get_mediainfo_text(des_path, file_size)
    tc = f"<h4>📌 {ospath.basename(des_path)}</h4><br><br>"
    if stdout:
        tc += parseinfo(stdout, file_size)
    return tc
