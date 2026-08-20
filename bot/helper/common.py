import re
from asyncio import gather, sleep
from contextlib import suppress
from os import path as ospath
from os import walk
from re import sub
from secrets import token_hex
from shlex import split

from aiofiles.os import listdir, makedirs, remove
from aiofiles.os import path as aiopath
from aioshutil import move, rmtree
from pyrogram.enums import ChatAction, ChatType
from pyrogram.types import Message

from .. import (
    DOWNLOAD_DIR,
    LOGGER,
    categories_dict,
    cores,
    excluded_extensions,
    intervals,
    multi_tags,
    task_dict,
    task_dict_lock,
    user_data,
)
from ..core.config_manager import BinConfig, Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_lock import ff_lock
from .ext_utils.autorename_utils import apply_autorename_template
from .ext_utils.bot_utils import (
    fetch_drive_cat,
    get_size_bytes,
    get_valid_base_url,
    new_task,
    sync_to_async,
)
from .ext_utils.bulk_links import extract_bulk_links
from .ext_utils.files_utils import (
    SevenZ,
    get_base_name,
    get_path_size,
    is_archive,
    is_archive_split,
    is_first_archive_split,
    split_file,
)
from .ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_mega_link,
    is_rclone_path,
    is_telegram_link,
    is_terabox_link,
)
from .ext_utils.media_utils import (
    FFMpeg,
    create_thumb,
    download_image_thumb,
    get_document_type,
    take_ss,
)
from .ext_utils.metadata_utils import MetadataProcessor
from .ext_utils.telegram_destinations import (
    format_leech_dump_destination,
    normalize_named_leech_dumps,
    parse_leech_dump_destinations,
    select_named_leech_dumps,
)
from .mirror_leech_utils.gdrive_utils.list import GoogleDriveList
from .mirror_leech_utils.rclone_utils.list import RcloneList
from .mirror_leech_utils.status_utils.ffmpeg_status import FFmpegStatus
from .mirror_leech_utils.status_utils.sevenz_status import SevenZStatus
from .mirror_leech_utils.terabox_utils.list import TeraboxCookieSelector, TeraboxList
from .telegram_helper.bot_commands import BotCommands
from .telegram_helper.compat import get_user_mention
from .telegram_helper.message_utils import (
    get_tg_link_message,
    open_category_btns,
    open_leech_dump_btns,
    send_message,
    send_status_message,
)


class TaskConfig:
    def __init__(self):
        # Telegram message ids are only unique inside one chat.  Using the
        # bare message id here allowed simultaneous commands from different
        # chats to share a download directory and overwrite each other's
        # task_dict entry.
        self.message_id = self.message.id
        self.mid = f"{self.message.chat.id}_{self.message_id}"
        self.user = self.message.from_user or self.message.sender_chat
        self.user_id = self.user.id
        self.user_dict = user_data.get(self.user_id, {})
        # Phase 3.4 — task priority. Higher value = higher priority.
        # Owner/sudo can set priority via /setpriority inline button on
        # the task status message. Default 0. The queue dispatcher in
        # task_manager.py sorts pending tasks by priority DESC, then
        # added_at ASC. Normal users cannot change priority.
        self.priority = 0
        self.metadata_processor = MetadataProcessor()
        for k in ("METADATA", "AUDIO_METADATA", "VIDEO_METADATA", "SUBTITLE_METADATA"):
            v = self.user_dict.get(k, {})
            if k == "METADATA":
                k = "default_metadata"
            if isinstance(v, dict):
                setattr(self, f"{k.lower()}_dict", v)
            elif isinstance(v, str):
                setattr(
                    self, f"{k.lower()}_dict", self.metadata_processor.parse_string(v)
                )
            else:
                setattr(self, f"{k.lower()}_dict", {})
        self.dir = f"{DOWNLOAD_DIR}{self.mid}"
        self.up_dir = ""
        self.link = ""
        self.up_dest = ""
        self.drive_id = ""
        self.leech_dest = ""
        self.cmd_up_dest = ""
        self.selected_dumps = []
        self.user_dump_selection = ""
        self.leech_dump_context = {}
        self.rc_flags = ""
        self.tag = ""
        self.name = ""
        self.subname = ""
        self.category = ""
        self.index_link = ""
        self.name_swap = ""
        self.autorename_template = ""
        self.thumbnail_layout = ""
        self.folder_name = ""
        self.split_size = 0
        self.max_split_size = 0
        self.multi = 0
        self.size = 0
        self.subsize = 0
        self.proceed_count = 0
        self.is_leech = False
        self.is_yt = False
        self.is_qbit = False
        self.is_mega = False
        self.is_terabox = False
        self.is_terabox_account = False
        self.is_nzb = False
        self.is_jd = False
        self.is_clone = False
        self.is_uphoster = False
        self.is_gdrive = False
        self.is_rclone = False
        self.is_ytdlp = False
        self.equal_splits = False
        self.transmission_mode = "bot"
        self.extract = False
        self.compress = False
        self.select = False
        self.seed = False
        self.join = False
        self.private_link = False
        self.stop_duplicate = False
        self.sample_video = False
        self.convert_audio = False
        self.convert_video = False
        self.screen_shots = False
        self.is_cancelled = False
        self.force_run = False
        self.force_download = False
        self.force_upload = False
        self.is_torrent = False
        self.as_med = False
        self.as_doc = False
        self.is_file = False
        self.bot_trans = False
        self.user_trans = False
        self.progress = True
        self.ffmpeg_cmds = None
        self.is_encode = False
        self.encode_profile = None
        self.encode_metadata = {}
        self.metadata_title = None
        self.chat_thread_id = None
        self.subproc = None
        self.thumb = None
        self.excluded_extensions = []
        self.files_to_proceed = []
        self.is_super_chat = self.message.chat.type in [
            ChatType.SUPERGROUP,
            ChatType.CHANNEL,
            ChatType.FORUM,
        ]
        self.source_url = None
        self.bot_pm = Config.BOT_PM or self.user_dict.get("BOT_PM")
        self.pm_msg = None
        self.processing_msg = None
        self._tbx_web = False
        self._tbx_selection = []
        self._rcl_web = False
        self.terabox_cookie = ""
        self.terabox_cookie_source = ""
        self.terabox_cookie_error = ""
        self.file_details = {}
        self.mode = tuple()

    def _set_mode_engine(self):
        self.source_url = (
            self.link
            if len(self.link) > 0 and self.link.startswith("http")
            else (
                f"https://t.me/share/url?url={self.link}"
                if self.link
                else self.message.link
            )
        )

        out_mode = f"#{'Leech' if self.is_leech else 'UphosterUpload' if self.is_uphoster else 'Clone' if self.is_clone else 'Mega' if self.up_dest in ('mega', 'mega:') else 'RClone' if self.up_dest.startswith('mrcc:') or is_rclone_path(self.up_dest) else 'GDrive' if self.up_dest.startswith(('mtp:', 'tp:', 'sa:')) or is_gdrive_id(self.up_dest) else 'UpHosters'}"
        out_mode += " (Zip)" if self.compress else " (Unzip)" if self.extract else ""

        self.is_rclone = is_rclone_path(self.link)
        self.is_gdrive = is_gdrive_link(self.source_url) if self.source_url else False
        self.is_mega = is_mega_link(self.link) if self.source_url else False
        self.is_terabox = self.is_terabox_account or (
            is_terabox_link(self.link) if self.source_url else False
        )

        in_mode = f"#{'TeraBox' if self.is_terabox else 'Mega' if self.is_mega else 'qBit' if self.is_qbit else 'SABnzbd' if self.is_nzb else 'JDown' if self.is_jd else 'RCloneDL' if self.is_rclone else 'ytdlp' if self.is_ytdlp else 'GDrive' if (self.is_clone or self.is_gdrive) else 'Aria2' if (self.source_url and self.source_url != self.message.link) else 'TgMedia'}"

        self.mode = (in_mode, out_mode)

    def get_token_path(self, dest):
        if dest.startswith("mtp:"):
            return f"tokens/{self.user_id}.pickle"
        elif (
            dest.startswith("sa:")
            or Config.USE_SERVICE_ACCOUNTS
            and not dest.startswith("tp:")
        ):
            return "accounts"
        else:
            return "token.pickle"

    def get_config_path(self, dest):
        return (
            f"rclone/{self.user_id}.conf" if dest.startswith("mrcc:") else "rclone.conf"
        )

    async def is_token_exists(self, path, status):
        if is_rclone_path(path):
            config_path = self.get_config_path(path)
            if config_path != "rclone.conf" and status == "up":
                self.private_link = True
            if not await aiopath.exists(config_path):
                if config_path.startswith("rclone/"):
                    raise ValueError(
                        f"Your rclone config ({config_path}) was not found. "
                        "Upload it via /userset > Rclone Tools > RCLONE CONFIG."
                    )
                raise ValueError(
                    f"Rclone config not found: {config_path}. "
                    "Ask the bot owner to provide one, or upload your own via /userset."
                )
        elif (
            status == "dl"
            and is_gdrive_link(path)
            or status == "up"
            and is_gdrive_id(path)
        ):
            token_path = self.get_token_path(path)
            if token_path.startswith("tokens/") and status == "up":
                self.private_link = True
            if not await aiopath.exists(token_path):
                if token_path.startswith("tokens/"):
                    raise ValueError(
                        f"Your token.pickle ({token_path}) was not found. "
                        "Upload it via /userset > GDrive Tools > TOKEN.PICKLE."
                    )
                raise ValueError(
                    f"token.pickle not found: {token_path}. "
                    "Ask the bot owner to provide one, or upload your own via /userset."
                )

    async def _terabox_cookie_path(self, purpose="Transfer"):
        selector = TeraboxCookieSelector(self, purpose=purpose)
        cookie = await selector.select()
        self.terabox_cookie_error = selector.error
        if cookie:
            self.terabox_cookie_source = selector.cookie_label
        return cookie

    async def _prepare_leech_dumps(self):
        if not self.is_leech:
            return

        dumps = normalize_named_leech_dumps(
            self.user_dict.get("LEECH_DUMP")
            if "LEECH_DUMP" in self.user_dict
            else self.user_dict.get("LDUMP"),
            self.user_dict.get("LEECH_DUMP_CHAT"),
            self.user_id,
        )
        requested = str(self.user_dump_selection or "").strip()
        dump_mode = self.user_dict.get("DUMP_MODE", True)
        if not dump_mode:
            if requested:
                raise ValueError(
                    "Leech Dump mode is disabled. Enable it in /userset before using -ud."
                )
            self.selected_dumps = []
            return

        if not dumps:
            if requested:
                raise ValueError(
                    "No Leech Dumps are configured. Add them in /userset first."
                )
            self.selected_dumps = []
            return

        selected = select_named_leech_dumps(dumps, requested)
        if selected is not None:
            self.selected_dumps = selected
        elif "selected_dumps" in self.leech_dump_context:
            self.selected_dumps = list(self.leech_dump_context["selected_dumps"])
        elif len(dumps) == 1:
            self.selected_dumps = list(dumps)
        else:
            self.selected_dumps, is_cancelled = await open_leech_dump_btns(
                self.message, dumps
            )
            if is_cancelled:
                self.is_cancelled = True
                raise ValueError("Leech Dump selection cancelled.")
        self.leech_dump_context["selected_dumps"] = tuple(self.selected_dumps)

    async def _normalize_command_leech_destination(self):
        if not self.cmd_up_dest:
            return
        destinations = parse_leech_dump_destinations(
            self.cmd_up_dest, self.user_id
        )
        if len(destinations) != 1:
            raise ValueError("-up accepts exactly one Telegram destination.")
        chat_id, topic_id = destinations[0]
        if chat_id != self.user_id:
            try:
                chat = await TgClient.bot.get_chat(chat_id)
            except Exception as err:
                raise ValueError(
                    f"The bot cannot access the -up destination {chat_id}: "
                    f"{str(err) or type(err).__name__}"
                ) from err
            chat_id = chat.id
        self.cmd_up_dest = format_leech_dump_destination((chat_id, topic_id))

    async def before_start(self):
        await self._prepare_leech_dumps()
        self.name_swap = (
            self.name_swap
            or self.user_dict.get("NAME_SWAP", False)
            or (Config.NAME_SWAP if "NAME_SWAP" not in self.user_dict else "")
        )
        if self.name_swap:
            self.name_swap = [x.split(":") for x in self.name_swap.split("|")]

        self.autorename_template = self.user_dict.get("AUTORENAME_TEMPLATE", "")

        self.excluded_extensions = self.user_dict.get("EXCLUDED_EXTENSIONS") or (
            excluded_extensions
            if "EXCLUDED_EXTENSIONS" not in self.user_dict
            else ["aria2", "!qB"]
        )
        if not self.rc_flags:
            if self.user_dict.get("RCLONE_FLAGS"):
                self.rc_flags = self.user_dict["RCLONE_FLAGS"]
            elif "RCLONE_FLAGS" not in self.user_dict and Config.RCLONE_FLAGS:
                self.rc_flags = Config.RCLONE_FLAGS
        if self.link not in ["rcl", "gdl", "tbx"]:
            if not self.is_jd:
                if is_rclone_path(self.link):
                    if not self.link.startswith("mrcc:") and (
                        self.user_dict.get("USER_TOKENS", False)
                        or (
                            # Auto-detect: if the user has uploaded their
                            # own rclone.conf, use mrcc: mode automatically.
                            # Same UX trap as GDRIVE_ID — see upload path
                            # comment below for details.
                            self.user_id
                            and await aiopath.exists(f"rclone/{self.user_id}.conf")
                        )
                    ):
                        self.link = f"mrcc:{self.link}"
                    await self.is_token_exists(self.link, "dl")
                elif is_gdrive_link(self.link):
                    if not self.link.startswith(
                        ("mtp:", "tp:", "sa:")
                    ) and (
                        self.user_dict.get("USER_TOKENS", False)
                        or (
                            # Auto-detect: if the user has uploaded their
                            # own token.pickle, use mtp: mode for downloads
                            # too (mirror of the upload-side fix).
                            self.user_id
                            and await aiopath.exists(f"tokens/{self.user_id}.pickle")
                        )
                    ):
                        self.link = f"mtp:{self.link}"
                    await self.is_token_exists(self.link, "dl")
        elif self.link == "rcl":
            if not self.is_ytdlp and not self.is_jd:
                self.link = await RcloneList(self).get_rclone_path("rcd")
                if not is_rclone_path(self.link):
                    raise ValueError(self.link)
                if not self.is_clone and get_valid_base_url():
                    self._rcl_web = True
        elif self.link == "gdl":
            if not self.is_ytdlp and not self.is_jd:
                self.link = await GoogleDriveList(self).get_target_id("gdd")
                if not is_gdrive_id(self.link):
                    raise ValueError(self.link)
        elif self.link == "tbx":
            if not self.is_ytdlp and not self.is_jd and not self.is_clone:
                self.terabox_cookie = await self._terabox_cookie_path("Download")
                if not self.terabox_cookie:
                    raise ValueError(
                        self.terabox_cookie_error or "No TeraBox cookie found."
                    )
                self.is_terabox_account = True
                if get_valid_base_url():
                    self._tbx_web = True
                else:
                    browser = TeraboxList(self)
                    self._tbx_selection = await browser.get_terabox_path()
                    if not self._tbx_selection:
                        raise ValueError(browser.error or "No TeraBox selection made.")

        self.transmission_mode = Config.TRANSMISSION_MODE

        if self.user_dict.get("UPLOAD_PATHS", False):
            if self.up_dest in self.user_dict["UPLOAD_PATHS"]:
                self.up_dest = self.user_dict["UPLOAD_PATHS"][self.up_dest]
        elif "UPLOAD_PATHS" not in self.user_dict and Config.UPLOAD_PATHS:
            if self.up_dest in Config.UPLOAD_PATHS:
                self.up_dest = Config.UPLOAD_PATHS[self.up_dest]

        if self.category and not self.is_leech:
            dcats = fetch_drive_cat(self.user_id)
            default_id = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
            default_index = self.user_dict.get("INDEX_URL") or Config.INDEX_URL
            merged_cats = {
                "Default": {"drive_id": default_id, "index_link": default_index},
                **dcats,
                **categories_dict,
            }
            if self.category == "gdl":
                self.up_dest = "gdl"
            elif self.category == "gd":
                self.up_dest = default_id
                self.index_link = default_index
            elif "|" in self.category:
                parts = self.category.split("|", 1)
                self.up_dest = parts[0]
                self.index_link = parts[1] if len(parts) > 1 else ""
            elif is_gdrive_id(self.category):
                self.up_dest = self.category
            elif self.category in merged_cats:
                self.up_dest = merged_cats[self.category]["drive_id"]
                self.index_link = merged_cats[self.category].get("index_link", "")
            else:
                drive_id, index_link, is_cancelled = await open_category_btns(self.message)
                if is_cancelled:
                    self.is_cancelled = True
                    return
                if drive_id:
                    self.up_dest = drive_id
                    self.index_link = index_link or ""
            gc_used = True
        else:
            gc_used = False

        if self.ffmpeg_cmds and not isinstance(self.ffmpeg_cmds, list):
            if self.user_dict.get("FFMPEG_CMDS", None):
                ffmpeg_dict = self.user_dict["FFMPEG_CMDS"]
                self.ffmpeg_cmds = [
                    value
                    for key in list(self.ffmpeg_cmds)
                    if key in ffmpeg_dict
                    for value in ffmpeg_dict[key]
                ]
            elif "FFMPEG_CMDS" not in self.user_dict and Config.FFMPEG_CMDS:
                ffmpeg_dict = Config.FFMPEG_CMDS
                self.ffmpeg_cmds = [
                    value
                    for key in list(self.ffmpeg_cmds)
                    if key in ffmpeg_dict
                    for value in ffmpeg_dict[key]
                ]
            else:
                self.ffmpeg_cmds = None

        self.metadata_title = self.user_dict.get("METADATA")

        if not self.is_leech:
            self.stop_duplicate = (
                self.user_dict.get("STOP_DUPLICATE")
                or "STOP_DUPLICATE" not in self.user_dict
                and Config.STOP_DUPLICATE
            )
            if not gc_used:
                configured_upload = (
                    self.user_dict.get("DEFAULT_UPLOAD", "") or Config.DEFAULT_UPLOAD
                )
                default_upload = Config._normalize_default_upload(configured_upload)
                up_dest_text = self.up_dest if isinstance(self.up_dest, str) else ""
                if not self.is_uphoster and (
                    up_dest_text in ("tb", "tbx")
                    or up_dest_text.startswith(("tb:", "tbx:"))
                ):
                    raise ValueError(
                        "TeraBox upload is not supported. Choose Google Drive, "
                        "rclone, Mega, Telegram, or a DDL hoster."
                    )
                if not self.is_uphoster and (
                    (not self.up_dest and default_upload == "rc") or self.up_dest == "rc"
                ):
                    self.up_dest = self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH
                elif not self.is_uphoster and (
                    (not self.up_dest and default_upload == "gd") or self.up_dest == "gd"
                ):
                    self.up_dest = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
                elif (not self.up_dest and default_upload == "mega") or self.up_dest == "mega":
                    self.up_dest = "mega:"

                if self.is_uphoster and not self.up_dest:
                    uphoster_service = self.user_dict.get("UPHOSTER_SERVICE", "gofile")
                    services = uphoster_service.split(",")
                    for service in services:
                        if service == "gofile":
                            if not (
                                self.user_dict.get("GOFILE_TOKEN") or Config.GOFILE_API
                            ):
                                raise ValueError(
                                    "No Gofile API token found. Set GOFILE_API in "
                                    "config or add your own via /userset."
                                )
                        elif service == "buzzheavier":
                            if not (
                                self.user_dict.get("BUZZHEAVIER_TOKEN")
                                or Config.BUZZHEAVIER_API
                            ):
                                raise ValueError(
                                    "No BuzzHeavier API key found. Set BUZZHEAVIER_API "
                                    "in config or add your own via /userset."
                                )
                        elif service == "pixeldrain":
                            if not (
                                self.user_dict.get("PIXELDRAIN_KEY")
                                or Config.PIXELDRAIN_KEY
                            ):
                                raise ValueError(
                                    "No PixelDrain API key found. Set PIXELDRAIN_KEY "
                                    "in config or add your own via /userset."
                                )
                    self.up_dest = "Uphoster"

            if not self.up_dest:
                raise ValueError(
                    "No upload destination set. Use /mirror <link> -up <destination> "
                    "or set a default via /userset."
                )

            if is_gdrive_id(self.up_dest):
                if not self.up_dest.startswith(
                    ("mtp:", "tp:", "sa:")
                ) and (
                    self.user_dict.get("USER_TOKENS", False)
                    or (
                        # Auto-detect: if the user has uploaded their own
                        # token.pickle AND set their own GDRIVE_ID, use
                        # mtp: mode automatically. Previously the user
                        # had to manually toggle "Swap to USER token" in
                        # /userset, which was a UX trap — they'd upload
                        # token.pickle + GDRIVE_ID and still get "File
                        # not found" because the bot used the operator's
                        # token against the user's drive folder.
                        self.user_dict.get("GDRIVE_ID")
                        and self.user_dict.get("GDRIVE_ID") != Config.GDRIVE_ID
                        and self.user_id
                    )
                ):
                    if not self.user_dict.get("USER_TOKENS", False):
                        LOGGER.info(
                            f"Auto-detected user GDRIVE_ID for user_id={self.user_id}; "
                            "switching to user token.pickle (mtp: mode)."
                        )
                    self.up_dest = f"mtp:{self.up_dest}"
            elif self.up_dest == "mega:":
                pass
            elif is_rclone_path(self.up_dest):
                if not self.up_dest.startswith("mrcc:") and (
                    self.user_dict.get("USER_TOKENS", False)
                    or (
                        # Auto-detect: if the user has uploaded their own
                        # rclone.conf, use mrcc: mode automatically. Same
                        # UX trap fix as the GDRIVE_ID case above.
                        self.user_id
                        and await aiopath.exists(f"rclone/{self.user_id}.conf")
                    )
                ):
                    self.up_dest = f"mrcc:{self.up_dest}"
                self.up_dest = self.up_dest.strip("/")
            elif self.up_dest in ("gdl", "rcl"):
                pass
            elif self.is_uphoster:
                pass
            else:
                raise ValueError(
                    f"Wrong upload destination: {self.up_dest!r}. "
                    "Use a GDrive ID, rclone path (remote:path), 'gdl', 'rcl', "
                    "or 'mega:'. Run /help mirror for details."
                )

            if (
                self.up_dest not in ["rcl", "gdl"]
                and not self.is_uphoster
                and self.up_dest != "mega:"
            ):
                await self.is_token_exists(self.up_dest, "up")

            if self.up_dest == "rcl":
                if self.is_clone:
                    if not is_rclone_path(self.link):
                        raise ValueError(
                            "You can't clone from different types of tools"
                        )
                    config_path = self.get_config_path(self.link)
                else:
                    config_path = None
                self.up_dest = await RcloneList(self).get_rclone_path(
                    "rcu", config_path
                )
                if not is_rclone_path(self.up_dest):
                    raise ValueError(self.up_dest)
            elif self.up_dest == "gdl":
                if self.is_clone:
                    if not is_gdrive_link(self.link):
                        raise ValueError(
                            "You can't clone from different types of tools"
                        )
                    token_path = self.get_token_path(self.link)
                else:
                    token_path = None
                self.up_dest = await GoogleDriveList(self).get_target_id(
                    "gdu", token_path
                )
                if not is_gdrive_id(self.up_dest):
                    raise ValueError(self.up_dest)
            elif self.is_clone:
                if is_gdrive_link(self.link) and self.get_token_path(
                    self.link
                ) != self.get_token_path(self.up_dest):
                    raise ValueError("You must use the same token to clone!")
                elif is_rclone_path(self.link) and self.get_config_path(
                    self.link
                ) != self.get_config_path(self.up_dest):
                    raise ValueError("You must use the same config to clone!")
        else:
            # Config.LEECH_DUMP_CHAT remains the primary upload chat. A task's
            # -up value and selected named Leech Dumps are cached separately and
            # copied after upload, preserving topic IDs and avoiding reparsing.
            self.leech_dest = ""
            self.cmd_up_dest = self.up_dest
            self.transmission_mode = Config.TRANSMISSION_MODE
            if self.cmd_up_dest:
                if not isinstance(self.cmd_up_dest, int):
                    mode_prefix = self.cmd_up_dest[:2].lower()
                    if mode_prefix == "b:":
                        self.cmd_up_dest = self.cmd_up_dest[2:]
                        self.transmission_mode = "bot"
                    elif mode_prefix == "u:":
                        self.cmd_up_dest = self.cmd_up_dest[2:]
                        self.transmission_mode = "user"
                    elif mode_prefix == "h:":
                        self.cmd_up_dest = self.cmd_up_dest[2:]
                        self.transmission_mode = "both"
            await self._normalize_command_leech_destination()
            if self.bot_trans:
                self.transmission_mode = "bot"
            if self.user_trans:
                self.transmission_mode = "user"
            if self.hybrid_leech:
                self.transmission_mode = "both"

            self.up_dest = Config.LEECH_DUMP_CHAT
            if self.up_dest:
                if not isinstance(self.up_dest, int):
                    if "|" in str(self.up_dest):
                        self.up_dest, self.chat_thread_id = list(
                            map(
                                lambda x: int(x) if x.lstrip("-").isdigit() else x,
                                self.up_dest.split("|", 1),
                            )
                        )
                    elif str(self.up_dest).lstrip("-").isdigit():
                        self.up_dest = int(self.up_dest)

                if self.transmission_mode in ("user", "both"):
                    if not TgClient.user:
                        self.transmission_mode = "bot"
                    else:
                        try:
                            chat = await TgClient.user.get_chat(self.up_dest)
                        except Exception:
                            chat = None
                        if chat is None:
                            self.transmission_mode = "bot"
                        else:
                            uploader_id = TgClient.user.me.id
                            if chat.type not in [
                                ChatType.SUPERGROUP,
                                ChatType.CHANNEL,
                                ChatType.GROUP,
                                ChatType.FORUM,
                            ]:
                                self.transmission_mode = "bot"
                            else:
                                member = await chat.get_member(uploader_id)
                                if (
                                    not member.privileges.can_manage_chat
                                    or not member.privileges.can_delete_messages
                                ):
                                    self.transmission_mode = "bot"

                try:
                    chat = await self.client.get_chat(self.up_dest)
                except Exception:
                    chat = None
                if chat is None:
                    if self.transmission_mode == "bot":
                        raise ValueError(
                            "Chat not found! Try adding the bot to the chat and try again!"
                        )
                else:
                    uploader_id = self.client.me.id
                    if chat.type in [
                        ChatType.SUPERGROUP,
                        ChatType.CHANNEL,
                        ChatType.GROUP,
                        ChatType.FORUM,
                    ]:
                        member = await chat.get_member(uploader_id)
                        if (
                            not member.privileges.can_manage_chat
                            or not member.privileges.can_delete_messages
                        ):
                            if self.transmission_mode == "bot":
                                raise ValueError(
                                    "You don't have enough privileges in this chat!"
                                )
                            else:
                                self.transmission_mode = "user"
                    else:
                        if self.transmission_mode == "bot":
                            try:
                                await self.client.send_chat_action(
                                    self.up_dest, ChatAction.TYPING
                                )
                            except Exception as err:
                                raise ValueError(
                                    "Start the bot and try again!"
                                ) from err
                        else:
                            self.transmission_mode = "user"
            elif self.transmission_mode in ("user", "both") and not self.is_super_chat:
                self.transmission_mode = "bot"
            if self.split_size:
                if self.split_size.isdigit():
                    self.split_size = int(self.split_size)
                else:
                    self.split_size = get_size_bytes(self.split_size)
            self.split_size = (
                self.split_size
                or self.user_dict.get("LEECH_SPLIT_SIZE")
                or Config.LEECH_SPLIT_SIZE
            )
            self.equal_splits = (
                self.user_dict.get("EQUAL_SPLITS")
                or Config.EQUAL_SPLITS
                and "EQUAL_SPLITS" not in self.user_dict
            )
            self.max_split_size = (
                TgClient.MAX_SPLIT_SIZE if self.transmission_mode in ("user", "both") else 2097152000
            )
            self.split_size = min(self.split_size, self.max_split_size)

            if not self.as_doc:
                self.as_doc = (
                    not self.as_med
                    if self.as_med
                    else (
                        self.user_dict.get("AS_DOCUMENT", False)
                        or Config.AS_DOCUMENT
                        and "AS_DOCUMENT" not in self.user_dict
                    )
                )

            self.thumbnail_layout = (
                self.thumbnail_layout
                or self.user_dict.get("THUMBNAIL_LAYOUT", False)
                or (
                    Config.THUMBNAIL_LAYOUT
                    if "THUMBNAIL_LAYOUT" not in self.user_dict
                    else ""
                )
            )

            if self.thumb and self.thumb != "none":
                if is_telegram_link(self.thumb):
                    msg = (await get_tg_link_message(self.thumb))[0]
                    self.thumb = (
                        await create_thumb(msg) if msg.photo or msg.document else ""
                    )
                elif self.thumb.startswith("http"):
                    self.thumb = await download_image_thumb(self.thumb)

    async def get_tag(self, text: list):
        if len(text) > 1 and text[1].startswith("Tag: "):
            user_info = text[1].split("Tag: ")
            if len(user_info) >= 3:
                id_ = user_info[-1]
                self.tag = " ".join(user_info[:-1])
            else:
                self.tag, id_ = text[1].split("Tag: ")[1].split()
            self.user = self.message.from_user = await self.client.get_users(int(id_))
            self.user_id = self.user.id
            self.user_dict = user_data.get(self.user_id, {})
            with suppress(Exception):
                await self.message.unpin()
        if self.user:
            self.tag = get_user_mention(self.user)

    @staticmethod
    def _multi_sender_id(message):
        sender = getattr(message, "from_user", None) or getattr(
            message, "sender_chat", None
        )
        return getattr(sender, "id", None)

    @staticmethod
    def _is_multi_source(message):
        if not isinstance(message, Message) or getattr(message, "empty", False):
            return False
        text = (getattr(message, "text", None) or "").lstrip()
        if text.startswith("/"):
            return False
        return bool(
            getattr(message, "media", None)
            or text
            or getattr(message, "caption", None)
        )

    async def _get_next_multi_source(self):
        reply_id = self.message.reply_to_message_id
        if reply_id is None:
            return None

        current_source = self.message.reply_to_message
        if not isinstance(current_source, Message):
            current_source = await self.client.get_messages(
                chat_id=self.message.chat.id,
                message_ids=reply_id,
            )
        sender_id = self._multi_sender_id(current_source)
        thread_id = getattr(current_source, "message_thread_id", None)

        # Telegram message IDs are not guaranteed to be consecutive. Search
        # forward through messages that existed before the command and select
        # the next usable item from the same sender as the replied source.
        last_id = min(self.message.id - 1, reply_id + 1000)
        for start_id in range(reply_id + 1, last_id + 1, 100):
            message_ids = list(range(start_id, min(start_id + 100, last_id + 1)))
            messages = await self.client.get_messages(
                chat_id=self.message.chat.id,
                message_ids=message_ids,
            )
            if isinstance(messages, Message):
                messages = [messages]
            elif not isinstance(messages, list):
                messages = []
            for candidate in sorted(
                (msg for msg in messages if isinstance(msg, Message)),
                key=lambda msg: msg.id,
            ):
                if not self._is_multi_source(candidate):
                    continue
                if (
                    thread_id is not None
                    and getattr(candidate, "message_thread_id", None) != thread_id
                ):
                    continue
                if sender_id is None or self._multi_sender_id(candidate) == sender_id:
                    return candidate
        return None

    async def _record_unstarted_multi_leech(self, summary, count, error):
        if summary is None:
            return
        snapshot = await summary.record_unstarted(
            count,
            summary.total - self.multi + 2,
            error,
            self.tag,
        )
        if snapshot is not None:
            send_summary = getattr(self, "_send_multi_leech_summary", None)
            if send_summary is not None:
                await send_summary(snapshot)

    @new_task
    async def run_multi(self, input_list, obj):
        await sleep(7)
        multi_leech_summary = getattr(self, "multi_leech_summary", None)
        if not self.multi_tag and self.multi > 1:
            self.multi_tag = token_hex(3)
            multi_tags.add(self.multi_tag)
        elif self.multi <= 1:
            # A multi-leech owns its tag until the shared completion summary
            # has been emitted. Other multi-task modes keep the old lifecycle.
            if multi_leech_summary is None and self.multi_tag in multi_tags:
                multi_tags.discard(self.multi_tag)
            return
        if self.multi_tag and self.multi_tag not in multi_tags:
            await send_message(
                self.message, f"{self.tag} Multi Task has been cancelled!"
            )
            await send_status_message(self.message)
            async with task_dict_lock:
                for fd_name in self.same_dir:
                    self.same_dir[fd_name]["total"] -= self.multi
            await self._record_unstarted_multi_leech(
                multi_leech_summary,
                self.multi - 1,
                "Multi Task was cancelled before this item started.",
            )
            return
        if len(self.bulk) != 0:
            msg = input_list[:1]
            msg.append(f"{self.bulk[0]} -i {self.multi - 1} {self.options}")
            msgts = " ".join(msg)
            if self.multi > 2:
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msgts)
        else:
            msg = [s.strip() for s in input_list]
            index = msg.index("-i")
            msg[index + 1] = f"{self.multi - 1}"
            next_source = await self._get_next_multi_source()
            if not isinstance(next_source, Message):
                multi_tags.discard(self.multi_tag)
                await self._record_unstarted_multi_leech(
                    multi_leech_summary,
                    self.multi - 1,
                    "The next file/link could not be found.",
                )
                await send_message(
                    self.message,
                    "Multi Task stopped: I could not find the next file/link after "
                    "the replied message.",
                )
                return
            msgts = " ".join(msg)
            if self.multi > 2:
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(next_source, msgts)
        if not isinstance(nextmsg, Message):
            await self._record_unstarted_multi_leech(
                multi_leech_summary,
                self.multi - 1,
                "The next multi-task command could not be created.",
            )
            return
        nextmsg = await self.client.get_messages(
            chat_id=self.message.chat.id, message_ids=nextmsg.id
        )
        if not isinstance(nextmsg, Message):
            await self._record_unstarted_multi_leech(
                multi_leech_summary,
                self.multi - 1,
                "The next multi-task command could not be loaded.",
            )
            return
        if self.message.from_user:
            nextmsg.from_user = self.user
        else:
            nextmsg.sender_chat = self.user
        if intervals["stopAll"]:
            await self._record_unstarted_multi_leech(
                multi_leech_summary,
                self.multi - 1,
                "The bot stopped before this item started.",
            )
            return

        next_task_kwargs = {}
        if multi_leech_summary is not None:
            next_task_kwargs["multi_leech_summary"] = multi_leech_summary
        next_task_kwargs["leech_dump_context"] = self.leech_dump_context

        await obj(
            client=self.client,
            message=nextmsg,
            is_qbit=self.is_qbit,
            is_leech=self.is_leech,
            is_jd=self.is_jd,
            is_nzb=self.is_nzb,
            is_uphoster=self.is_uphoster,
            same_dir=self.same_dir,
            bulk=self.bulk,
            multi_tag=self.multi_tag,
            options=self.options,
            **next_task_kwargs,
        ).new_event()

    async def init_bulk(self, input_list, bulk_start, bulk_end, obj):
        if Config.DISABLE_BULK:
            await send_message(self.message, "Bulk downloads are currently disabled.")
            return
        try:
            self.bulk = await extract_bulk_links(self.message, bulk_start, bulk_end)
            if len(self.bulk) == 0:
                raise ValueError("Bulk Empty!")
            b_msg = input_list[:1]
            self.options = input_list[1:]
            index = self.options.index("-b")
            del self.options[index]
            if bulk_start or bulk_end:
                del self.options[index]
            self.options = " ".join(self.options)
            b_msg.append(f"{self.bulk[0]} -i {len(self.bulk)} {self.options}")
            msg = " ".join(b_msg)
            if len(self.bulk) > 2:
                self.multi_tag = token_hex(3)
                multi_tags.add(self.multi_tag)
                msg += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msg)
            if not isinstance(nextmsg, Message):
                return
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id, message_ids=nextmsg.id
            )
            if not isinstance(nextmsg, Message):
                return
            if self.message.from_user:
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user

            next_task_kwargs = {}
            if multi_leech_summary := getattr(self, "multi_leech_summary", None):
                next_task_kwargs["multi_leech_summary"] = multi_leech_summary
            next_task_kwargs["leech_dump_context"] = self.leech_dump_context

            await obj(
                client=self.client,
                message=nextmsg,
                is_qbit=self.is_qbit,
                is_leech=self.is_leech,
                is_jd=self.is_jd,
                is_nzb=self.is_nzb,
                is_uphoster=self.is_uphoster,
                same_dir=self.same_dir,
                bulk=self.bulk,
                multi_tag=self.multi_tag,
                options=self.options,
                **next_task_kwargs,
            ).new_event()
        except Exception:
            await send_message(
                self.message,
                "Reply to text file or to telegram message that have links seperated by new line!",
            )

    async def proceed_extract(self, dl_path, gid):
        pswd = self.extract if isinstance(self.extract, str) else ""
        self.files_to_proceed = []
        if self.is_file and (
            is_archive(dl_path) or is_first_archive_split(dl_path)
        ):
            self.files_to_proceed.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    if (
                        is_first_archive_split(file_)
                        or is_archive(file_)
                        and not file_.strip().lower().endswith(".rar")
                    ):
                        f_path = ospath.join(dirpath, file_)
                        self.files_to_proceed.append(f_path)

        if not self.files_to_proceed:
            LOGGER.warning(
                "Extraction requested but no supported archive was found: %s",
                dl_path,
            )
            await send_message(
                self.message,
                "<b>Extraction skipped:</b> No supported archive or first "
                "multipart volume was found.",
            )
            return dl_path
        sevenz = SevenZ(self)
        LOGGER.info(f"Extracting: {self.name}")
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Extract")
        t_path = dl_path
        extraction_failed = False
        for dirpath, _, files in await sync_to_async(
            walk, self.up_dir or self.dir, topdown=False
        ):
            code = 0
            directory_processed = False
            directory_failed = False
            for file_ in files:
                if self.is_cancelled:
                    return False
                if (
                    is_first_archive_split(file_)
                    or is_archive(file_)
                    and not file_.strip().lower().endswith(".rar")
                ):
                    directory_processed = True
                    self.proceed_count += 1
                    f_path = ospath.join(dirpath, file_)
                    t_path = get_base_name(f_path) if self.is_file else dirpath
                    if not self.is_file:
                        self.subname = file_
                    code = await sevenz.extract(f_path, t_path, pswd)
                    if code != 0:
                        directory_failed = True
                        extraction_failed = True
            if self.is_cancelled:
                return code
            if directory_processed and not directory_failed:
                for file_ in files:
                    if is_archive_split(file_) or is_archive(file_):
                        del_path = ospath.join(dirpath, file_)
                        try:
                            await remove(del_path)
                        except Exception:
                            self.is_cancelled = True
        if extraction_failed:
            await send_message(
                self.message,
                "<b>Extraction failed:</b> The original archive will be "
                "uploaded. Check that every multipart volume is present and "
                "that the extraction password is correct.",
            )
        return t_path if self.is_file and not extraction_failed else dl_path

    async def proceed_ffmpeg(self, dl_path, gid):
        checked = False
        lock_acquired = False
        cmds = [
            [part.strip() for part in split(item) if part.strip()]
            for item in self.ffmpeg_cmds
        ]
        try:
            ffmpeg = FFMpeg(self)
            for ffmpeg_cmd in cmds:
                self.proceed_count = 0
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
                ] + ffmpeg_cmd
                if "-del" in cmd:
                    cmd.remove("-del")
                    delete_files = True
                else:
                    delete_files = False
                index = cmd.index("-i")
                input_file = cmd[index + 1]
                if input_file.strip().endswith(".video"):
                    ext = "video"
                elif input_file.strip().endswith(".audio"):
                    ext = "audio"
                elif "." not in input_file:
                    ext = "all"
                else:
                    ext = ospath.splitext(input_file)[-1].lower()
                if await aiopath.isfile(dl_path):
                    is_video, is_audio, _ = await get_document_type(dl_path)
                    if not is_video and not is_audio:
                        break
                    elif is_video and ext == "audio":
                        break
                    elif is_audio and not is_video and ext == "video":
                        break
                    elif ext not in [
                        "all",
                        "audio",
                        "video",
                    ] and not dl_path.strip().lower().endswith(ext):
                        break
                    new_folder = ospath.splitext(dl_path)[0]
                    if await aiopath.isfile(new_folder):
                        new_folder = f"{new_folder}_temp"
                    name = ospath.basename(dl_path)
                    await makedirs(new_folder, exist_ok=True)
                    file_path = f"{new_folder}/{name}"
                    await move(dl_path, file_path)
                    if not checked:
                        checked = True
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "FFmpeg"
                            )
                        self.progress = False
                        await ff_lock.acquire()
                        lock_acquired = True
                        self.progress = True
                    LOGGER.info(f"Running ffmpeg cmd for: {file_path}")
                    var_cmd = cmd.copy()
                    var_cmd[index + 1] = file_path
                    self.subsize = self.size
                    res = await ffmpeg.ffmpeg_cmds(var_cmd, file_path)
                    if res:
                        if delete_files:
                            await remove(file_path)
                            if len(await listdir(new_folder)) == 1:
                                folder = new_folder.rsplit("/", 1)[0]
                                self.name = ospath.basename(res[0])
                                if self.name.startswith("ffmpeg"):
                                    self.name = self.name.split(".", 1)[-1]
                                dl_path = ospath.join(folder, self.name)
                                await move(res[0], dl_path)
                                await rmtree(new_folder)
                            else:
                                dl_path = new_folder
                                self.name = new_folder.rsplit("/", 1)[-1]
                        else:
                            dl_path = new_folder
                            self.name = new_folder.rsplit("/", 1)[-1]
                    else:
                        await move(file_path, dl_path)
                        await rmtree(new_folder)
                else:
                    for dirpath, _, files in await sync_to_async(
                        walk, dl_path, topdown=False
                    ):
                        for file_ in files:
                            var_cmd = cmd.copy()
                            if self.is_cancelled:
                                return False
                            f_path = ospath.join(dirpath, file_)
                            is_video, is_audio, _ = await get_document_type(f_path)
                            if not is_video and not is_audio:
                                continue
                            elif is_video and ext == "audio":
                                continue
                            elif is_audio and not is_video and ext == "video":
                                continue
                            elif ext not in [
                                "all",
                                "audio",
                                "video",
                            ] and not f_path.strip().lower().endswith(ext):
                                continue
                            self.proceed_count += 1
                            var_cmd[index + 1] = f_path
                            if not checked:
                                checked = True
                                async with task_dict_lock:
                                    task_dict[self.mid] = FFmpegStatus(
                                        self, ffmpeg, gid, "FFmpeg"
                                    )
                                self.progress = False
                                await ff_lock.acquire()
                                lock_acquired = True
                                self.progress = True
                            LOGGER.info(f"Running ffmpeg cmd for: {f_path}")
                            self.subsize = await get_path_size(f_path)
                            self.subname = file_
                            res = await ffmpeg.ffmpeg_cmds(var_cmd, f_path)
                            if res and delete_files:
                                await remove(f_path)
                                if len(res) == 1:
                                    file_name = ospath.basename(res[0])
                                    if file_name.startswith("ffmpeg"):
                                        newname = file_name.split(".", 1)[-1]
                                        newres = ospath.join(dirpath, newname)
                                        await move(res[0], newres)
        finally:
            if lock_acquired:
                await ff_lock.release()
        return dl_path

    async def substitute(self, dl_path):
        def perform_swap(name, swaps, template=""):
            name, ext = ospath.splitext(name)
            name = sub(r"www\S+", "", name)

            if template:
                name_ext = apply_autorename_template(name + ext, template)
                name, ext = ospath.splitext(name_ext)

            if swaps:
                for swap in swaps:
                    pattern, res, cnt, sen = (
                        swap + ["", "0", "NOFLAG"][min(len(swap) - 1, 2) :]
                    )[0:4]
                    cnt = 0 if len(cnt) == 0 else int(cnt)
                    try:
                        name = sub(
                            rf"{pattern}",
                            res,
                            name,
                            count=cnt,
                            flags=getattr(re, sen.upper(), 0),
                        )
                    except Exception as e:
                        LOGGER.error(
                            f"Swap Error: pattern: {pattern} res: {res}. Error: {e}"
                        )
                        return False
                    if len(name.encode()) > 255:
                        LOGGER.error(f"Substitute: {name} is too long")
                        return False
            return name + ext

        if self.is_file:
            up_dir, name = dl_path.rsplit("/", 1)
            new_name = perform_swap(name, self.name_swap, self.autorename_template)
            if not new_name:
                return dl_path
            new_path = ospath.join(up_dir, new_name)
            await move(dl_path, new_path)
            return new_path
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    new_name = perform_swap(file_, self.name_swap, self.autorename_template)
                    if not new_name:
                        continue
                    await move(f_path, ospath.join(dirpath, new_name))
            return dl_path

    async def generate_screenshots(self, dl_path):
        ss_nb = int(self.screen_shots) if isinstance(self.screen_shots, str) else 10
        if self.is_file:
            if (await get_document_type(dl_path))[0]:
                LOGGER.info(f"Creating Screenshot for: {dl_path}")
                res = await take_ss(dl_path, ss_nb)
                if res:
                    new_folder = ospath.splitext(dl_path)[0]
                    if await aiopath.isfile(new_folder):
                        new_folder = f"{new_folder}_temp"
                    name = ospath.basename(dl_path)
                    await makedirs(new_folder, exist_ok=True)
                    await gather(
                        move(dl_path, f"{new_folder}/{name}"),
                        move(res, new_folder),
                    )
                    return new_folder
        else:
            LOGGER.info(f"Creating Screenshot for: {dl_path}")
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        await take_ss(f_path, ss_nb)
        return dl_path

    async def convert_media(self, dl_path, gid):
        fvext = []
        if self.convert_video:
            vdata = self.convert_video.split()
            vext = vdata[0].lower()
            if len(vdata) > 2:
                if "+" in vdata[1].split():
                    vstatus = "+"
                elif "-" in vdata[1].split():
                    vstatus = "-"
                else:
                    vstatus = ""
                fvext.extend(f".{ext.lower()}" for ext in vdata[2:])
            else:
                vstatus = ""
        else:
            vext = ""
            vstatus = ""

        faext = []
        if self.convert_audio:
            adata = self.convert_audio.split()
            aext = adata[0].lower()
            if len(adata) > 2:
                if "+" in adata[1].split():
                    astatus = "+"
                elif "-" in adata[1].split():
                    astatus = "-"
                else:
                    astatus = ""
                faext.extend(f".{ext.lower()}" for ext in adata[2:])
            else:
                astatus = ""
        else:
            aext = ""
            astatus = ""

        self.files_to_proceed = {}
        all_files = []
        if self.is_file:
            all_files.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    all_files.append(f_path)

        for f_path in all_files:
            is_video, is_audio, _ = await get_document_type(f_path)
            if (
                is_video
                and vext
                and not f_path.strip().lower().endswith(f".{vext}")
                and (
                    vstatus == "+"
                    and f_path.strip().lower().endswith(tuple(fvext))
                    or vstatus == "-"
                    and not f_path.strip().lower().endswith(tuple(fvext))
                    or not vstatus
                )
            ):
                self.files_to_proceed[f_path] = "video"
            elif (
                is_audio
                and aext
                and not is_video
                and not f_path.strip().lower().endswith(f".{aext}")
                and (
                    astatus == "+"
                    and f_path.strip().lower().endswith(tuple(faext))
                    or astatus == "-"
                    and not f_path.strip().lower().endswith(tuple(faext))
                    or not astatus
                )
            ):
                self.files_to_proceed[f_path] = "audio"
        del all_files

        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Convert")
            self.progress = False
            async with ff_lock:
                self.progress = True
                for f_path, f_type in self.files_to_proceed.items():
                    self.proceed_count += 1
                    LOGGER.info(f"Converting: {f_path}")
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = ospath.basename(f_path)
                    if f_type == "video":
                        res = await ffmpeg.convert_video(f_path, vext)
                    else:
                        res = await ffmpeg.convert_audio(f_path, aext)
                    if res:
                        try:
                            await remove(f_path)
                        except Exception:
                            self.is_cancelled = True
                            return False
                        if self.is_file:
                            return res
        return dl_path

    async def proceed_encode(self, dl_path, gid):
        self.files_to_proceed = {}
        if self.is_file and (await get_document_type(dl_path))[0]:
            self.files_to_proceed[dl_path] = ospath.basename(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        self.files_to_proceed[f_path] = file_

        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Encode")
            self.progress = False
            async with ff_lock:
                self.progress = True
                for f_path, file_ in self.files_to_proceed.items():
                    self.proceed_count += 1
                    LOGGER.info(f"Encoding: {f_path}")
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = file_

                    res = await ffmpeg.encode_video(f_path, self.encode_profile, self.encode_metadata)

                    if res:
                        try:
                            await remove(f_path)
                        except Exception:
                            self.is_cancelled = True
                            return False
                        if self.is_file:
                            return res
        return dl_path

    async def generate_sample_video(self, dl_path, gid):
        data = (
            self.sample_video.split(":") if isinstance(self.sample_video, str) else ""
        )
        if data:
            sample_duration = int(data[0]) if data[0] else 60
            part_duration = int(data[1]) if len(data) > 1 else 4
        else:
            sample_duration = 60
            part_duration = 4

        self.files_to_proceed = {}
        if self.is_file and (await get_document_type(dl_path))[0]:
            file_ = ospath.basename(dl_path)
            self.files_to_proceed[dl_path] = file_
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        self.files_to_proceed[f_path] = file_
        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Sample Video")
            self.progress = False
            async with ff_lock:
                self.progress = True
                LOGGER.info(f"Creating Sample video: {self.name}")
                for f_path, file_ in self.files_to_proceed.items():
                    self.proceed_count += 1
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = file_
                    res = await ffmpeg.sample_video(
                        f_path, sample_duration, part_duration
                    )
                    if res and self.is_file:
                        new_folder = ospath.splitext(f_path)[0]
                        if await aiopath.isfile(new_folder):
                            new_folder = f"{new_folder}_temp"
                        await makedirs(new_folder, exist_ok=True)
                        await gather(
                            move(f_path, f"{new_folder}/{file_}"),
                            move(res, f"{new_folder}/SAMPLE.{file_}"),
                        )
                        return new_folder
        return dl_path

    async def proceed_compress(self, dl_path, gid):
        pswd = self.compress if isinstance(self.compress, str) else ""
        if self.is_leech and self.is_file:
            new_folder = ospath.splitext(dl_path)[0]
            if await aiopath.isfile(new_folder):
                new_folder = f"{new_folder}_temp"
            name = ospath.basename(dl_path)
            await makedirs(new_folder, exist_ok=True)
            new_dl_path = f"{new_folder}/{name}"
            await move(dl_path, new_dl_path)
            dl_path = new_dl_path
            up_path = f"{new_dl_path}.zip"
            self.is_file = False
        else:
            up_path = f"{dl_path}.zip"
        sevenz = SevenZ(self)
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Zip")
        return await sevenz.zip(dl_path, up_path, pswd)

    async def proceed_split(self, dl_path, gid):
        self.files_to_proceed = {}
        if self.is_file:
            f_size = await get_path_size(dl_path)
            if f_size > self.split_size:
                self.files_to_proceed[dl_path] = [f_size, ospath.basename(dl_path)]
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    f_size = await get_path_size(f_path)
                    if f_size > self.split_size:
                        self.files_to_proceed[f_path] = [f_size, file_]
        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Split")
            LOGGER.info(f"Splitting: {self.name}")
            for f_path, (f_size, file_) in self.files_to_proceed.items():
                self.proceed_count += 1
                if self.is_file:
                    self.subsize = self.size
                else:
                    self.subsize = f_size
                    self.subname = file_
                parts = -(-f_size // self.split_size)
                if self.equal_splits:
                    split_size = (f_size // parts) + (f_size % parts)
                else:
                    split_size = self.split_size
                if not self.as_doc and (await get_document_type(f_path))[0]:
                    self.progress = True
                    res = await ffmpeg.split(f_path, file_, parts, split_size)
                else:
                    self.progress = False
                    res = await split_file(f_path, split_size, self)
                if self.is_cancelled:
                    return False
                if res or f_size >= self.max_split_size:
                    try:
                        await remove(f_path)
                    except Exception:
                        self.is_cancelled = True

    def parse_metadata_string(self, metadata_str):
        return self.metadata_processor.parse_string(metadata_str)

    def merge_metadata_dicts(self, default_dict, cmd_dict):
        return self.metadata_processor.merge_dicts(default_dict, cmd_dict)
