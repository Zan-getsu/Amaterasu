from asyncio import Event, TimeoutError as AsyncTimeoutError, wait_for
from os import path as ospath
from secrets import token_hex

from aiofiles.os import makedirs, path as aiopath
from aioshutil import rmtree
from mega import MegaApi, MegaError, MegaListener, MegaRequest

from ... import LOGGER
from .bot_utils import sync_to_async
from .status_utils import get_readable_file_size


class MegaAccountListener(MegaListener):
    def __init__(self):
        self.event = Event()
        self.result = None
        self.error = None
        self.root_handle = None
        super().__init__()

    def onRequestFinish(self, api, request, error):
        err_code = error.getErrorCode() if error else MegaError.API_OK
        if err_code != MegaError.API_OK:
            self.error = error.toString()
        else:
            req_type = request.getType()
            if req_type == MegaRequest.TYPE_ACCOUNT_DETAILS:
                self.result = request.getMegaAccountDetails()
            elif req_type == MegaRequest.TYPE_FETCH_NODES:
                self.result = True
                try:
                    self.root_handle = api.getRootNode().getHandle()
                except Exception:
                    pass
            elif req_type == MegaRequest.TYPE_LOGIN:
                self.result = True
        self.event.set()

    def onRequestTemporaryError(self, api, request, error):
        pass

    def onUsersUpdate(self, api, users):
        pass

    def onNodesUpdate(self, api, nodes):
        pass

    def onAccountUpdate(self, api):
        pass

    def onEvent(self, api, event):
        pass

    def onReloadNeeded(self, api):
        pass

    async def wait(self):
        try:
            await wait_for(self.event.wait(), timeout=120)
        except AsyncTimeoutError:
            self.error = "Request timed out after 120s"


async def get_mega_account_info(email: str, password: str) -> str:
    if not email or not password:
        return (
            "⌬ <b>Mega Account Info</b>\n"
            "│\n"
            "┖ <i>No credentials configured.</i>"
        )

    base_dir = ospath.join("/tmp", f".mega_account_{token_hex(5)}")
    await makedirs(base_dir, exist_ok=True)

    api = MegaApi("", base_dir, "WZML-X", 4)
    listener = MegaAccountListener()
    api.addListener(listener)

    try:
        listener.event.clear()
        await sync_to_async(api.login, email, password)
        await listener.wait()
        if listener.error:
            return f"⌬ <b>Mega Account Info</b>\n│\n┖ Login failed: {listener.error}"

        listener.event.clear()
        await sync_to_async(api.fetchNodes)
        await listener.wait()
        if listener.error:
            return f"⌬ <b>Mega Account Info</b>\n│\n┖ Fetch nodes failed: {listener.error}"

        listener.event.clear()
        await sync_to_async(api.getAccountDetails)
        await listener.wait()
        if listener.error:
            return f"⌬ <b>Mega Account Info</b>\n│\n┖ Account details failed: {listener.error}"

        details = listener.result
        if not details:
            return "⌬ <b>Mega Account Info</b>\n│\n┖ No account details available."

        storage_max = details.getStorageMax()
        storage_used = details.getStorageUsed()
        transfer_max = details.getTransferMax()
        transfer_used = details.getTransferUsed()
        pro_level = details.getProLevel()
        pro_expiration = details.getProExpiration()

        storage_pct = round(storage_used / max(storage_max, 1) * 100, 2)
        transfer_pct = round(transfer_used / max(transfer_max, 1) * 100, 2)

        pro_names = {0: "Free", 1: "Pro I", 2: "Pro II", 3: "Pro III", 4: "Lite"}
        pro_name = pro_names.get(pro_level, f"Level {pro_level}")

        text = (
            f"⌬ <b>Mega Account Info</b>\n"
            f"│\n"
            f"┠ <b>Email</b> → <code>{email}</code>\n"
            f"┠ <b>Account Type</b> → {pro_name}\n"
        )
        if pro_expiration > 0:
            from time import gmtime, strftime
            text += f"┠ <b>Pro Expires</b> → {strftime('%Y-%m-%d', gmtime(pro_expiration))}\n"

        text += (
            f"┃\n"
            f"┠ <b>Storage</b> → {get_readable_file_size(storage_used)} / "
            f"{get_readable_file_size(storage_max)} ({storage_pct}%)\n"
            f"┠ <b>Transfer</b> → {get_readable_file_size(transfer_used)} / "
            f"{get_readable_file_size(transfer_max)} ({transfer_pct}%)\n"
        )

        if listener.root_handle is not None:
            try:
                num_files = details.getNumFiles(listener.root_handle)
                num_folders = details.getNumFolders(listener.root_handle)
                text += (
                    f"┃\n"
                    f"┠ <b>Files</b> → {num_files}\n"
                    f"┖ <b>Folders</b> → {num_folders}"
                )
            except Exception:
                text += (
                    "┃\n"
                    "┖ <b>Files/Folders</b> → N/A"
                )
        else:
            text += "┖ <b>Files/Folders</b> → N/A"

        return text

    except Exception as e:
        LOGGER.error(f"Mega get_account_info error: {e}", exc_info=True)
        return f"⌬ <b>Mega Account Info</b>\n│\n┖ Error: {e}"
    finally:
        try:
            api.logout()
        except Exception:
            pass
        if base_dir and await aiopath.exists(base_dir):
            await rmtree(base_dir, ignore_errors=True)
