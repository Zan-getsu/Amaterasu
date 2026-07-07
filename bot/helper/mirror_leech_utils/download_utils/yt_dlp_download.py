from logging import getLogger
from mimetypes import guess_extension
from os import path as ospath, listdir, replace
from re import search as re_search
from contextlib import suppress
from secrets import token_hex
from zipfile import ZipFile, is_zipfile
from asyncio import sleep
from yt_dlp import YoutubeDL, DownloadError
from yt_dlp.networking.impersonate import ImpersonateTarget

from .... import task_dict_lock, task_dict
from ....core.config_manager import BinConfig, Config
from ...ext_utils.bot_utils import sync_to_async, async_to_sync, get_content_info
from ...ext_utils.files_utils import get_mime_type
from ...ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
    limit_checker,
)
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...telegram_helper.message_utils import send_status_message
from ..status_utils.yt_dlp_status import YtDlpStatus

LOGGER = getLogger(__name__)


def _bin_path(name):
    return name if ospath.isabs(name) else f"/bin/{name}"


def format_ytdlp_error(error, link=""):
    error = str(error).replace("<", " ").replace(">", " ")
    lower_error = error.lower()
    lower_link = (link or "").lower()

    if "cannot parse data" in lower_error and "facebook" in lower_link:
        return (
            "Facebook changed the page data that yt-dlp reads, so this video "
            "could not be parsed by the current extractor. Update/rebuild yt-dlp, "
            "refresh cookies.txt, try the original facebook.com video URL instead "
            "of a share URL, or move the deployment to a yt-dlp nightly/pre-release "
            "build if stable still fails."
        )

    return error


class MyLogger:
    def __init__(self, obj, listener):
        self._obj = obj
        self._listener = listener

    def debug(self, msg):
        # Hack to fix changing extension
        if not self._obj.is_playlist:
            if match := re_search(
                r".Merger..Merging formats into..(.*?).$", msg
            ) or re_search(r".ExtractAudio..Destination..(.*?)$", msg):
                LOGGER.info(msg)
                newname = match.group(1)
                newname = newname.rsplit("/", 1)[-1]
                self._listener.name = newname

    @staticmethod
    def warning(msg):
        LOGGER.warning(msg)

    @staticmethod
    def error(msg):
        if msg != "ERROR: Cancelling...":
            LOGGER.error(msg)


class YoutubeDLHelper:
    def __init__(self, listener):
        self._last_downloaded = 0
        self._progress = 0
        self._downloaded_bytes = 0
        self._download_speed = 0
        self._eta = "-"
        self._listener = listener
        self._active = False
        self._gid = ""
        self._ext = ""
        self.is_playlist = False
        self.keep_thumb = False
        self.extra_postprocess = True
        self.playlist_count = 0
        self.opts = {
            "progress_hooks": [self._on_download_progress],
            "logger": MyLogger(self, self._listener),
            "usenetrc": True,
            "allow_multiple_video_streams": True,
            "allow_multiple_audio_streams": True,
            "noprogress": True,
            "allow_playlist_files": True,
            "overwrites": True,
            "writethumbnail": True,
            "trim_file_name": 220,
            "ffmpeg_location": _bin_path(BinConfig.FFMPEG_NAME),
            "concurrent_fragments": 8,
            "impersonate": ImpersonateTarget.from_str("chrome"),
            "socket_timeout": 30,
            "downloader": {
                "http": _bin_path(BinConfig.ARIA2_NAME),
                "https": _bin_path(BinConfig.ARIA2_NAME),
            },
            "downloader_args": {
                BinConfig.ARIA2_NAME: [
                    "-x16", "-k1M", "-s16",
                    "--max-tries=5", "--retry-wait=3",
                ],
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["mweb"],
                    "skip": ["webpage", "configs"],
                },
                "youtubetab": {"skip": ["webpage"]},
            },
            "hls_use_mpegts": True,
            "fragment_retries": 10,
            "retries": 10,
            "retry_sleep_functions": {
                "http": lambda n: min(2 ** n, 30),
                "fragment": lambda n: min(2 ** n, 30),
                "file_access": lambda n: 3,
                "extractor": lambda n: min(2 ** n, 30),
            },
            "sleep_interval": 3,
            "max_sleep_interval": 8,
            "sleep_interval_requests": 1,
        }
        cookie_to_use = (
            usr_cookie
            if not self._listener.user_dict.get("USE_DEFAULT_COOKIE", False)
            and (usr_cookie := self._listener.user_dict.get("USER_COOKIE_FILE", ""))
            and ospath.exists(usr_cookie)
            else "cookies.txt"
        )
        self.opts["cookiefile"] = cookie_to_use
        LOGGER.info(
            f"Using cookies.txt file: {cookie_to_use} | User ID : {self._listener.user_id}"
        )

    @property
    def download_speed(self):
        return self._download_speed

    @property
    def downloaded_bytes(self):
        return self._downloaded_bytes

    @property
    def size(self):
        return self._listener.size

    @property
    def progress(self):
        return self._progress

    @property
    def eta(self):
        return self._eta

    def _on_download_progress(self, d):
        if self._listener.is_cancelled:
            raise ValueError("Cancelling...")
        if d["status"] == "finished":
            if self.is_playlist:
                self._last_downloaded = 0
        elif d["status"] == "downloading":
            self._download_speed = d["speed"] or 0
            if self.is_playlist:
                downloadedBytes = d["downloaded_bytes"] or 0
                chunk_size = downloadedBytes - self._last_downloaded
                self._last_downloaded = downloadedBytes
                self._downloaded_bytes += chunk_size
            else:
                if d.get("total_bytes"):
                    self._listener.size = d["total_bytes"] or 0
                elif d.get("total_bytes_estimate"):
                    self._listener.size = d["total_bytes_estimate"] or 0
                self._downloaded_bytes = d["downloaded_bytes"] or 0
                self._eta = d.get("eta", "-") or "-"
            try:
                self._progress = (self._downloaded_bytes / self._listener.size) * 100
            except ZeroDivisionError:
                pass

    async def _on_download_start(self, from_queue=False):
        async with task_dict_lock:
            task_dict[self._listener.mid] = YtDlpStatus(self._listener, self, self._gid)
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1:
                await send_status_message(self._listener.message)

    def _on_download_error(self, error):
        self._listener.is_cancelled = True
        async_to_sync(
            self._listener.on_download_error,
            format_ytdlp_error(error, self._listener.link),
        )

    @staticmethod
    def _valid_filename(name):
        return bool(name and "." in name and not name.endswith(".unknown_video"))

    @staticmethod
    def _is_apk_file(file_path):
        try:
            if not is_zipfile(file_path):
                return False
            with ZipFile(file_path) as archive:
                return "AndroidManifest.xml" in archive.namelist()
        except Exception:
            return False

    def _extension_from_file(self, file_path):
        if self._is_apk_file(file_path):
            return ".apk"

        mime_type = get_mime_type(file_path)
        known_extensions = {
            "application/vnd.android.package-archive": ".apk",
            "application/zip": ".zip",
            "application/x-zip": ".zip",
            "application/x-zip-compressed": ".zip",
            "application/x-7z-compressed": ".7z",
            "application/x-rar": ".rar",
            "application/x-rar-compressed": ".rar",
            "application/vnd.rar": ".rar",
            "application/gzip": ".gz",
            "application/x-gzip": ".gz",
            "application/x-bzip2": ".bz2",
            "application/x-xz": ".xz",
            "application/x-tar": ".tar",
            "application/x-gtar": ".tar",
            "application/zstd": ".zst",
            "application/x-zstd": ".zst",
            "application/x-iso9660-image": ".iso",
            "application/vnd.debian.binary-package": ".deb",
            "application/x-debian-package": ".deb",
            "application/x-rpm": ".rpm",
            "application/x-msdownload": ".exe",
            "application/vnd.microsoft.portable-executable": ".exe",
            "application/pdf": ".pdf",
            "application/epub+zip": ".epub",
        }
        ext = known_extensions.get(mime_type) or guess_extension(mime_type)
        if ext == ".jpe":
            ext = ".jpg"
        return ext or ""

    @staticmethod
    def _unique_path(path, filename):
        base_name, ext = ospath.splitext(filename)
        target = f"{path}/{filename}"
        suffix = 1
        while ospath.exists(target):
            filename = f"{base_name}.{suffix}{ext}"
            target = f"{path}/{filename}"
            suffix += 1
        return target, filename

    def _repair_unknown_video_name(self, path):
        if self.is_playlist or self.extra_postprocess:
            return

        filename = self._listener.name.rsplit("/", 1)[-1]
        file_path = f"{path}/{filename}"
        if not filename.endswith(".unknown_video") or not ospath.isfile(file_path):
            filename = next(
                (
                    file_
                    for file_ in listdir(path)
                    if file_.endswith(".unknown_video")
                    and ospath.isfile(f"{path}/{file_}")
                ),
                "",
            )
            if not filename:
                return
            file_path = f"{path}/{filename}"

        repaired_name = getattr(self._listener, "ytdlp_fallback_name", "")
        if not self._valid_filename(repaired_name):
            with suppress(Exception):
                _, content_filename = async_to_sync(
                    get_content_info, self._listener.link
                )
                if self._valid_filename(content_filename):
                    repaired_name = content_filename

        if not self._valid_filename(repaired_name):
            base_name = filename[: -len(".unknown_video")]
            with suppress(Exception):
                if ext := self._extension_from_file(file_path):
                    repaired_name = f"{base_name}{ext}"

        if not self._valid_filename(repaired_name):
            return

        target_path, repaired_name = self._unique_path(path, repaired_name)
        try:
            replace(file_path, target_path)
            self._listener.name = repaired_name
            self._ext = ospath.splitext(repaired_name)[-1]
            LOGGER.info(f"Renamed yt-dlp fallback file to: {repaired_name}")
        except Exception as e:
            LOGGER.warning(f"Unable to repair yt-dlp fallback filename: {e}")

    def _extract_meta_data(self):
        with YoutubeDL(self.opts) as ydl:
            try:
                result = ydl.extract_info(self._listener.link, download=False)
                if result is None:
                    raise ValueError("Info result is None")
            except Exception as e:
                return self._on_download_error(e)
            if self.is_playlist:
                self.playlist_count = result.get("playlist_count", 0)
            if "entries" in result:
                for entry in result["entries"]:
                    if not entry:
                        continue
                    elif "filesize_approx" in entry:
                        self._listener.size += entry.get("filesize_approx", 0) or 0
                    elif "filesize" in entry:
                        self._listener.size += entry.get("filesize", 0) or 0
                    if not self._listener.name:
                        outtmpl_ = "%(series,playlist_title,channel)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d.%(ext)s"
                        self._listener.name, ext = ospath.splitext(
                            ydl.prepare_filename(entry, outtmpl=outtmpl_)
                        )
                        if not self._ext:
                            self._ext = ext
            else:
                outtmpl_ = "%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s"
                realName = ydl.prepare_filename(result, outtmpl=outtmpl_)
                ext = ospath.splitext(realName)[-1]
                self._listener.name = (
                    f"{self._listener.name}{ext}" if self._listener.name else realName
                )
                if not self._ext:
                    self._ext = ext

    def _download(self, path):
        self._active = True
        try:
            with suppress(Exception):
                with YoutubeDL(self.opts) as ydl:
                    try:
                        ydl.download([self._listener.link])
                    except DownloadError as e:
                        if not self._listener.is_cancelled:
                            self._on_download_error(e)
                        return
                self._repair_unknown_video_name(path)
                if self.is_playlist and (
                    not ospath.exists(path) or len(listdir(path)) == 0
                ):
                    self._on_download_error(
                        "No video available to download from this playlist. Check logs for more details"
                    )
                    return
                if self._listener.is_cancelled:
                    return
                async_to_sync(self._listener.on_download_complete)
        finally:
            self._active = False
        return

    async def add_download(
        self, path, qual, playlist, options, extra_postprocess=True, forced_name=None
    ):
        self.extra_postprocess = extra_postprocess
        if playlist:
            self.opts["ignoreerrors"] = True
            self.is_playlist = True

        self._gid = token_hex(5)

        await self._on_download_start()

        self.opts["postprocessors"] = []
        # Phase 3.7 — playlist parallelism. yt-dlp downloads playlist
        # items sequentially, but we can parallelize fragment downloads
        # within each item by increasing concurrent_fragments. For true
        # per-item parallelism (downloading N videos at once), we'd need
        # to extract entries and download each via a separate aria2 task
        # — that's a larger refactor deferred to a future version.
        # For now, bump concurrent_fragments for playlists to improve
        # throughput on multi-fragment videos.
        if playlist:
            parallelism = min(6, max(1, int(getattr(Config, "PLAYLIST_PARALLELISM", 3) or 3)))
            self.opts["concurrent_fragments"] = max(8, parallelism * 4)
            LOGGER.info(
                f"yt-dlp playlist: concurrent_fragments={self.opts['concurrent_fragments']} "
                f"(PLAYLIST_PARALLELISM={parallelism})"
            )
        if extra_postprocess:
            self.opts["postprocessors"].append(
                {
                    "add_chapters": True,
                    "add_infojson": "if_exists",
                    "add_metadata": True,
                    "key": "FFmpegMetadata",
                }
            )
        else:
            self.opts["writethumbnail"] = False

        if qual.startswith("ba/b-"):
            audio_info = qual.split("-")
            qual = audio_info[0]
            audio_format = audio_info[1]
            rate = audio_info[2]
            self.opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": rate,
                }
            )
            if audio_format == "vorbis":
                self._ext = ".ogg"
            elif audio_format == "alac":
                self._ext = ".m4a"
            else:
                self._ext = f".{audio_format}"

        if not self._listener.is_leech or self._listener.thumbnail_layout:
            self.opts["writethumbnail"] = False

        if options:
            self._set_options(options)

        self.opts["format"] = qual

        await sync_to_async(self._extract_meta_data)
        if self._listener.is_cancelled:
            return
        if forced_name:
            self._listener.name = forced_name
            self._ext = ospath.splitext(forced_name)[-1]

        base_name, ext = ospath.splitext(self._listener.name)
        trim_name = self._listener.name if self.is_playlist else base_name
        if len(trim_name.encode()) > 200:
            self._listener.name = (
                self._listener.name[:200]
                if self.is_playlist
                else f"{base_name[:200]}{ext}"
            )
            base_name = ospath.splitext(self._listener.name)[0]

        start_path = path if self.keep_thumb else f"{path}/yt-dlp-thumb"
        if self.is_playlist:
            self.opts["outtmpl"] = {
                "default": f"{path}/{self._listener.name}/%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s",
                "thumbnail": f"{start_path}/%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s",
            }
        elif "download_ranges" in options:
            self.opts["outtmpl"] = {
                "default": f"{path}/{base_name}/%(section_number|)s%(section_number&.|)s%(section_title|)s%(section_title&-|)s%(title,fulltitle,alt_title)s %(section_start)s to %(section_end)s.%(ext)s",
                "thumbnail": f"{start_path}/%(section_number|)s%(section_number&.|)s%(section_title|)s%(section_title&-|)s%(title,fulltitle,alt_title)s %(section_start)s to %(section_end)s.%(ext)s",
            }
        elif any(
            key in options
            for key in [
                "writedescription",
                "writeinfojson",
                "writeannotations",
                "writedesktoplink",
                "writewebloclink",
                "writelink",
                "writeurllink",
                "writesubtitles",
                "write_all_thumbnails",
            ]
        ):
            self.opts["outtmpl"] = {
                "default": f"{path}/{base_name}/{self._listener.name}",
                "thumbnail": f"{start_path}/{base_name}.%(ext)s",
            }
        else:
            self.opts["outtmpl"] = {
                "default": f"{path}/{self._listener.name}",
                "thumbnail": f"{start_path}/{base_name}.%(ext)s",
            }

        if qual.startswith("ba/b"):
            self._listener.name = f"{base_name}{self._ext}"

        if self.opts["writethumbnail"] and extra_postprocess:
            self.opts["postprocessors"].append(
                {
                    "format": "jpg",
                    "key": "FFmpegThumbnailsConvertor",
                    "when": "before_dl",
                }
            )
        if extra_postprocess and self._ext in [
            ".mp3",
            ".mkv",
            ".mka",
            ".ogg",
            ".opus",
            ".flac",
            ".m4a",
            ".mp4",
            ".mov",
            ".m4v",
        ]:
            self.opts["postprocessors"].append(
                {
                    "already_have_thumbnail": self.opts["writethumbnail"],
                    "key": "EmbedThumbnail",
                }
            )

        msg, button = await stop_duplicate_check(self._listener)
        if msg:
            await self._listener.on_download_error(msg, button)
            return

        if limit_exceeded := await limit_checker(self._listener, self.playlist_count):
            await self._listener.on_download_error(limit_exceeded, is_limit=True)
            return

        add_to_queue, event = await check_running_tasks(self._listener)
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
            async with task_dict_lock:
                task_dict[self._listener.mid] = QueueStatus(
                    self._listener, self._gid, "dl"
                )
            await event.wait()
            if self._listener.is_cancelled:
                return
            LOGGER.info(f"Start Queued Download from YT_DLP: {self._listener.name}")
            await self._on_download_start(True)

        if not add_to_queue:
            LOGGER.info(f"Download with YT_DLP: {self._listener.name}")

        await sync_to_async(self._download, path)

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Download: {self._listener.name}")
        for _ in range(30):
            if not self._active:
                break
            await sleep(0.5)
        await self._listener.on_download_error("Stopped by User!")

    def _set_options(self, options):
        for key, value in options.items():
            if key == "postprocessors":
                if isinstance(value, list):
                    self.opts[key].extend(tuple(value))
                elif isinstance(value, dict):
                    self.opts[key].append(value)
            elif key == "download_ranges":
                if isinstance(value, list):
                    self.opts[key] = lambda info, ytdl: value
            else:
                if key == "writethumbnail" and value is True:
                    self.keep_thumb = True
                self.opts[key] = value
