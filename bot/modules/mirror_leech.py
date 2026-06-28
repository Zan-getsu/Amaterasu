from ast import literal_eval
from base64 import b64encode
from asyncio import sleep
from re import match as re_match

from aiofiles.os import path as aiopath
from bot.core.config_manager import Config
from yt_dlp import YoutubeDL

from .. import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict_lock
from ..helper.ext_utils.bot_utils import (
    COMMAND_USAGE,
    arg_parser,
    get_content_info,
    sync_to_async,
)
from ..helper.ext_utils.exceptions import DirectDownloadLinkException
from ..helper.ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_mega_link,
    is_magnet,
    is_rclone_path,
    is_pixeldrain_link,
    is_telegram_link,
    is_url,
)
from ..helper.ext_utils.task_manager import pre_task_check
from ..helper.listeners.task_listener import TaskListener
from ..helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_link_generator import (
    direct_link_generator,
)
from ..helper.mirror_leech_utils.download_utils.gd_download import add_gd_download
from ..helper.mirror_leech_utils.download_utils.jd_download import add_jd_download
from ..helper.mirror_leech_utils.download_utils.mega_download import add_mega_download
from ..helper.mirror_leech_utils.download_utils.nzb_downloader import add_nzb
from ..helper.mirror_leech_utils.download_utils.qbit_download import add_qb_torrent
from ..helper.mirror_leech_utils.download_utils.rclone_download import (
    add_rclone_download,
)
from ..helper.mirror_leech_utils.download_utils.telegram_download import (
    TelegramDownloadHelper,
)
from ..helper.mirror_leech_utils.download_utils.yt_dlp_download import YoutubeDLHelper
from ..helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    get_tg_link_message,
    send_message,
)


def extract_ytdlp_info(link, options):
    with YoutubeDL(options) as ydl:
        result = ydl.extract_info(link, download=False)
        if result is None:
            raise ValueError("Info result is None")
        return result


def get_ytdlp_extractor(result):
    extractor = result.get("extractor_key") or result.get("extractor") or ""
    if extractor:
        return str(extractor).split(":", 1)[0]
    return ""


def is_generic_ytdlp_result(result):
    extractor = get_ytdlp_extractor(result).lower()
    return not extractor or extractor == "generic"


class Mirror(TaskListener):
    def __init__(
        self,
        client,
        message,
        is_qbit=False,
        is_leech=False,
        is_jd=False,
        is_nzb=False,
        is_uphoster=False,
        same_dir=None,
        bulk=None,
        multi_tag=None,
        options="",
        **kwargs,
    ):
        if same_dir is None:
            same_dir = {}
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multi_tag = multi_tag
        self.options = options
        self.same_dir = same_dir
        self.bulk = bulk
        super().__init__()
        self.is_qbit = is_qbit
        self.is_leech = is_leech
        self.is_jd = is_jd
        self.is_nzb = is_nzb
        self.is_uphoster = is_uphoster

    async def _add_ytdlp_fallback(
        self,
        path,
        forced_name=None,
        force_generic=False,
        fallback_error=None,
        notify_generic_error=True,
        notify_extract_error=True,
    ):
        opt = self.user_dict.get("YT_DLP_OPTIONS") or Config.YT_DLP_OPTIONS or {}
        if not isinstance(opt, dict):
            opt = {}

        cookie_to_use = (
            usr_cookie
            if not self.user_dict.get("USE_DEFAULT_COOKIE", False)
            and (usr_cookie := self.user_dict.get("USER_COOKIE_FILE", ""))
            and await aiopath.exists(usr_cookie)
            else "cookies.txt"
        )
        options = {"usenetrc": True, "cookiefile": cookie_to_use}
        qual = ""
        for key, value in opt.items():
            if key in ["postprocessors", "download_ranges"]:
                continue
            if key == "format" and isinstance(value, str):
                qual = value
            options[key] = value
        options["playlist_items"] = "0"

        try:
            result = await sync_to_async(extract_ytdlp_info, self.link, options)
        except Exception as e:
            msg = str(e).replace("<", " ").replace(">", " ")
            if notify_extract_error:
                await self.on_download_error(msg)
                return None
            self.ytdlp_fallback_error = msg
            return False

        extractor = get_ytdlp_extractor(result) or "unknown"
        if is_generic_ytdlp_result(result) and not force_generic:
            msg = (
                fallback_error
                or "Aria2 could not download this link, and yt-dlp only matched it "
                "as a generic HTTP URL."
            )
            msg = (
                f"{msg}\n\nSkipped automatic yt-dlp fallback to avoid treating a "
                "normal file link as media. Use -yf to force yt-dlp fallback."
            )
            LOGGER.info(
                f"Skipping automatic yt-dlp fallback for generic extractor: {self.link}"
            )
            if notify_generic_error:
                await self.on_download_error(msg)
                return None
            return False

        LOGGER.info(f"Using yt-dlp fallback extractor: {extractor}")
        self.is_ytdlp = True
        self._set_mode_engine()

        playlist = "entries" in result
        ydl = YoutubeDLHelper(self)
        forced_name = forced_name or getattr(self, "ytdlp_fallback_name", "")
        await ydl.add_download(
            path,
            qual or "best/b",
            playlist,
            opt,
            extra_postprocess=False,
            forced_name=forced_name,
        )
        return True

    async def _add_aria2_download_with_fallback(self, path, headers, ratio, seed_time):
        can_fallback = self.link.startswith(("http://", "https://", "ftp://"))
        self.allow_ytdlp_fallback = can_fallback
        self.aria2_fallback_retried = False
        self.ytdlp_fallback_path = path
        self.aria2_fallback_headers = headers
        self.aria2_fallback_ratio = ratio
        self.aria2_fallback_seed_time = seed_time
        self.aria2_fallback_error = ""
        self.aria2_fallback_completed = 0
        aria2_started = await add_aria2_download(
            self,
            path,
            headers,
            ratio,
            seed_time,
            notify_error=not can_fallback,
        )
        if not aria2_started and can_fallback:
            LOGGER.info(
                f"Aria2 could not start download. Retrying before yt-dlp fallback for: {self.link}"
            )
            await self._retry_aria2_or_ytdlp(path)

    async def _retry_aria2_or_ytdlp(self, path):
        if not getattr(self, "aria2_fallback_retried", False):
            self.aria2_fallback_retried = True
            await sleep(5)

            content_type, content_filename = await get_content_info(self.link)
            is_text_response = bool(
                content_type and re_match(r"text/html|text/plain", content_type)
            )
            if content_filename and not self.name and (
                not is_text_response or "." in content_filename
            ):
                self.ytdlp_fallback_name = content_filename

            LOGGER.info(f"Retrying Aria2 before yt-dlp fallback for: {self.link}")
            self.allow_ytdlp_fallback = True
            aria2_started = await add_aria2_download(
                self,
                path,
                getattr(self, "aria2_fallback_headers", ""),
                getattr(self, "aria2_fallback_ratio", None),
                getattr(self, "aria2_fallback_seed_time", None),
                notify_error=False,
            )
            if aria2_started:
                return

        force_generic = getattr(self, "force_ytdlp_fallback", False)
        if not force_generic and getattr(self, "aria2_fallback_completed", 0) > 0:
            error = getattr(self, "aria2_fallback_error", "Aria2 download failed.")
            await self.on_download_error(
                f"{error}\n\nSkipped yt-dlp fallback because aria2 already started "
                "receiving data. Use -yf to force yt-dlp fallback."
            )
            return

        LOGGER.info(f"Aria2 retry failed. Falling back to yt-dlp for: {self.link}")
        self.allow_ytdlp_fallback = False
        await self._add_ytdlp_fallback(
            path,
            force_generic=force_generic,
            fallback_error=getattr(self, "aria2_fallback_error", None),
        )

    async def new_event(self):


        text = self.message.text.split("\n")
        input_list = text[0].split(" ")

        check_msg, check_button = await pre_task_check(self.message)
        if check_msg:
            await delete_links(self.message)
            await auto_delete_message(
                await send_message(self.message, check_msg, check_button)
            )
            return

        args = {
            "-doc": False,
            "-med": False,
            "-d": False,
            "-j": False,
            "-s": False,
            "-b": False,
            "-e": False,
            "-z": False,
            "-sv": False,
            "-ss": False,
            "-f": False,
            "-fd": False,
            "-fu": False,
            "-hl": False,
            "-bt": False,
            "-ut": False,
            "-yt": False,
            "-yf": False,
            "-ytdlp-fallback": False,
            "-i": 0,
            "-sp": 0,
            "link": "",
            "-n": "",
            "-m": "",
            "-meta": "",
            "-up": "",
            "-gc": "",
            "-rcf": "",
            "-au": "",
            "-ap": "",
            "-h": "",
            "-t": "",
            "-ca": "",
            "-cv": "",
            "-ns": "",
            "-tl": "",
            "-en": False,
            "-enmeta": "",
            "-ff": set(),
            # Phase 3.2 — parallel multi-source download. Pass multiple
            # space-separated URLs after --multi and aria2 will download
            # the same file from all sources in parallel (mirror mode).
            # Example: /mirror --multi url1 url2 url3
            "--multi": "",
            # Phase 4.1 — sequential torrent streaming flag. When set,
            # torrent pieces are downloaded in order so the file can be
            # streamed while still downloading.
            "--stream": False,
            # Phase 4.3 — cloud-to-cloud transfer flag. When set, both
            # source and destination must be rclone remotes.
            "--c2c": False,
        }

        arg_parser(input_list[1:], args)

        if Config.DISABLE_BULK and args.get("-b", False):
            await send_message(self.message, "Bulk downloads are currently disabled.")
            return

        if Config.DISABLE_MULTI and int(args.get("-i", 1)) > 1:
            await send_message(
                self.message,
                "Multi-downloads are currently disabled. Please try without the -i flag.",
            )
            return

        if Config.DISABLE_SEED and args.get("-d", False):
            await send_message(
                self.message,
                "Seeding is currently disabled. Please try without the -d flag.",
            )
            return

        if Config.DISABLE_FF_MODE and args.get("-ff"):
            await send_message(self.message, "FFmpeg commands are currently disabled.")
            return
        if Config.DISABLE_ENCODE and args.get("-en"):
            await send_message(self.message, "Encoding is currently disabled.")
            return

        from .. import sudo_users, user_data
        user = self.message.from_user or self.message.sender_chat
        is_sudo = user.id == Config.OWNER_ID or user.id in sudo_users or user_data.get(user.id, {}).get("SUDO")
        if args.get("-en") and not is_sudo:
            await send_message(self.message, "Encoding is restricted to sudo users only.")
            return

        self.select = args["-s"]
        self.seed = args["-d"]
        self.name = args["-n"]
        self.up_dest = args["-up"]
        self.category = args["-gc"]
        self.rc_flags = args["-rcf"]
        self.link = args["link"]
        self.compress = args["-z"]
        self.extract = args["-e"]
        self.join = args["-j"]
        self.thumb = args["-t"]
        self.split_size = args["-sp"]
        self.sample_video = args["-sv"]
        self.screen_shots = args["-ss"]
        self.force_run = args["-f"]
        self.force_download = args["-fd"]
        self.force_upload = args["-fu"]
        self.convert_audio = args["-ca"]
        self.convert_video = args["-cv"]
        self.name_swap = args["-ns"]
        self.hybrid_leech = args["-hl"]
        self.thumbnail_layout = args["-tl"]
        self.as_doc = args["-doc"]
        self.as_med = args["-med"]
        self.folder_name = f"/{args['-m']}".rstrip("/") if len(args["-m"]) > 0 else ""
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.is_yt = args["-yt"]
        self.force_ytdlp_fallback = args["-yf"] or args["-ytdlp-fallback"]
        self.is_encode = args["-en"]
        self.encode_metadata = args["-enmeta"]
        # Phase 3.2 — parallel multi-source download. Parse the --multi
        # flag value (space-separated URLs) into a list. The first URL
        # is the primary (listener.link); the rest are additional mirrors
        # that aria2 downloads in parallel.
        self.multi_urls = []
        if args.get("--multi"):
            self.multi_urls = [u.strip() for u in args["--multi"].split() if u.strip()]
        # Phase 4.1 — sequential torrent streaming flag
        self.is_stream = args.get("--stream", False)
        # Phase 4.3 — cloud-to-cloud transfer flag
        self.is_c2c = args.get("--c2c", False)
        self.metadata_dict = self.default_metadata_dict.copy()
        self.audio_metadata_dict = self.audio_metadata_dict.copy()
        self.video_metadata_dict = self.video_metadata_dict.copy()
        self.subtitle_metadata_dict = self.subtitle_metadata_dict.copy()
        if args["-meta"]:
            meta = self.metadata_processor.parse_string(args["-meta"])
            self.metadata_dict = self.metadata_processor.merge_dicts(
                self.metadata_dict, meta
            )

        headers = args["-h"]
        is_bulk = args["-b"]

        bulk_start = 0
        bulk_end = 0
        ratio = None
        seed_time = None
        reply_to = None
        file_ = None
        session = ""
        use_ytdlp_fallback = False
        retry_aria2_after_generic = False
        ytdlp_fallback_error = ""
        ytdlp_fallback_name = ""

        try:
            self.multi = int(args["-i"])
        except Exception:
            self.multi = 0

        try:
            if args["-ff"]:
                if isinstance(args["-ff"], set):
                    self.ffmpeg_cmds = args["-ff"]
                else:
                    value = literal_eval(args["-ff"])
                    if not isinstance(value, (dict, set, list, tuple)):
                        raise ValueError("ffmpeg_cmds must be a dict/set/list/tuple")
                    self.ffmpeg_cmds = value
        except Exception as e:
            self.ffmpeg_cmds = None
            LOGGER.error(e)

        if not isinstance(self.seed, bool):
            dargs = self.seed.split(":")
            ratio = dargs[0] or None
            if len(dargs) == 2:
                seed_time = dargs[1] or None
            self.seed = True

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = dargs[0] or 0
            if len(dargs) == 2:
                bulk_end = dargs[1] or 0
            is_bulk = True

        if not is_bulk:
            if self.multi > 0:
                if self.folder_name:
                    async with task_dict_lock:
                        if self.folder_name in self.same_dir:
                            self.same_dir[self.folder_name]["tasks"].add(self.mid)
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        elif self.same_dir:
                            self.same_dir[self.folder_name] = {
                                "total": self.multi,
                                "tasks": {self.mid},
                            }
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        else:
                            self.same_dir = {
                                self.folder_name: {
                                    "total": self.multi,
                                    "tasks": {self.mid},
                                }
                            }
                elif self.same_dir:
                    async with task_dict_lock:
                        for fd_name in self.same_dir:
                            self.same_dir[fd_name]["total"] -= 1
        else:
            await self.init_bulk(input_list, bulk_start, bulk_end, Mirror)
            return

        if len(self.bulk) != 0:
            del self.bulk[0]

        await self.run_multi(input_list, Mirror)

        await self.get_tag(text)

        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"

        if not self.link and (reply_to := self.message.reply_to_message):
            if reply_to.text:
                self.link = reply_to.text.split("\n", 1)[0].strip()
        if is_telegram_link(self.link):
            try:
                reply_to, session = await get_tg_link_message(self.link)
            except Exception as e:
                await send_message(self.message, f"ERROR: {e}")
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return

        if isinstance(reply_to, list):
            self.bulk = reply_to
            b_msg = input_list[:1]
            self.options = " ".join(input_list[1:])
            b_msg.append(f"{self.bulk[0]} -i {len(self.bulk)} {self.options}")
            nextmsg = await send_message(self.message, " ".join(b_msg))
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id, message_ids=nextmsg.id
            )
            if self.message.from_user:
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user
            await Mirror(
                self.client,
                nextmsg,
                self.is_qbit,
                self.is_leech,
                self.is_jd,
                self.is_nzb,
                self.is_uphoster,
                self.same_dir,
                self.bulk,
                self.multi_tag,
                self.options,
            ).new_event()
            return

        if reply_to:
            file_ = (
                reply_to.document
                or reply_to.photo
                or reply_to.video
                or reply_to.audio
                or reply_to.voice
                or reply_to.video_note
                or reply_to.sticker
                or reply_to.animation
                or None
            )
            self.file_details = {"caption": reply_to.caption}

            if file_ is None:
                if reply_text := reply_to.text:
                    self.link = reply_text.split("\n", 1)[0].strip()
                else:
                    reply_to = None
            elif reply_to.document and (
                file_.mime_type == "application/x-bittorrent"
                or file_.file_name.endswith((".torrent", ".dlc", ".nzb"))
            ):
                self.link = await reply_to.download()
                file_ = None

        if (
            not self.link
            and file_ is None
            or is_telegram_link(self.link)
            and reply_to is None
            or file_ is None
            and not is_url(self.link)
            and not is_magnet(self.link)
            and not await aiopath.exists(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_id(self.link)
            and not is_gdrive_link(self.link)
            and not is_mega_link(self.link)
        ):
            await send_message(
                self.message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][1]
            )
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        if len(self.link) > 0:
            LOGGER.info(self.link)

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        self._set_mode_engine()

        # Phase 3.3 — Smart engine selection is already handled by the
        # existing URL pattern checks below (is_magnet, is_rclone_path,
        # is_gdrive_link, is_mega_link, etc.). The engine_selector.py
        # module (Phase 2.7) provides a cleaner abstraction for fallback
        # chains and is used by the engine_health integration. No new
        # commands — /mirror and /leech auto-detect the engine when no
        # explicit flag (/qbmirror, /jdmirror, etc.) is given.
        if (
            not self.is_jd
            and not self.is_nzb
            and not self.is_qbit
            and not is_magnet(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_link(self.link)
            and not self.link.endswith(".torrent")
            and file_ is None
            and not is_gdrive_id(self.link)
            and not is_mega_link(self.link)
        ):
            content_type, content_filename = await get_content_info(self.link)
            is_text_response = bool(
                content_type and re_match(r"text/html|text/plain", content_type)
            )
            if content_filename and not self.name and (
                not is_text_response or "." in content_filename
            ):
                ytdlp_fallback_name = content_filename
            if (
                is_pixeldrain_link(self.link)
                or content_type is None
                or is_text_response
            ):
                try:
                    self.link = await sync_to_async(direct_link_generator, self.link)
                    if isinstance(self.link, tuple):
                        self.link, headers = self.link
                    elif isinstance(self.link, str):
                        LOGGER.info(f"Generated link: {self.link}")
                except DirectDownloadLinkException as e:
                    e = str(e)
                    if "This link requires a password!" in e:
                        await send_message(self.message, e)
                        await self.remove_from_same_dir()
                        await delete_links(self.message)
                        return
                    no_direct_link = e.startswith("No Direct link function found")
                    if no_direct_link:
                        LOGGER.info(
                            f"{e}. Checking yt-dlp for a real extractor; "
                            f"generic matches will fall back to aria2: {self.link}"
                        )
                    else:
                        LOGGER.info(f"{e}. Checking yt-dlp fallback for: {self.link}")
                    use_ytdlp_fallback = True
                    retry_aria2_after_generic = no_direct_link or content_type is None
                    ytdlp_fallback_error = e
                except Exception as e:
                    await send_message(self.message, e)
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return

        await delete_links(self.message)
        self.ytdlp_fallback_name = ytdlp_fallback_name

        ussr = args["-au"]
        pssw = args["-ap"]
        if ussr or pssw:
            auth = f"{ussr}:{pssw}"
            headers += (
                f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
            )

        if file_ is not None:
            await TelegramDownloadHelper(self).add_download(
                reply_to, f"{path}/", session
            )
        elif use_ytdlp_fallback:
            ytdlp_started = await self._add_ytdlp_fallback(
                path,
                ytdlp_fallback_name,
                force_generic=self.force_ytdlp_fallback,
                fallback_error=ytdlp_fallback_error,
                notify_generic_error=False,
                notify_extract_error=False,
            )
            if ytdlp_started is not False:
                return
            if self.force_ytdlp_fallback and getattr(self, "ytdlp_fallback_error", ""):
                await self.on_download_error(self.ytdlp_fallback_error)
                return
            if not retry_aria2_after_generic:
                fallback_detail = getattr(
                    self, "ytdlp_fallback_error", "yt-dlp only matched a generic HTTP URL"
                )
                await self.on_download_error(
                    f"{ytdlp_fallback_error}\n\nSkipped automatic yt-dlp fallback "
                    f"because {fallback_detail}. Use -yf to force yt-dlp fallback."
                )
                return
            LOGGER.info(
                f"yt-dlp fallback did not start. Trying aria2 for: {self.link}"
            )
            await self._add_aria2_download_with_fallback(
                path, headers, ratio, seed_time
            )
        elif isinstance(self.link, dict):
            await add_direct_download(self, path)
        elif self.is_jd:
            await add_jd_download(self, path)
        elif self.is_qbit:
            await add_qb_torrent(self, path, ratio, seed_time)
        elif self.is_nzb:
            await add_nzb(self, path)
        elif is_rclone_path(self.link):
            await add_rclone_download(self, f"{path}/")
        elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
            await add_gd_download(self, path)
        elif is_mega_link(self.link):
            await add_mega_download(self, f"{path}/")
        elif getattr(self, "is_c2c", False):
            # Phase 4.3 — cloud-to-cloud transfer. Both source and dest
            # are rclone remotes — no local download. The link is the
            # source; the upload destination (self.up_dest) is the dest.
            from ..helper.mirror_leech_utils.rclone_utils.transfer import (
                RcloneTransferHelper,
            )
            dest = self.up_dest or self.link  # fallback to same remote if no dest
            # If up_dest is not set, we need a destination. For c2c, the
            # command format is: /mirror --c2c source_remote:path dest_remote:path
            # The link is the source; the second arg is in -up.
            if not self.up_dest:
                await send_message(
                    self.message,
                    "Cloud-to-cloud transfer requires a destination. "
                    "Use: /mirror --c2c source_remote:path -up dest_remote:path",
                )
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return
            rc_helper = RcloneTransferHelper(self)
            await rc_helper.c2c_transfer(self.link, self.up_dest)
        else:
            await self._add_aria2_download_with_fallback(
                path, headers, ratio, seed_time
            )


async def mirror(client, message):
    bot_loop.create_task(Mirror(client, message).new_event())


async def qb_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_qbit=True).new_event())


async def jd_mirror(client, message):
    if Config.DISABLE_JD:
        await message.reply("JDownloader is currently disabled by the Bot Owner.")
        return
    bot_loop.create_task(Mirror(client, message, is_jd=True).new_event())


async def nzb_mirror(client, message):
    if Config.DISABLE_NZB:
        await message.reply("SABnzbd is currently disabled by the Bot Owner.")
        return
    text_parts = message.text.split()
    nzb_id = None
    if len(text_parts) > 1 and not text_parts[1].startswith(("http", "ftp", "/")):
        potential_id = text_parts[1]
        clean = potential_id.lstrip("-").replace("_", "")
        if clean.isalnum() and not (potential_id.startswith("-") and clean.isalpha()):
            nzb_id = potential_id
            nzb_url = f"{Config.HYDRA_IP.rstrip('/')}/getnzb/api/{nzb_id}?apikey={Config.HYDRA_API_KEY}"
            extra = " ".join(text_parts[2:])
            message.text = f"/nzbmirror {nzb_url} -e {extra}".strip()
    else:
        if "-e" not in message.text:
            message.text += " -e"
    mirror_task = Mirror(client, message, is_nzb=True)
    if nzb_id:
        mirror_task.nzb_id = nzb_id
    bot_loop.create_task(mirror_task.new_event())


async def leech(client, message):
    if Config.DISABLE_LEECH:
        await message.reply("The Leech command is currently disabled.")
        return
    bot_loop.create_task(Mirror(client, message, is_leech=True).new_event())


async def qb_leech(client, message):
    bot_loop.create_task(
        Mirror(client, message, is_qbit=True, is_leech=True).new_event()
    )


async def jd_leech(client, message):
    if Config.DISABLE_JD:
        await message.reply("JDownloader is currently disabled by the Bot Owner.")
        return
    bot_loop.create_task(Mirror(client, message, is_leech=True, is_jd=True).new_event())


async def nzb_leech(client, message):
    if Config.DISABLE_NZB:
        await message.reply("SABnzbd is currently disabled by the Bot Owner.")
        return
    text_parts = message.text.split()
    nzb_id = None
    if len(text_parts) > 1 and not text_parts[1].startswith(("http", "ftp", "/")):
        potential_id = text_parts[1]
        clean = potential_id.lstrip("-").replace("_", "")
        if clean.isalnum() and not (potential_id.startswith("-") and clean.isalpha()):
            nzb_id = potential_id
            nzb_url = f"{Config.HYDRA_IP.rstrip('/')}/getnzb/api/{nzb_id}?apikey={Config.HYDRA_API_KEY}"
            extra = " ".join(text_parts[2:])
            message.text = f"/nzbleech {nzb_url} -e {extra}".strip()
    else:
        if "-e" not in message.text:
            message.text += " -e"
    mirror_task = Mirror(client, message, is_leech=True, is_nzb=True)
    if nzb_id:
        mirror_task.nzb_id = nzb_id
    bot_loop.create_task(mirror_task.new_event())


async def uphoster(client, message):
    bot_loop.create_task(Mirror(client, message, is_uphoster=True).new_event())
