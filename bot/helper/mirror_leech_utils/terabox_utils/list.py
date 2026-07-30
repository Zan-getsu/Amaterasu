import os
from asyncio import Event, wait_for
from functools import partial
from time import time

from aiofiles.os import path as aiopath
from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler

from ...ext_utils.bot_utils import new_task
from ...ext_utils.status_utils import get_readable_file_size, get_readable_time
from ...telegram_helper.button_build import ButtonMaker
from ...telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)

try:
    from terabox import TeraboxClient, TeraboxError
except ImportError:
    TeraboxClient = None

LIST_LIMIT = 8


@new_task
async def terabox_cookie_updates(_, query, obj):
    await query.answer()
    data = query.data.split()
    if len(data) < 2:
        return
    if data[1] == "cancel":
        obj.error = "Task has been cancelled!"
        obj.listener.is_cancelled = True
    elif data[1] == "user":
        obj.cookie_path = obj.user_cookie
        obj.cookie_label = "User Cookie"
    elif data[1] == "owner":
        obj.cookie_path = obj.owner_cookie
        obj.cookie_label = "Owner Cookie"
    else:
        return
    obj.event.set()
    await delete_message(query.message)
    obj._reply_to = None


class TeraboxCookieSelector:
    def __init__(self, listener, *, purpose):
        self.listener = listener
        self.purpose = purpose
        self.user_cookie = f"terabox_cookies/{listener.user_id}.txt"
        self.owner_cookie = "terabox.txt"
        self.cookie_path = ""
        self.cookie_label = ""
        self.error = ""
        self.event = Event()
        self._reply_to = None
        self._timeout = 120

    async def select(self):
        has_user = await aiopath.exists(self.user_cookie)
        has_owner = await aiopath.exists(self.owner_cookie)
        if has_user ^ has_owner:
            self.cookie_path = self.user_cookie if has_user else self.owner_cookie
            self.cookie_label = "User Cookie" if has_user else "Owner Cookie"
            return self.cookie_path
        if not has_user:
            self.error = (
                "No TeraBox cookie found. Upload terabox.txt in User Settings, "
                "or have the owner add a global one."
            )
            return ""
        buttons = ButtonMaker()
        buttons.data_button("User Cookie", "tbc user")
        buttons.data_button("Owner Cookie", "tbc owner")
        buttons.data_button("Cancel", "tbc cancel", position="footer")
        self._reply_to = await send_message(
            self.listener.message,
            f"Choose TeraBox cookie source for <i>{self.purpose}</i>:",
            buttons.build_menu(2),
        )
        callback = partial(terabox_cookie_updates, obj=self)
        handler = self.listener.client.add_handler(
            CallbackQueryHandler(
                callback,
                filters=regex("^tbc") & user(self.listener.user_id),
            ),
            group=-1,
        )
        try:
            await wait_for(self.event.wait(), timeout=self._timeout)
        except TimeoutError:
            self.error = "Timed out. Task has been cancelled!"
            self.listener.is_cancelled = True
        finally:
            self.listener.client.remove_handler(*handler)
            if self._reply_to is not None:
                await delete_message(self._reply_to)
        return self.cookie_path


@new_task
async def terabox_path_updates(_, query, obj):
    await query.answer()
    data = query.data.split()
    if len(data) < 2 or obj.query_proc:
        return
    obj.query_proc = True
    try:
        action = data[1]
        if action == "cancel":
            obj.error = "Task has been cancelled!"
            obj.listener.is_cancelled = True
            obj.event.set()
            await delete_message(query.message)
        elif action == "pre":
            obj.iter_start -= LIST_LIMIT * obj.page_step
            await obj.get_path_buttons()
        elif action == "nex":
            obj.iter_start += LIST_LIMIT * obj.page_step
            await obj.get_path_buttons()
        elif action == "ps":
            obj.page_step = int(data[2])
            await obj.get_path_buttons()
        elif action == "sel":
            obj.select = not obj.select
            await obj.get_path_buttons()
        elif action == "clr":
            obj.selected.clear()
            await obj.get_path_buttons()
        elif action == "back":
            obj.path = os.path.dirname(obj.path.rstrip("/")) or "/"
            await obj.get_path()
        elif action == "root":
            obj.path = "/"
            await obj.get_path()
        elif action == "pa":
            entry = obj.path_list[int(data[3])]
            if obj.select:
                if entry.path in obj.selected:
                    obj.selected.pop(entry.path)
                else:
                    obj.selected[entry.path] = obj._meta(entry)
                await obj.get_path_buttons()
            elif data[2] == "fo":
                obj.path = entry.path
                await obj.get_path()
            else:
                obj.selection = [obj._meta(entry)]
                obj.event.set()
                await delete_message(query.message)
        elif action == "cur":
            obj.selection = [
                {
                    "path": obj.path,
                    "name": os.path.basename(obj.path.rstrip("/")) or "TeraBox",
                    "size": 0,
                    "is_dir": True,
                }
            ]
            obj.event.set()
            await delete_message(query.message)
        elif action == "dl":
            obj.selection = list(obj.selected.values())
            obj.event.set()
            await delete_message(query.message)
    finally:
        obj.query_proc = False


class TeraboxList:
    def __init__(self, listener):
        self.listener = listener
        self.client = None
        self.event = Event()
        self._reply_to = None
        self._timeout = 240
        self._started = time()
        self.query_proc = False
        self.path = "/"
        self.path_list = []
        self.iter_start = 0
        self.page_step = 1
        self.select = False
        self.selected = {}
        self.selection = []
        self.error = ""

    @staticmethod
    def _meta(entry):
        return {
            "path": entry.path,
            "name": entry.name,
            "size": entry.size,
            "is_dir": entry.is_dir,
        }

    async def get_path_buttons(self):
        item_count = len(self.path_list)
        page_count = max(1, (item_count + LIST_LIMIT - 1) // LIST_LIMIT)
        self.iter_start = min(max(0, self.iter_start), LIST_LIMIT * (page_count - 1))
        buttons = ButtonMaker()
        for index, entry in enumerate(
            self.path_list[self.iter_start : self.iter_start + LIST_LIMIT],
            start=self.iter_start,
        ):
            kind = "fo" if entry.is_dir else "fi"
            label = (
                f"📁 {entry.name}"
                if entry.is_dir
                else f"[{get_readable_file_size(entry.size)}] {entry.name}"
            )
            if self.select and entry.path in self.selected:
                label = f"✅ {label}"
            buttons.data_button(label, f"tbq pa {kind} {index}")
        if item_count > LIST_LIMIT:
            buttons.data_button("Previous", "tbq pre", position="footer")
            buttons.data_button("Next", "tbq nex", position="footer")
        buttons.data_button("Download This Folder", "tbq cur", position="footer")
        buttons.data_button(
            f"Select: {'Enabled' if self.select else 'Disabled'}",
            "tbq sel",
            position="footer",
        )
        if self.selected:
            buttons.data_button(
                f"Download Selected ({len(self.selected)})",
                "tbq dl",
                position="footer",
            )
            buttons.data_button("Clear Selection", "tbq clr", position="footer")
        if self.path != "/":
            buttons.data_button("Back", "tbq back", position="footer")
            buttons.data_button("Back To Root", "tbq root", position="footer")
        buttons.data_button("Cancel", "tbq cancel", position="footer")
        message = (
            f"Choose a TeraBox file or folder:\n\nItems: {item_count}"
            f"\nCurrent Path: <code>{self.path}</code>"
            f"\nTimeout: {get_readable_time(self._timeout - (time() - self._started))}"
        )
        menu = buttons.build_menu(f_cols=2)
        if self._reply_to is None:
            self._reply_to = await send_message(self.listener.message, message, menu)
        else:
            await edit_message(self._reply_to, message, menu)

    async def get_path(self):
        try:
            entries = await self.client.list_account_dir(self.path)
            self.path_list = sorted(
                entries,
                key=lambda entry: (not entry.is_dir, entry.name.lower()),
            )
            self.iter_start = 0
            await self.get_path_buttons()
        except Exception as error:
            self.error = f"TeraBox listing failed: {error}"
            self.event.set()

    async def get_terabox_path(self):
        if TeraboxClient is None:
            self.error = "teraboxSDK is not installed in this image."
            return []
        cookie = self.listener.terabox_cookie or await self.listener._terabox_cookie_path()
        if not cookie:
            self.error = "No TeraBox cookie found."
            return []
        self.client = TeraboxClient(cookie_file=os.path.abspath(cookie))
        try:
            await self.client.login()
            await self.get_path()
            callback = partial(terabox_path_updates, obj=self)
            handler = self.listener.client.add_handler(
                CallbackQueryHandler(
                    callback,
                    filters=regex("^tbq") & user(self.listener.user_id),
                ),
                group=-1,
            )
            try:
                await wait_for(self.event.wait(), timeout=self._timeout)
            except TimeoutError:
                self.error = "Timed out. Task has been cancelled!"
                self.listener.is_cancelled = True
            finally:
                self.listener.client.remove_handler(*handler)
        except TeraboxError as error:
            self.error = f"TeraBox login failed: {error}"
        finally:
            await self.client.aclose()
            if self._reply_to is not None:
                await delete_message(self._reply_to)
        return self.selection
