from asyncio import CancelledError, ensure_future, gather, sleep
from logging import getLogger
from os import path as ospath, walk
from re import match as re_match, sub as re_sub
from time import time

from aioshutil import rmtree
from natsort import natsorted
from PIL import Image
from pyrogram import StopTransmission
from pyrogram.errors import BadRequest, FloodWait, RPCError
try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait
from pyrogram.raw.types import (
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
)
from aiofiles.os import (
    path as aiopath,
    remove,
    rename,
)
from pyrogram.types import (
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ...ext_utils.hyperup_utils import HypertgUpload
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.files_utils import get_base_name, is_archive
from ...ext_utils.status_utils import get_readable_file_size, get_readable_time
from ...telegram_helper.message_utils import send_message
from ...ext_utils.media_utils import (
    get_audio_thumbnail,
    get_document_type,
    get_media_info,
    get_multiple_frames_thumbnail,
    get_video_thumbnail,
    get_md5_hash,
    generate_telegraph_mediainfo,
)
from ...telegram_helper.button_build import ButtonMaker
from ...telegram_helper.message_utils import delete_message

LOGGER = getLogger(__name__)


class TelegramUploader:
    def __init__(self, listener, path):
        self._last_uploaded = 0
        self._processed_bytes = 0
        self._completed_bytes = 0
        self._is_finalizing_upload = False
        self._listener = listener
        self._path = path
        self._client = None
        self._start_time = time()
        self._total_files = 0
        self._thumb = self._listener.thumb or f"thumbnails/{listener.user_id}.jpg"
        self._msgs_dict = {}
        self._corrupted = 0
        self._is_corrupted = False
        self._media_dict = {"videos": {}, "documents": {}}
        self._last_msg_in_group = False
        self._up_path = ""
        self._lprefix = ""
        self._lsuffix = ""
        self._lcaption = ""
        self._lfont = ""
        self._bot_pm = False
        self._media_group = False
        self._is_private = False
        self._sent_msg = None
        self._log_msg = None
        self._user_session = self._listener.transmission_mode in ("user", "both")
        self._error = ""
        self._upload_tasks = []
        self._hu = HypertgUpload(self) if Config.USE_HYPER and Config.LEECH_DUMP_CHAT else None

    async def _upload_progress(self, current, total):
        if self._listener.is_cancelled:
            client = TgClient.user if self._user_session else self._listener.client
            client.stop_transmission()
            raise StopTransmission()
        current = max(0, current)
        total = total or current
        self._last_uploaded = current
        self._processed_bytes = self._completed_bytes + min(current, total)
        self._is_finalizing_upload = total > 0 and current >= total

    async def _reset_upload_attempt(self, path):
        self._last_uploaded = 0
        self._processed_bytes = self._completed_bytes
        self._is_finalizing_upload = False

    async def _user_settings(self):
        settings_map = {
            "MEDIA_GROUP": ("_media_group", False),
            "BOT_PM": ("_bot_pm", False),
            "LEECH_PREFIX": ("_lprefix", ""),
            "LEECH_SUFFIX": ("_lsuffix", ""),
            "LEECH_CAPTION": ("_lcaption", ""),
            "LEECH_FONT": ("_lfont", ""),
        }

        for key, (attr, default) in settings_map.items():
            setattr(
                self,
                attr,
                self._listener.user_dict.get(key) or getattr(Config, key, default),
            )

        if self._thumb != "none" and not await aiopath.exists(self._thumb):
            self._thumb = None

    async def _msg_to_reply(self):
        if self._listener.up_dest:
            msg_link = (
                self._listener.message.link if self._listener.is_super_chat else ""
            )
            msg_link_text = f"\n┠ <b>Message Link :</b> <a href='{msg_link}'>Click Here</a>" if msg_link else ""
            msg = f"""➲ <b><u>Leech Started :</u></b>
┃
┠ <b>User :</b> {self._listener.user.mention} ( #ID{self._listener.user_id} ){msg_link_text}
┖ <b>Source :</b> <a href='{self._listener.source_url}'>Click Here</a>"""
            try:
                self._log_msg = await TgClient.bot.send_message(
                    chat_id=self._listener.up_dest,
                    text=msg,
                    disable_web_page_preview=True,
                    message_thread_id=self._listener.chat_thread_id,
                    disable_notification=True,
                )
                self._sent_msg = self._log_msg
                if self._user_session:
                    self._sent_msg = await TgClient.user.get_messages(
                        chat_id=self._sent_msg.chat.id,
                        message_ids=self._sent_msg.id,
                    )
                else:
                    self._is_private = self._sent_msg.chat.type.name == "PRIVATE"
                if self._listener.leech_dest:
                    try:
                        leech_dest = self._listener.leech_dest
                        if not isinstance(leech_dest, int):
                            if "|" in str(leech_dest):
                                leech_dest, _ = str(leech_dest).split("|", 1)
                            if leech_dest.lstrip("-").isdigit():
                                leech_dest = int(leech_dest)
                        if self._log_msg.chat.id != leech_dest:
                            await self._log_msg.copy(chat_id=leech_dest)
                    except Exception as e:
                        if not self._listener.is_cancelled:
                            LOGGER.error(
                                f"Failed to copy 'Leech Started' message to {self._listener.leech_dest}: {e}"
                            )
                            await send_message(
                                self._listener.user_id,
                                f"Failed to send 'Leech Started' message to {self._listener.leech_dest}\n{e}",
                            )
            except Exception as e:
                await self._listener.on_upload_error(str(e))
                return False

        elif self._user_session:
            self._sent_msg = await TgClient.user.get_messages(
                chat_id=self._listener.message.chat.id, message_ids=self._listener.mid
            )
            if self._sent_msg is None:
                self._sent_msg = await TgClient.user.send_message(
                    chat_id=self._listener.message.chat.id,
                    text="Deleted Cmd Message! Don't delete the cmd message again!",
                    disable_web_page_preview=True,
                    disable_notification=True,
                )
        else:
            self._sent_msg = self._listener.message
        return True

    async def _prepare_file(self, pre_file_, dirpath):
        cap_file_ = file_ = pre_file_
        lprefix = self._lprefix
        lsuffix = self._lsuffix
        lcaption = self._lcaption

        if lprefix:
            cap_file_ = lprefix.replace(r"\s", " ") + file_
            lprefix = re_sub(r"<.*?>", "", lprefix).replace(r"\s", " ")
            if not file_.startswith(lprefix):
                file_ = f"{lprefix}{file_}"

        if lsuffix:
            name, ext = ospath.splitext(cap_file_)
            cap_file_ = name + lsuffix.replace(r"\s", " ") + ext
            lsuffix = re_sub(r"<.*?>", "", lsuffix).replace(r"\s", " ")

        cap_mono = (
            f"<{Config.LEECH_FONT}>{cap_file_}</{Config.LEECH_FONT}>"
            if Config.LEECH_FONT
            else cap_file_
        )
        if lcaption:
            lcaption = re_sub(
                r"(\\\||\\\{|\\\}|\\s)",
                lambda m: {r"\|": "%%", r"\{": "&%&", r"\}": "$%$", r"\s": " "}[
                    m.group(0)
                ],
                lcaption,
            )

            parts = lcaption.split("|")
            parts[0] = re_sub(
                r"\{([^}]+)\}", lambda m: f"{{{m.group(1).lower()}}}", parts[0]
            )
            up_path = ospath.join(dirpath, pre_file_)
            dur, qual, lang, subs = await get_media_info(up_path, True)
            class SafeDict(dict):
                def __missing__(self, key):
                    return f"{{{key}}}"

            cap_mono = parts[0].format_map(SafeDict(
                filename=cap_file_,
                size=get_readable_file_size(await aiopath.getsize(up_path)),
                duration=get_readable_time(dur),
                quality=qual,
                languages=lang,
                subtitles=subs,
                md5_hash=await sync_to_async(get_md5_hash, up_path),
                mime_type=self._listener.file_details.get("mime_type", "text/plain"),
                prefilename=self._listener.file_details.get("filename", ""),
                precaption=self._listener.file_details.get("caption", ""),
            ))

            for part in parts[1:]:
                args = part.split(":")
                cap_mono = cap_mono.replace(
                    args[0],
                    args[1] if len(args) > 1 else "",
                    int(args[2]) if len(args) == 3 else -1,
                )
            cap_mono = re_sub(
                r"%%|&%&|\$%\$",
                lambda m: {"%%": "|", "&%&": "{", "$%$": "}"}[m.group()],
                cap_mono,
            )

        if len(file_) > 60:
            if is_archive(file_):
                name = get_base_name(file_)
                ext = file_.split(name, 1)[1]
            elif match := re_match(r".+(?=\..+\.0*\d+$)|.+(?=\.part\d+\..+$)", file_):
                name = match.group(0)
                ext = file_.split(name, 1)[1]
            elif len(fsplit := ospath.splitext(file_)) > 1:
                name = fsplit[0]
                ext = fsplit[1]
            else:
                name = file_
                ext = ""
            if lsuffix:
                ext = f"{lsuffix}{ext}"
            name = name[: 64 - len(ext)]
            file_ = f"{name}{ext}"
        elif lsuffix:
            name, ext = ospath.splitext(file_)
            file_ = f"{name}{lsuffix}{ext}"

        old_path = ospath.join(dirpath, pre_file_)
        new_path = ospath.join(dirpath, file_)
        if old_path != new_path:
            await rename(old_path, new_path)

        return new_path, cap_mono

    def _get_input_media(self, subkey, key):
        rlist = []
        for msg in self._media_dict[key][subkey]:
            if key == "videos":
                input_media = InputMediaVideo(
                    media=msg.video.file_id, caption=msg.caption
                )
            elif key == "audios" and msg.audio:
                input_media = InputMediaDocument(
                    media=msg.audio.file_id, caption=msg.caption
                )
            else:
                input_media = InputMediaDocument(
                    media=msg.document.file_id, caption=msg.caption
                )
            rlist.append(input_media)
        return rlist

    async def _send_screenshots(self, dirpath, outputs):
        inputs = [
            InputMediaPhoto(ospath.join(dirpath, p), p.rsplit("/", 1)[-1])
            for p in outputs
        ]
        for i in range(0, len(inputs), 10):
            batch = inputs[i : i + 10]
            if Config.BOT_PM and self._sent_msg.chat.id != self._listener.user_id:
                await TgClient.bot.send_media_group(
                    chat_id=self._listener.user_id,
                    media=batch,
                    disable_notification=True,
                )
            self._sent_msg = (
                await self._sent_msg.reply_media_group(
                    media=batch,
                    quote=True,
                    disable_notification=True,
                )
            )[-1]

    async def _send_media_group(self, subkey, key, msgs):
        for index, msg in enumerate(msgs):
            if self._listener.transmission_mode == "both" or not self._user_session:
                msgs[index] = await self._listener.client.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
            else:
                msgs[index] = await TgClient.user.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
        msgs_list = await msgs[0].reply_to_message.reply_media_group(
            media=self._get_input_media(subkey, key),
            quote=True,
            disable_notification=True,
        )
        for msg in msgs:
            link = f"https://t.me/pm/{msg.chat.id}/{msg.id}" if self._is_private else msg.link
            if link in self._msgs_dict:
                del self._msgs_dict[link]
            await delete_message(msg)
        del self._media_dict[key][subkey]
        if self._listener.is_super_chat or self._listener.up_dest or self._is_private:
            for m in msgs_list:
                link = f"https://t.me/pm/{m.chat.id}/{m.id}" if self._is_private else m.link
                self._msgs_dict[link] = m.caption
        self._sent_msg = msgs_list[-1]

    async def _copy_media(self):
        try:
            if self._bot_pm and self._sent_msg.chat.id != self._listener.user_id:
                buttons = ButtonMaker()
                if getattr(self, '_telegraph_url', None):
                    buttons.url_button("ℹ️ MediaInfo", self._telegraph_url)
                else:
                    buttons.data_button("ℹ️ MediaInfo", "minfo")
                await TgClient.bot.copy_message(
                    chat_id=self._listener.user_id,
                    from_chat_id=self._sent_msg.chat.id,
                    message_id=self._sent_msg.id,
                    reply_to_message_id=(
                        self._listener.pm_msg.id if self._listener.pm_msg else None
                    ),
                    reply_markup=buttons.build_menu(1) if not self._sent_msg.photo else None
                )
        except Exception as err:
            if not self._listener.is_cancelled:
                LOGGER.error(f"Failed To Send in BotPM:\n{str(err)}")

    async def _upload_file_task(self, file_, f_path, dirpath):
        up_path = None
        try:
            up_path, cap_mono = await self._prepare_file(file_, dirpath)
            sent = await self._upload_file(cap_mono, file_, up_path)
            if sent and not self._is_corrupted:
                self._completed_bytes += await aiopath.getsize(up_path)
                self._processed_bytes = self._completed_bytes
                self._is_finalizing_upload = False
                if self._listener.is_super_chat or self._listener.up_dest:
                    if not self._is_private:
                        self._msgs_dict[sent.link] = file_
            return sent
        except (StopTransmission, CancelledError):
            return None
        except Exception as err:
            if self._listener.is_cancelled:
                return None
            self._is_finalizing_upload = False
            is_retry_error = isinstance(err, RetryError)
            if isinstance(err, RetryError):
                LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err_msg = str(err) or repr(err)
            LOGGER.error(f"{err_msg}. Path: {f_path}", exc_info=not is_retry_error)
            self._error = err_msg
            self._corrupted += 1
            return None
        finally:
            path_to_clean = up_path or f_path
            if not self._listener.is_cancelled and await aiopath.exists(path_to_clean):
                await remove(path_to_clean)

    async def upload(self):
        await self._user_settings()
        res = await self._msg_to_reply()
        if not res:
            return
        is_log_del = False
        self._upload_tasks = []
        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.strip().endswith("/yt-dlp-thumb"):
                continue
            if dirpath.strip().endswith("_mltbss"):
                await self._send_screenshots(dirpath, files)
                await rmtree(dirpath, ignore_errors=True)
                continue
            for file_ in natsorted(files):
                self._error = ""
                f_path = ospath.join(dirpath, file_)
                if not await aiopath.exists(f_path):
                    LOGGER.error(f"{f_path} not exists! Continue uploading!")
                    continue
                try:
                    f_size = await aiopath.getsize(f_path)
                    self._total_files += 1
                    if f_size == 0:
                        LOGGER.error(
                            f"{f_path} size is zero, telegram don't upload zero size files"
                        )
                        self._corrupted += 1
                        continue
                    if self._listener.is_cancelled:
                        return
                    if self._last_msg_in_group:
                        group_lists = [
                            x for v in self._media_dict.values() for x in v.keys()
                        ]
                        match = re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", f_path)
                        if not match or match and match.group(0) not in group_lists:
                            for key, value in list(self._media_dict.items()):
                                for subkey, msgs in list(value.items()):
                                    if len(msgs) > 1:
                                        await self._send_media_group(subkey, key, msgs)
                    if self._listener.transmission_mode == "both":
                        # Phase 4.8 — use premium-aware split size. If the
                        # bot account has premium (Config.IS_PREMIUM_BOT),
                        # files up to 4 GB can be sent without the user
                        # session. Otherwise, fall back to user session for
                        # files > 2 GB (the standard bot limit).
                        from ... import Config as _Config
                        premium_limit = 4 * 1024 * 1024 * 1024  # 4 GB
                        standard_limit = 2097152000  # 2 GB
                        if getattr(_Config, "IS_PREMIUM_BOT", False):
                            self._user_session = f_size > premium_limit
                        else:
                            self._user_session = f_size > standard_limit
                        if self._user_session:
                            self._sent_msg = await TgClient.user.get_messages(
                                chat_id=self._sent_msg.chat.id,
                                message_ids=self._sent_msg.id,
                            )
                        else:
                            self._sent_msg = await self._listener.client.get_messages(
                                chat_id=self._sent_msg.chat.id,
                                message_ids=self._sent_msg.id,
                            )
                    self._last_msg_in_group = False
                    task = ensure_future(
                        self._upload_file_task(file_, f_path, dirpath)
                    )
                    self._upload_tasks.append(task)
                    await task
                    if self._log_msg and not is_log_del and Config.CLEAN_LOG_MSG:
                        await delete_message(self._log_msg)
                        is_log_del = True
                    if self._listener.is_cancelled:
                        return
                except Exception as err:
                    err_msg = str(err) or repr(err)
                    LOGGER.error(f"{err_msg}. Path: {f_path}", exc_info=True)
                    self._error = err_msg
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        return
        await sleep(1)
        for key, value in list(self._media_dict.items()):
            for subkey, msgs in list(value.items()):
                if len(msgs) > 1:
                    try:
                        await self._send_media_group(subkey, key, msgs)
                    except Exception as e:
                        LOGGER.info(
                            f"While sending media group at the end of task. Error: {e}"
                        )
        if self._listener.is_cancelled:
            return
        if self._total_files == 0:
            await self._listener.on_upload_error(
                "No files to upload. In case you have filled EXCLUDED_EXTENSIONS, then check if all files have those extensions or not."
            )
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return
        LOGGER.info(f"Leech Completed: {self._listener.name}")
        await self._listener.on_upload_complete(
            None, self._msgs_dict, self._total_files, self._corrupted
        )
        return

    async def _hyperul_upload(self, cap_mono, file, thumb, key, f_path=None, duration=0, width=0, height=0, artist="", title=""):
        if self._listener.is_cancelled:
            raise StopTransmission()
        attr_base = [DocumentAttributeFilename(file_name=file)]
        if key == "videos":
            attrs = [
                DocumentAttributeVideo(
                    duration=duration or 0, w=width or 480, h=height or 320, supports_streaming=True
                ),
                *attr_base,
            ]
            mtype = "video"
        elif key == "audios":
            attrs = [
                DocumentAttributeAudio(
                    duration=duration or 0, performer=artist or "", title=title or ""
                ),
                *attr_base,
            ]
            mtype = "audio"
        elif key == "documents":
            attrs = attr_base
            mtype = "document"
        else:
            mtype = "photo"
            attrs = None
        target_client = TgClient.user if self._user_session else self._listener.client
        upload_path = f_path or self._up_path
        LOGGER.info(
            f"Telegram upload started: {file} as {mtype} "
            f"via {'HyperTG' if self._hu else 'Pyrogram'}"
        )
        try:
            if self._hu is None:
                if key == "videos":
                    upload_coro = target_client.send_video(
                        chat_id=self._sent_msg.chat.id,
                        video=upload_path,
                        caption=cap_mono,
                        duration=duration or 0,
                        width=width or 480,
                        height=height or 320,
                        thumb=thumb if thumb and thumb != "none" else None,
                        supports_streaming=True,
                        disable_notification=True,
                        reply_to_message_id=self._sent_msg.id,
                        progress=self._upload_progress,
                    )
                elif key == "audios":
                    upload_coro = target_client.send_audio(
                        chat_id=self._sent_msg.chat.id,
                        audio=upload_path,
                        caption=cap_mono,
                        duration=duration or 0,
                        performer=artist or "",
                        title=title or "",
                        thumb=thumb if thumb and thumb != "none" else None,
                        disable_notification=True,
                        reply_to_message_id=self._sent_msg.id,
                        progress=self._upload_progress,
                    )
                elif key == "documents":
                    upload_coro = target_client.send_document(
                        chat_id=self._sent_msg.chat.id,
                        document=upload_path,
                        caption=cap_mono,
                        thumb=thumb if thumb and thumb != "none" else None,
                        disable_content_type_detection=True,
                        disable_notification=True,
                        reply_to_message_id=self._sent_msg.id,
                        progress=self._upload_progress,
                    )
                else:
                    upload_coro = target_client.send_photo(
                        chat_id=self._sent_msg.chat.id,
                        photo=upload_path,
                        caption=cap_mono,
                        disable_notification=True,
                        reply_to_message_id=self._sent_msg.id,
                        progress=self._upload_progress,
                    )
                sent_msg = await upload_coro
            else:
                sent_msg = await self._hu.upload(
                    target_client=target_client,
                    target_chat_id=self._sent_msg.chat.id,
                    file_path=upload_path,
                    dump_chat_id=Config.LEECH_DUMP_CHAT,
                    media_type=mtype,
                    attributes=attrs,
                    thumb_path=thumb if thumb and thumb != "none" else None,
                    caption=cap_mono,
                    reply_to_message_id=self._sent_msg.id,
                )
            LOGGER.info(f"Telegram upload completed: {file}")
            return sent_msg
        except Exception as err:
            if not self._listener.is_cancelled:
                LOGGER.warning(
                    f"Telegram upload attempt failed: {file} | {type(err).__name__}: {str(err) or repr(err)}"
                )
            raise

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=(
            retry_if_exception_type(Exception)
            & retry_if_not_exception_type((StopTransmission, CancelledError))
        ),
    )
    async def _upload_file(self, cap_mono, file, o_path, force_document=False):
        if self._listener.is_cancelled:
            raise StopTransmission()
        if not await aiopath.exists(o_path):
            raise FileNotFoundError(o_path)
        await self._reset_upload_attempt(o_path)

        if self._sent_msg is None:
            LOGGER.error("Cannot upload: _sent_msg is None")
            await self._listener.on_upload_error(
                "Upload failed: Message not initialized"
            )
            return

        if not hasattr(self._sent_msg, "chat") or self._sent_msg.chat is None:
            LOGGER.error("Cannot upload: _sent_msg.chat is None")
            await self._listener.on_upload_error(
                "Upload failed: Invalid message object"
            )
            return

        if (
            self._thumb is not None
            and not await aiopath.exists(self._thumb)
            and self._thumb != "none"
        ):
            self._thumb = None
        thumb = self._thumb
        self._is_corrupted = False
        key = None
        try:
            is_video, is_audio, is_image = await get_document_type(o_path)

            self._telegraph_url = None
            if not is_image:
                try:
                    f_size = await aiopath.getsize(o_path)
                    self._telegraph_url = await generate_telegraph_mediainfo(o_path, f_size)
                except Exception as e:
                    LOGGER.error(f"Failed to generate telegraph URL: {str(e) or repr(e)}")

            if not is_image and thumb is None:
                file_name = ospath.splitext(file)[0]
                thumb_path = f"{self._path}/yt-dlp-thumb/{file_name}.jpg"
                if await aiopath.isfile(thumb_path):
                    thumb = thumb_path
                elif await aiopath.isfile(thumb_path.replace("/yt-dlp-thumb", "")):
                    thumb = thumb_path.replace("/yt-dlp-thumb", "")
                elif is_audio and not is_video:
                    thumb = await get_audio_thumbnail(o_path)

            if (
                self._listener.as_doc
                or force_document
                or (not is_video and not is_audio and not is_image)
            ):
                key = "documents"
                if is_video and thumb is None:
                    thumb = await get_video_thumbnail(o_path, None)

                if self._listener.is_cancelled:
                    return
                if thumb == "none":
                    thumb = None
                sent_msg = await self._hyperul_upload(cap_mono, file, thumb, key, f_path=o_path)
            elif is_video:
                key = "videos"
                duration = (await get_media_info(o_path))[0]
                if thumb is None and self._listener.thumbnail_layout:
                    thumb = await get_multiple_frames_thumbnail(
                        o_path,
                        self._listener.thumbnail_layout,
                        self._listener.screen_shots,
                    )
                if thumb is None:
                    thumb = await get_video_thumbnail(o_path, duration)
                if thumb is not None and thumb != "none":
                    with Image.open(thumb) as img:
                        width, height = img.size
                else:
                    width = 480
                    height = 320
                if self._listener.is_cancelled:
                    return
                if thumb == "none":
                    thumb = None
                sent_msg = await self._hyperul_upload(cap_mono, file, thumb, key, f_path=o_path, duration=duration, width=width, height=height)
            elif is_audio:
                key = "audios"
                duration, artist, title = await get_media_info(o_path)
                if self._listener.is_cancelled:
                    return
                if thumb == "none":
                    thumb = None
                sent_msg = await self._hyperul_upload(cap_mono, file, thumb, key, f_path=o_path, duration=duration, artist=artist, title=title)
            else:
                key = "photos"
                if self._listener.is_cancelled:
                    return
                sent_msg = await self._hyperul_upload(cap_mono, file, thumb, key, f_path=o_path)

            self._sent_msg = sent_msg

            if (
                not self._listener.is_cancelled
                and self._media_group
                and (sent_msg.video or sent_msg.document)
            ):
                key = "documents" if sent_msg.document else "videos"
                if match := re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", o_path):
                    pname = match.group(0)
                    if pname in self._media_dict[key].keys():
                        self._media_dict[key][pname].append(
                            [sent_msg.chat.id, sent_msg.id]
                        )
                    else:
                        self._media_dict[key][pname] = [
                            [sent_msg.chat.id, sent_msg.id]
                        ]
                    msgs = self._media_dict[key][pname]
                    if len(msgs) == 10:
                        await self._send_media_group(pname, key, msgs)
                    else:
                        self._last_msg_in_group = True

            self._sent_msg = sent_msg

            if self._sent_msg:
                await self._copy_media()
                if self._listener.leech_dest:
                    try:
                        leech_dest = self._listener.leech_dest
                        if not isinstance(leech_dest, int):
                            if "|" in str(leech_dest):
                                leech_dest, _ = str(leech_dest).split("|", 1)
                            if leech_dest.lstrip("-").isdigit():
                                leech_dest = int(leech_dest)
                        await TgClient.bot.copy_message(
                            chat_id=leech_dest,
                            from_chat_id=sent_msg.chat.id,
                            message_id=sent_msg.id,
                        )
                    except Exception as e:
                        if not self._listener.is_cancelled:
                            LOGGER.error(
                                f"Failed to forward to {self._listener.leech_dest}: {e}"
                            )
                            await send_message(
                                self._listener.user_id,
                                f"Failed to forward to {self._listener.leech_dest}\n{e}",
                            )

            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            return sent_msg
        except (FloodWait, FloodPremiumWait) as flood:
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            wait_time = getattr(flood, "value", 5)
            LOGGER.warning(f"{str(flood) or repr(flood)}. Retrying in {wait_time}s")
            await sleep(wait_time * 1.3)
            return await self._upload_file(cap_mono, file, o_path, force_document)
        except (StopTransmission, CancelledError):
            raise
        except Exception as err:
            if self._listener.is_cancelled:
                raise StopTransmission()
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            err_type = "RPCError: " if isinstance(err, RPCError) else ""
            err_msg = str(err) or repr(err)
            LOGGER.warning(f"{err_type}{err_msg}. Retrying upload. Path: {o_path}")
            if isinstance(err, BadRequest) and key != "documents":
                LOGGER.error(f"Retrying as document. Path: {o_path}")
                return await self._upload_file(cap_mono, file, o_path, True)
            raise err

    @property
    def speed(self):
        try:
            return self._processed_bytes / (time() - self._start_time)
        except ZeroDivisionError:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def cancel_task(self):
        if self._listener.is_cancelled:
            return
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self._listener.name}")
        for task in self._upload_tasks:
            if not task.done():
                task.cancel()
        if self._hu is not None:
            try:
                await self._hu.cancel()
            except Exception as err:
                LOGGER.warning(f"Failed to cancel hypertg upload cleanly: {str(err) or repr(err)}")
        if self._upload_tasks:
            await gather(*self._upload_tasks, return_exceptions=True)
        await self._listener.on_upload_error("your upload has been stopped!")
