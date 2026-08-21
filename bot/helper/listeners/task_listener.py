from asyncio import gather, sleep, Event, wait_for
from html import escape
from time import time
from mimetypes import guess_type
from contextlib import suppress
from os import path as ospath
from pyrogram.enums import ButtonStyle

from aiofiles.os import listdir, remove, path as aiopath
from requests import utils as rutils
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.filters import regex

from ... import (
    intervals,
    task_dict,
    task_dict_lock,
    LOGGER,
    non_queued_up,
    non_queued_dl,
    queued_up,
    queued_dl,
    queue_dict_lock,
    same_directory_lock,
    DOWNLOAD_DIR,
    multi_tags,
)
from ...modules.metadata import apply_metadata_title
from ..common import TaskConfig
from ...core.tg_client import TgClient
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.bot_utils import get_web_secret, sync_to_async
from ..ext_utils.links_utils import encode_slink
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    clean_download,
    clean_target,
    create_recursive_symlink,
    get_path_size,
    join_files,
    remove_excluded_files,
    move_and_merge,
)
from ..ext_utils.links_utils import is_gdrive_id
from ..ext_utils.media_utils import download_custom_thumb
from ..ext_utils.multi_leech_utils import paginate_text_blocks
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..ext_utils.task_manager import check_running_tasks, start_from_queued
from ..mirror_leech_utils.uphoster_utils.multi_upload import MultiUphosterUpload
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.upload_utils.mega_upload import add_mega_upload
from ..mirror_leech_utils.status_utils.uphoster_status import UphosterStatus
from ..mirror_leech_utils.status_utils.gdrive_status import (
    GoogleDriveStatus,
)
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ..mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ..mirror_leech_utils.status_utils.yt_status import YtStatus
from ..mirror_leech_utils.upload_utils.telegram_uploader import TelegramUploader
from ..mirror_leech_utils.youtube_utils.youtube_upload import YouTubeUpload
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    delete_message,
    delete_status,
    send_message,
    update_status_message,
)
from web.security import make_route_token


def _stream_route_token(chat_id, message_id):
    return make_route_token(
        get_web_secret(),
        "stream",
        int(chat_id),
        int(message_id),
    )


def _premium_row(label, value, *, code=True, branch="├─"):
    rendered = f"<code>{value}</code>" if code else str(value)
    return f"{branch} <b>{label}</b> : {rendered}\n"


def _completion_header(title, task_name, icon):
    task_name = escape(str(task_name or "Unknown Task"))
    return (
        f"<b>✦ {title}</b>\n\n"
        f"╭─ {icon} <b>Task</b> : <b>{task_name}</b>\n"
    )


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()

    async def clean(self):
        with suppress(Exception):
            if st := intervals["status"]:
                for intvl in list(st.values()):
                    intvl.cancel()
            intervals["status"].clear()
            await gather(TorrentManager.aria2.purgeDownloadResult(), delete_status())

    def clear(self):
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    async def remove_from_same_dir(self):
        async with task_dict_lock:
            if (
                self.folder_name
                and self.same_dir
                and self.mid in self.same_dir[self.folder_name]["tasks"]
            ):
                self.same_dir[self.folder_name]["tasks"].remove(self.mid)
                self.same_dir[self.folder_name]["total"] -= 1

    async def send_processing(self):
        if self.processing_msg is not None or self.multi > 1:
            return
        with suppress(Exception):
            self.processing_msg = await send_message(
                self.message, "<b>Processing...</b>"
            )

    async def remove_processing(self):
        message = self.processing_msg
        self.processing_msg = None
        if message and not isinstance(message, str):
            with suppress(Exception):
                await delete_message(message)

    async def on_download_start(self):
        await self.remove_processing()
        mode_name = "Leech" if self.is_leech else "Mirror"
        if self.bot_pm and self.is_super_chat:
            self.pm_msg = await send_message(
                self.user_id,
                "<b>✦ TASK STARTED</b>\n\n"
                f"╰─ <b>Source</b> : "
                f"<code>{escape(str(self.source_url or 'N/A'))}</code>",
            )
        if Config.LINKS_LOG_ID:
            message_link = (
                f"<a href='{self.message.link}'>Open Message</a>"
                if self.message.link
                else "<code>N/A</code>"
            )
            await send_message(
                Config.LINKS_LOG_ID,
                f"<b>✦ {mode_name.upper()} STARTED</b>\n\n"
                f"╭─ <b>User</b> : {self.tag} : <code>{self.user_id}</code>\n"
                f"├─ <b>Message</b> : {message_link}\n"
                f"╰─ <b>Source</b> : "
                f"<code>{escape(str(self.source_url or 'N/A'))}</code>",
            )
        if (
            (Config.INCOMPLETE_TASK_NOTIFIER or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.add_incomplete_task(
                self.message.chat.id,
                self.message.link or f"pm:{self.user_id}:{self.message.id}",
                self.tag,
                user_id=self.user_id,
                command=self.message.text or "",
                reply_to_msg_id=(
                    self.message.reply_to_message.id
                    if self.message.reply_to_message
                    else 0
                ),
                name=self.name or "",
                is_pm=not self.is_super_chat,
            )

    async def _metadata_handler_cb(self, _, message):
        text_msg = message.text.strip()
        if text_msg.lower() != "skip":
            try:
                from ..ext_utils.metadata_utils import MetadataProcessor
                processor = MetadataProcessor()
                self.encode_metadata = processor.parse_string(text_msg)
            except Exception as e:
                LOGGER.error(f"Error parsing metadata: {e}")
        self.encode_event.set()

    async def _profile_callback_cb(self, _, query):
        if query.from_user.id != self.user_id:
            await query.answer("Not yours!", show_alert=True)
            return
        data = query.data.split()
        await query.answer()
        if data[2] == "cancel":
            self.encode_profile = None
            self.is_cancelled = True
            self.encode_event.set()
        elif data[2] == "sel":
            pid = data[3]
            if pid == "default":
                self.encode_profile = Config.DEFAULT_ENCODE_PRESET
            else:
                self.encode_profile = self._temp_profiles.get(pid)
            self.encode_event.set()



    async def _prompt_encode_profile(self):
        profiles = await database.get_encode_profiles(self.user_id) or {}
        if not isinstance(profiles, dict):
            LOGGER.warning("Ignoring malformed encoding profile collection")
            profiles = {}
        self._temp_profiles = profiles

        default_profile = Config.DEFAULT_ENCODE_PRESET or {}
        if not isinstance(default_profile, dict):
            default_profile = {}
        default_codec = str(default_profile.get("video_codec", "libx264")).lower()
        default_codec = {
            "libsvtav1": "SVT-AV1",
            "libx264": "H.264",
            "libx265": "HEVC",
            "libvpx-vp9": "VP9",
        }.get(default_codec, default_codec.upper())
        buttons = ButtonMaker()
        buttons.data_button(
            f"◆ DEFAULT : {default_codec}", f"enc {self.user_id} sel default"
        )

        for pid, pdata in profiles.items():
            if pid == "_id" or not isinstance(pdata, dict):
                continue
            name = str(pdata.get("name") or pid)
            if pdata.get("is_default"):
                name = f"⭐ {name}"
            buttons.data_button(name, f"enc {self.user_id} sel {pid}")

        buttons.data_button("✕ CANCEL", f"enc {self.user_id} cancel")
        reply_to = await send_message(
            self.message,
            "<b>✦ ENCODING PROFILE</b>\n"
            "<i>Select a profile for this task.</i>\n\n"
            "<b>Timeout</b> : <code>60s</code>",
            buttons.build_menu(2),
        )

        self.encode_event = Event()
        self.encode_profile = None

        handler = self.client.add_handler(
            CallbackQueryHandler(self._profile_callback_cb, filters=regex(f"^enc {self.user_id}")),
            group=-1,
        )
        try:
            await wait_for(self.encode_event.wait(), timeout=60)
        except Exception:
            user_default = None
            for pid, pdata in profiles.items():
                if (
                    pid != "_id"
                    and isinstance(pdata, dict)
                    and pdata.get("is_default")
                ):
                    user_default = pdata
                    break
            self.encode_profile = user_default or Config.DEFAULT_ENCODE_PRESET
        finally:
            self.client.remove_handler(*handler)
            await delete_message(reply_to)

    async def _handle_encode_pipeline(self, up_path, gid):
        if getattr(self, "encode_metadata", None) and isinstance(self.encode_metadata, str):
            from ..ext_utils.metadata_utils import MetadataProcessor
            processor = MetadataProcessor()
            self.encode_metadata = processor.parse_string(self.encode_metadata)
        else:
            self.encode_metadata = {}

        self.encode_profile = None
        if isinstance(self.is_encode, str) and self.is_encode.strip() and self.is_encode != "True":
            pid_search = self.is_encode.strip().lower()
            if pid_search == "default":
                self.encode_profile = Config.DEFAULT_ENCODE_PRESET
            else:
                profiles = await database.get_encode_profiles(self.user_id) or {}
                if not isinstance(profiles, dict):
                    profiles = {}
                for db_pid, pdata in profiles.items():
                    if db_pid == "_id" or not isinstance(pdata, dict):
                        continue
                    if db_pid.lower() == pid_search or str(
                        pdata.get("name", "")
                    ).lower() == pid_search:
                        self.encode_profile = pdata
                        break

        if not self.encode_profile:
            await self._prompt_encode_profile()

        if self.is_cancelled or not self.encode_profile:
            return None

        if self.is_leech and not self.thumb:
            cover_url = self.encode_profile.get("cover_image", "").strip()
            if cover_url:
                cover_thumb = await download_custom_thumb(cover_url)
                if cover_thumb:
                    self.thumb = cover_thumb
                    self._encode_cover_thumb = cover_thumb

        return await self.proceed_encode(up_path, gid)

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        multi_links = False
        if (
            self.folder_name
            and self.same_dir
            and self.mid in self.same_dir[self.folder_name]["tasks"]
        ):
            async with same_directory_lock:
                while True:
                    async with task_dict_lock:
                        if self.mid not in self.same_dir[self.folder_name]["tasks"]:
                            return
                        if (
                            self.same_dir[self.folder_name]["total"] <= 1
                            or len(self.same_dir[self.folder_name]["tasks"]) > 1
                        ):
                            if self.same_dir[self.folder_name]["total"] > 1:
                                self.same_dir[self.folder_name]["tasks"].remove(
                                    self.mid
                                )
                                self.same_dir[self.folder_name]["total"] -= 1
                                spath = f"{self.dir}{self.folder_name}"
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[
                                    0
                                ]
                                des_path = f"{DOWNLOAD_DIR}{des_id}{self.folder_name}"
                                LOGGER.info(f"Moving files from {self.mid} to {des_id}")
                                await move_and_merge(spath, des_path, self.mid)
                                multi_links = True
                            break
                    await sleep(1)
        async with task_dict_lock:
            if self.is_cancelled:
                return
            if self.mid not in task_dict:
                return
            download = task_dict[self.mid]
            self.name = download.name()
            gid = download.gid()
        LOGGER.info(f"Download completed: {self.name}")

        if not (self.is_torrent or self.is_qbit):
            self.seed = False

        if multi_links:
            self.seed = False
            await self.on_upload_error(
                f"{self.name} Downloaded!\n\nWaiting for other tasks to finish..."
            )
            return
        elif self.same_dir:
            self.seed = False

        if self.folder_name:
            self.name = self.folder_name.strip("/").split("/", 1)[0]

        if not await aiopath.exists(f"{self.dir}/{self.name}"):
            try:
                files = await listdir(self.dir)
                self.name = files[-1]
                if self.name == "yt-dlp-thumb":
                    self.name = files[0]
            except Exception as e:
                await self.on_upload_error(str(e))
                return

        dl_path = f"{self.dir}/{self.name}"
        self.size = await get_path_size(dl_path)
        self.is_file = await aiopath.isfile(dl_path)

        if self.seed:
            up_dir = self.up_dir = f"{self.dir}10000"
            up_path = f"{self.up_dir}/{self.name}"
            await create_recursive_symlink(self.dir, self.up_dir)
            LOGGER.info(f"Shortcut created: {dl_path} -> {up_path}")
        else:
            up_dir = self.dir
            up_path = dl_path

        await remove_excluded_files(self.up_dir or self.dir, self.excluded_extensions)

        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        if self.join and not self.is_file:
            await join_files(up_path)

        if self.extract and not self.is_nzb:
            up_path = await self.proceed_extract(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
            await remove_excluded_files(up_dir, self.excluded_extensions)

        if self.ffmpeg_cmds:
            up_path = await self.proceed_ffmpeg(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.is_encode:
            encode_result = await self._handle_encode_pipeline(up_path, gid)
            if self.is_cancelled:
                return
            if encode_result:
                up_path = encode_result
                self.is_file = await aiopath.isfile(up_path)
                self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
                self.size = await get_path_size(up_dir)
                self.clear()

        if (
            (hasattr(self, "metadata_dict") and self.metadata_dict)
            or (hasattr(self, "audio_metadata_dict") and self.audio_metadata_dict)
            or (hasattr(self, "video_metadata_dict") and self.video_metadata_dict)
        ):
            up_path = await apply_metadata_title(
                self,
                up_path,
                gid,
                getattr(self, "metadata_dict", {}),
                getattr(self, "audio_metadata_dict", {}),
                getattr(self, "video_metadata_dict", {}),
            )
            if self.is_cancelled:
                return

            self.name = up_path.replace(f"{up_dir.rstrip('/')}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_path)
            self.clear()

        if self.is_leech and self.is_file:
            fname = ospath.basename(up_path)
            self.file_details["filename"] = fname
            self.file_details["mime_type"] = (guess_type(fname))[
                0
            ] or "application/octet-stream"

        if self.name_swap:
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        if self.screen_shots:
            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.compress:
            up_path = await self.proceed_compress(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            if not up_path:
                await self.on_upload_error(f"Unable to zip: {self.name}")
                return
            self.is_file = await aiopath.isfile(up_path)
            self.clear()

        self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
        self.size = await get_path_size(up_dir)

        if self.is_leech and not self.compress:
            await self.proceed_split(up_path, gid)
            if self.is_cancelled:
                return
            self.clear()

        self.subproc = None

        add_to_queue, event = await check_running_tasks(self, "up")
        await start_from_queued()
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Upload: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = QueueStatus(self, gid, "Up")
            await event.wait()
            if self.is_cancelled:
                return
            LOGGER.info(f"Start from Queued/Upload: {self.name}")

        self.size = await get_path_size(up_dir)

        if self.is_yt:
            LOGGER.info(f"Up to yt Name: {self.name}")
            yt = YouTubeUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = YtStatus(self, yt, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(yt.upload),
            )
            del yt
        elif self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            tg = TelegramUploader(self, up_dir)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(self, tg, gid, "up", "hul" if tg._hu else "")
            await gather(
                update_status_message(self.message.chat.id),
                tg.upload(),
            )
            del tg
        elif self.is_uphoster:
            LOGGER.info(f"Uphoster Upload Name: {self.name}")
            uphoster_service = self.user_dict.get("UPHOSTER_SERVICE", "gofile")
            services = uphoster_service.split(",")
            ddl = MultiUphosterUpload(
                self, up_path, services, self.folder_name.strip("/")
            )
            async with task_dict_lock:
                task_dict[self.mid] = UphosterStatus(self, ddl, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                ddl.upload(),
            )
            del ddl
        elif is_gdrive_id(self.up_dest):
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            drive = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(drive.upload),
            )
            del drive
        elif self.up_dest == "mega:":
            LOGGER.info(f"Mega Upload Name: {self.name}")
            mega_email = self.user_dict.get("MEGA_EMAIL") or ""
            mega_password = self.user_dict.get("MEGA_PASSWORD") or ""
            await add_mega_upload(self, up_path, mega_email, mega_password, gid)
        else:
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            RCTransfer = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                RCTransfer.upload(up_path),
            )
            del RCTransfer
        return

    def _multi_leech_remaining(self):
        try:
            remaining = int(self.multi or 0)
        except (TypeError, ValueError):
            remaining = 0
        if remaining > 0:
            return remaining
        text = getattr(self.message, "text", "") or ""
        tokens = text.split("\n", 1)[0].split()
        with suppress(ValueError, IndexError, TypeError):
            index = tokens.index("-i")
            return max(1, int(tokens[index + 1]))
        return 1

    def _multi_leech_position(self):
        summary = getattr(self, "multi_leech_summary", None)
        if summary is None:
            return 1
        remaining = self._multi_leech_remaining()
        return max(1, summary.total - remaining + 1)

    async def _record_multi_leech_success(self, files, corrupted):
        summary = getattr(self, "multi_leech_summary", None)
        if summary is None:
            return None
        return await summary.record_success(
            self.mid,
            self._multi_leech_position(),
            self.name,
            self.size,
            files,
            corrupted,
            self.tag,
        )

    async def _record_multi_leech_failure(self, error):
        summary = getattr(self, "multi_leech_summary", None)
        if summary is None:
            return None
        return await summary.record_failure(
            self.mid,
            self._multi_leech_position(),
            self.name,
            error,
            self.tag,
        )

    def _multi_leech_file_block(self, index, link, name):
        is_pm = "pm" in link
        try:
            chat_id, msg_id = link.split("/")[-2:]
        except ValueError:
            return f"╰─ <b>FILE {index:02d}</b> : <a href='{link}'>{escape(name)}</a>\n\n"

        c_id = chat_id if is_pm else (
            f"-100{chat_id}" if chat_id.isdigit() else chat_id
        )
        file_actions = []
        if Config.BASE_URL:
            try:
                stream_token = _stream_route_token(c_id, msg_id)
            except (TypeError, ValueError):
                LOGGER.warning(
                    "Skipping FileToLink URL for non-numeric chat/message "
                    f"reference: {c_id}/{msg_id}"
                )
            else:
                base_url = Config.BASE_URL.rstrip("/")
                file_actions.extend(
                    (
                        ("Stream", f"<a href='{base_url}/watch/{stream_token}'>Online</a>"),
                        (
                            "Download",
                            f"<a href='{base_url}/dl/{stream_token}'>Direct Link</a>",
                        ),
                    )
                )
        if Config.MEDIA_STORE and (self.is_super_chat or Config.LEECH_DUMP_CHAT):
            flink = (
                f"https://t.me/{TgClient.BNAME}?start="
                f"{encode_slink('file' + c_id + '&&' + msg_id)}"
            )
            file_actions.extend(
                (
                    ("Get Media", f"<a href='{flink}'>Store Link</a>"),
                    (
                        "Share",
                        f"<a href='https://t.me/share/url?url={flink}'>Share Link</a>",
                    ),
                )
            )

        branch = "╭─" if file_actions else "╰─"
        block = (
            f"{branch} <b>FILE {index:02d}</b> : "
            f"<a href='{link}'>{escape(str(name))}</a>\n"
        )
        for action_index, (label, value) in enumerate(file_actions):
            block += _premium_row(
                label,
                value,
                code=False,
                branch="╰─" if action_index == len(file_actions) - 1 else "├─",
            )
        return block + "\n"

    async def _send_multi_leech_summary(self, snapshot):
        multi_tags.discard(self.multi_tag)
        header = _completion_header(
            "MULTI LEECH COMPLETE", f"{snapshot.total} leech tasks", "📤"
        )
        header += _premium_row("Completed Tasks", snapshot.succeeded)
        header += _premium_row("Failed Tasks", snapshot.failed)
        header += _premium_row("Total Files", len(snapshot.files))
        header += _premium_row(
            "Total Size", get_readable_file_size(snapshot.total_size)
        )
        if snapshot.corrupted:
            header += _premium_row("Corrupted Files", snapshot.corrupted)
        header += _premium_row("Time Taken", get_readable_time(snapshot.elapsed))
        header += _premium_row(
            "Task By", snapshot.tag or self.tag, code=False, branch="╰─"
        )

        blocks = []
        if snapshot.failures:
            blocks.append("\n<b>✦ FAILED TASKS</b>\n\n")
            for failure in snapshot.failures:
                task_name = escape(failure.name[:200])
                error = escape(failure.error[:300])
                blocks.append(
                    f"╭─ <b>TASK {failure.position:02d}</b> : <code>{task_name}</code>\n"
                    f"╰─ <b>Reason</b> : <i>{error}</i>\n\n"
                )

        blocks.append("\n<b>✦ FILES LIST</b>\n\n")
        if not snapshot.files:
            blocks.append("╰─ <i>No files were uploaded successfully.</i>\n")
        for index, item in enumerate(snapshot.files, start=1):
            blocks.append(self._multi_leech_file_block(index, item.link, item.name))

        pages = paginate_text_blocks(
            header,
            blocks,
            "<b>✦ MULTI LEECH COMPLETE — CONTINUED</b>\n\n",
        )

        target = self.user_id if self.bot_pm else getattr(
            self.multi_leech_summary, "anchor_message", self.message
        )
        for page_index, page in enumerate(pages):
            await send_message(target, page)
            if page_index < len(pages) - 1:
                await sleep(1)

        if self.bot_pm and self.is_super_chat:
            await send_message(
                getattr(self.multi_leech_summary, "anchor_message", self.message),
                (
                    "<b>✦ MULTI LEECH COMPLETE</b>\n\n"
                    f"╭─ <b>Completed Tasks</b> : <code>{snapshot.succeeded}</code>\n"
                    f"├─ <b>Failed Tasks</b> : <code>{snapshot.failed}</code>\n"
                    "╰─ <b>Result</b> : <i>File list has been sent to User PM</i>\n"
                ),
            )

    async def on_multi_leech_task_error(self, error, abort_remaining=False):
        snapshot = await self._record_multi_leech_failure(error)
        summary = getattr(self, "multi_leech_summary", None)
        if abort_remaining and summary is not None:
            remaining = self._multi_leech_remaining()
            unstarted_snapshot = await summary.record_unstarted(
                remaining - 1,
                self._multi_leech_position() + 1,
                "The multi-leech chain stopped before this item started.",
                self.tag,
            )
            snapshot = snapshot or unstarted_snapshot
        if snapshot is not None:
            await self._send_multi_leech_summary(snapshot)

    async def on_upload_complete(
        self, link, files, folders, mime_type, rclone_path="", dir_id=""
    ):
        if (
            (Config.INCOMPLETE_TASK_NOTIFIER or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(
                self.message.link or f"pm:{self.user_id}:{self.message.id}"
            )
        if self.is_yt:
            completion_title, completion_icon = "YOUTUBE UPLOAD COMPLETE", "▶"
        elif self.is_leech:
            completion_title, completion_icon = "LEECH COMPLETE", "📤"
        else:
            completion_title, completion_icon = "UPLOAD COMPLETE", "☁"
        msg = _completion_header(completion_title, self.name, completion_icon)
        msg += _premium_row("Task Size", get_readable_file_size(self.size))
        msg += _premium_row(
            "Time Taken",
            get_readable_time(time() - self.message.date.timestamp()),
        )
        msg += _premium_row("In Mode", self.mode[0], code=False)
        msg += _premium_row("Out Mode", self.mode[1], code=False)
        LOGGER.info(f"Task Done: {self.name}")
        if self.is_yt:
            buttons = ButtonMaker()
            if mime_type == "Folder/Playlist":
                msg += _premium_row("Type", "Playlist")
                msg += _premium_row("Total Videos", files)
                if link:
                    buttons.url_button(
                        "🔗 View Playlist", link, style=ButtonStyle.PRIMARY
                    )
                result = (
                    f"Playlist with {files} videos uploaded to YouTube successfully"
                )
            else:
                msg += _premium_row("Type", "Video")
                if link:
                    buttons.url_button("🔗 View Video", link, style=ButtonStyle.PRIMARY)
                result = "Video uploaded to YouTube successfully"

            msg += _premium_row("Task By", self.tag, code=False, branch="╰─")
            user_message = (
                "<b>✦ YOUTUBE UPLOAD COMPLETE</b>\n\n"
                f"╭─ <b>Result</b> : <i>{result}</i>\n"
                f"╰─ <b>Task By</b> : {self.tag}"
            )

            button = buttons.build_menu(1) if link else None

            await send_message(self.user_id, msg, button, photo=self.thumb or "IMAGES")
            if Config.LEECH_DUMP_CHAT:
                try:
                    dump_chat = int(Config.LEECH_DUMP_CHAT)
                except (ValueError, TypeError):
                    dump_chat = Config.LEECH_DUMP_CHAT
                await send_message(dump_chat, msg, button, photo=self.thumb or "IMAGES")
            await send_message(self.message, user_message, button, photo=self.thumb or "IMAGES")

        elif self.is_leech:
            msg += _premium_row("Total Files", folders)
            if mime_type != 0:
                msg += _premium_row("Corrupted Files", mime_type)
            msg += _premium_row("Task By", self.tag, code=False, branch="╰─")
            msg += "\n"
            multi_leech_summary = getattr(self, "multi_leech_summary", None)
            multi_snapshot = None
            if multi_leech_summary is not None:
                multi_snapshot = await self._record_multi_leech_success(
                    files, mime_type
                )

            if multi_leech_summary is None and self.bot_pm:
                pmsg = msg
                pmsg += "<b>✦ ACTION PERFORMED</b>\n\n"
                pmsg += (
                    "╰─ <b>Result</b> : "
                    "<i>File(s) have been sent to User PM</i>\n"
                )
                if self.is_super_chat:
                    await send_message(self.message, pmsg)

            if multi_leech_summary is not None:
                if multi_snapshot is not None:
                    await self._send_multi_leech_summary(multi_snapshot)
            elif not files and not self.is_super_chat:
                await send_message(self.message, msg, photo=self.thumb or "IMAGES")
            else:
                log_chat = self.user_id if self.bot_pm else self.message
                msg += "<b>✦ FILES LIST</b>\n\n"
                fmsg = ""
                for index, (link, name) in enumerate(files.items(), start=1):
                    is_pm = "pm" in link
                    chat_id, msg_id = link.split("/")[-2:]
                    file_actions = []

                    c_id = chat_id if is_pm else (f"-100{chat_id}" if chat_id.isdigit() else chat_id)
                    
                    if Config.BASE_URL:
                        try:
                            stream_token = _stream_route_token(c_id, msg_id)
                        except (TypeError, ValueError):
                            LOGGER.warning(
                                "Skipping FileToLink URL for non-numeric chat/message "
                                f"reference: {c_id}/{msg_id}"
                            )
                        else:
                            base_url = Config.BASE_URL.rstrip("/")
                            stream_link = f"{base_url}/watch/{stream_token}"
                            download_link = f"{base_url}/dl/{stream_token}"
                            file_actions.extend(
                                (
                                    (
                                        "Stream",
                                        f"<a href='{stream_link}'>Online</a>",
                                    ),
                                    (
                                        "Download",
                                        f"<a href='{download_link}'>Direct Link</a>",
                                    ),
                                )
                            )
                        
                    if Config.MEDIA_STORE and (
                        self.is_super_chat or Config.LEECH_DUMP_CHAT
                    ):
                        flink = f"https://t.me/{TgClient.BNAME}?start={encode_slink('file' + c_id + '&&' + msg_id)}"
                        file_actions.extend(
                            (
                                (
                                    "Get Media",
                                    f"<a href='{flink}'>Store Link</a>",
                                ),
                                (
                                    "Share",
                                    "<a href='https://t.me/share/url?"
                                    f"url={flink}'>Share Link</a>",
                                ),
                            )
                        )
                    task_branch = "╭─" if file_actions else "╰─"
                    fmsg += (
                        f"{task_branch} <b>FILE {index:02d}</b> : "
                        f"<a href='{link}'>{escape(str(name))}</a>\n"
                    )
                    for action_index, (label, value) in enumerate(file_actions):
                        branch = (
                            "╰─"
                            if action_index == len(file_actions) - 1
                            else "├─"
                        )
                        fmsg += _premium_row(
                            label,
                            value,
                            code=False,
                            branch=branch,
                        )
                    fmsg += "\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        await send_message(log_chat, msg + fmsg, photo=self.thumb or "IMAGES")
                        await sleep(1)
                        fmsg = ""
                if fmsg != "":
                    await send_message(log_chat, msg + fmsg)
        else:
            msg += _premium_row("Type", escape(str(mime_type)))
            if mime_type == "Folder":
                msg += _premium_row("SubFolders", folders)
                msg += _premium_row("Files", files)

            multi_link_msg = ""
            multi_links = []
            if isinstance(link, dict) and not self.is_yt:
                for service, result in link.items():
                    if "error" in result:
                        multi_link_msg += (
                            f"{service.capitalize()}: Error - {result['error']}\n"
                        )
                    elif result.get("link"):
                        multi_links.append(
                            (f"{service.capitalize()} Link", result["link"])
                        )
                multi_link_msg = multi_link_msg.strip()
                link = None

            if (
                link
                or rclone_path
                and Config.RCLONE_SERVE_URL
                and not self.private_link
                or multi_links
            ):
                buttons = ButtonMaker()
                if link and Config.SHOW_CLOUD_LINK:
                    if "mega.nz" in link:
                        btn_label = "🔗 Mega Link"
                    else:
                        btn_label = "☁️ Cloud Link"
                    buttons.url_button(btn_label, link, style=ButtonStyle.PRIMARY)
                elif multi_links:
                    for name, url in multi_links:
                        buttons.url_button(name, url)
                else:
                    msg += _premium_row("Path", escape(rclone_path))
                if rclone_path and Config.RCLONE_SERVE_URL and not self.private_link:
                    remote, rpath = rclone_path.split(":", 1)
                    url_path = rutils.quote(f"{rpath}")
                    share_url = f"{Config.RCLONE_SERVE_URL}/{remote}/{url_path}"
                    if mime_type == "Folder":
                        share_url += "/"
                    buttons.url_button(
                        "🔗 Rclone Link", share_url, style=ButtonStyle.PRIMARY
                    )
                if not rclone_path and dir_id:
                    INDEX_URL = self.user_dict.get("INDEX_URL", "") or ""
                    if not INDEX_URL:
                        INDEX_URL = Config.INDEX_URL or ""
                    if INDEX_URL and self.name:
                        safe_name = rutils.quote(self.name.strip("/"))
                        share_url = f"{INDEX_URL}/{safe_name}"
                        if mime_type == "Folder":
                            share_url += "/"
                        buttons.url_button(
                            "⚡ Index Link", share_url, style=ButtonStyle.PRIMARY
                        )
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{share_url}?a=view"
                            buttons.url_button(
                                "🌐 View Link", share_urls, style=ButtonStyle.PRIMARY
                            )
                button = buttons.build_menu(2)
            else:
                if not multi_link_msg and rclone_path:
                    msg += _premium_row("Path", escape(rclone_path))
                button = None
            msg += _premium_row("Task By", self.tag, code=False, branch="╰─")
            msg += "\n"
            group_msg = (
                msg
                + "<b>✦ ACTION PERFORMED</b>\n\n"
                "╰─ <b>Result</b> : "
                "<i>Cloud link(s) have been sent to User PM</i>\n"
            )

            if multi_link_msg:
                group_msg += multi_link_msg + "\n"
                msg += multi_link_msg + "\n"

            if self.bot_pm and self.is_super_chat:
                await send_message(self.user_id, msg, button, photo=self.thumb or "IMAGES")

            if hasattr(Config, "MIRROR_LOG_ID") and Config.MIRROR_LOG_ID:
                await send_message(Config.MIRROR_LOG_ID, msg, button, photo=self.thumb or "IMAGES")

            await send_message(self.message, group_msg, button, photo=self.thumb or "IMAGES")
        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if self.pm_msg and not Config.DELETE_LINKS:
            await delete_message(self.pm_msg)

        await clean_download(self.dir)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        async with queue_dict_lock:
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()

    async def on_download_error(self, error, button=None, is_limit=False):
        await self.remove_processing()
        multi_snapshot = await self._record_multi_leech_failure(error)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await self.remove_from_same_dir()
        msg = (
            (
                _completion_header("LIMIT BREACHED", self.name, "!")
                + _premium_row("Task Size", get_readable_file_size(self.size))
                + _premium_row("In Mode", self.mode[0], code=False)
                + _premium_row("Out Mode", self.mode[1], code=False)
                + _premium_row(
                    "Details",
                    escape(str(error)),
                    branch="╰─",
                )
            )
            if is_limit
            else (
                _completion_header("DOWNLOAD STOPPED", self.name, "■")
                + _premium_row("Due To", escape(str(error)))
                + _premium_row("Task Size", get_readable_file_size(self.size))
                + _premium_row(
                    "Time Taken",
                    get_readable_time(time() - self.message.date.timestamp()),
                )
                + _premium_row("In Mode", self.mode[0], code=False)
                + _premium_row("Out Mode", self.mode[1], code=False)
                + _premium_row(
                    "Task By",
                    self.tag,
                    code=False,
                    branch="╰─",
                )
            )
        )

        await send_message(self.message, msg, button)
        if multi_snapshot is not None:
            await self._send_multi_leech_summary(multi_snapshot)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            (Config.INCOMPLETE_TASK_NOTIFIER or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
            and not intervals.get("stopAll")
        ):
            await database.rm_complete_task(
                self.message.link or f"pm:{self.user_id}:{self.message.id}"
            )

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

    async def on_upload_error(self, error):
        await self.remove_processing()
        multi_snapshot = await self._record_multi_leech_failure(error)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        msg = (
            _completion_header("UPLOAD STOPPED", self.name, "■")
            + _premium_row("Due To", escape(str(error)))
            + _premium_row("Task Size", get_readable_file_size(self.size))
            + _premium_row(
                "Time Taken",
                get_readable_time(time() - self.message.date.timestamp()),
            )
            + _premium_row("In Mode", self.mode[0], code=False)
            + _premium_row("Out Mode", self.mode[1], code=False)
            + _premium_row(
                "Task By",
                self.tag,
                code=False,
                branch="╰─",
            )
        )
        await send_message(self.message, msg)
        if multi_snapshot is not None:
            await self._send_multi_leech_summary(multi_snapshot)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            (Config.INCOMPLETE_TASK_NOTIFIER or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
            and not intervals.get("stopAll")
        ):
            await database.rm_complete_task(
                self.message.link or f"pm:{self.user_id}:{self.message.id}"
            )

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

