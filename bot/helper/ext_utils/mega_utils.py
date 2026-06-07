from asyncio import TimeoutError as AsyncTimeoutError, get_running_loop, wait_for
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
        self._fut = None
        self.result = None
        self.error = None
        self.root_handle = None
        self.expected_type = None
        super().__init__()

    def onRequestFinish(self, api, request, error):
        try:
            req_type = request.getType()
            if req_type != self.expected_type:
                return
            err_code = error.getErrorCode() if error else MegaError.API_OK
            if err_code != MegaError.API_OK:
                self.error = error.toString()
            elif req_type == MegaRequest.TYPE_ACCOUNT_DETAILS:
                ad = request.getMegaAccountDetails()
                if ad is None:
                    self.error = "getMegaAccountDetails returned None"
                else:
                    info = {
                        "storage_max": ad.getStorageMax(),
                        "storage_used": ad.getStorageUsed(),
                        "transfer_max": ad.getTransferMax(),
                        "transfer_used": ad.getTransferUsed(),
                        "pro_level": ad.getProLevel(),
                        "pro_expiration": ad.getProExpiration(),
                    }
                    try:
                        root_handle = api.getRootNode().getHandle()
                        info["num_files"] = ad.getNumFiles(root_handle)
                        info["num_folders"] = ad.getNumFolders(root_handle)
                        self.root_handle = root_handle
                    except Exception:
                        pass
                    self.result = info
            elif req_type == MegaRequest.TYPE_FETCH_NODES:
                self.result = True
                try:
                    self.root_handle = api.getRootNode().getHandle()
                except Exception:
                    pass
            elif req_type == MegaRequest.TYPE_LOGIN:
                self.result = True
            f = self._fut
            if f and not f.done():
                self._loop.call_soon_threadsafe(f.set_result, True)
        except Exception as e:
            LOGGER.error(f"MegaAccountListener.onRequestFinish exception: {e}", exc_info=True)
            self.error = str(e)
            f = self._fut
            if f and not f.done():
                self._loop.call_soon_threadsafe(f.set_result, True)

    def onRequestTemporaryError(self, *args):
        pass

    def onRequestStart(self, *args):
        pass

    def onRequestUpdate(self, *args):
        pass

    def onTransferStart(self, *args):
        pass

    def onTransferUpdate(self, *args):
        pass

    def onTransferFinish(self, *args):
        pass

    def onTransferTemporaryError(self, *args):
        pass

    def onUsersUpdate(self, *args):
        pass

    def onUserAlertsUpdate(self, *args):
        pass

    def onNodesUpdate(self, *args):
        pass

    def onAccountUpdate(self, *args):
        pass

    def onSetsUpdate(self, *args):
        pass

    def onSetElementsUpdate(self, *args):
        pass

    def onContactRequestsUpdate(self, *args):
        pass

    def onReloadNeeded(self, *args):
        pass

    def onSyncFileStateChanged(self, *args):
        pass

    def onSyncAdded(self, *args):
        pass

    def onSyncDeleted(self, *args):
        pass

    def onSyncStateChanged(self, *args):
        pass

    def onSyncStatsUpdated(self, *args):
        pass

    def onGlobalSyncStateChanged(self, *args):
        pass

    def onSyncRemoteRootChanged(self, *args):
        pass

    def onBackupStateChanged(self, *args):
        pass

    def onBackupStart(self, *args):
        pass

    def onBackupFinish(self, *args):
        pass

    def onBackupUpdate(self, *args):
        pass

    def onBackupTemporaryError(self, *args):
        pass

    def onChatsUpdate(self, *args):
        pass

    def onEvent(self, *args):
        pass

    def onMountAdded(self, *args):
        pass

    def onMountChanged(self, *args):
        pass

    def onMountDisabled(self, *args):
        pass

    def onMountEnabled(self, *args):
        pass

    def onMountRemoved(self, *args):
        pass

    async def wait(self):
        if self._fut is None:
            self._loop = get_running_loop()
            self._fut = self._loop.create_future()
        try:
            await wait_for(self._fut, timeout=120)
        except AsyncTimeoutError:
            self.error = "Request timed out after 120s"


async def _do_mega_api_create(base_dir: str):
    return MegaApi("", base_dir, "WZML-X", 4)


async def _do_sync_step(api, listener, expected_type, method, *args, step_name: str):
    listener.expected_type = expected_type
    listener._loop = get_running_loop()
    listener._fut = listener._loop.create_future()
    await sync_to_async(method, *args)
    await listener.wait()
    if listener.error:
        LOGGER.warning(f"get_mega_account_info: {step_name} failed: {listener.error}")
    return listener.error


async def get_mega_account_info(email: str, password: str) -> str:
    if not email or not password:
        return (
            "⌬ <b>Mega Account Info</b>\n"
            "│\n"
            "┖ <i>No credentials configured.</i>"
        )

    base_dir = ospath.join("/tmp", f".mega_account_{token_hex(5)}")
    await makedirs(base_dir, exist_ok=True)

    api = await sync_to_async(MegaApi, "", base_dir, "WZML-X", 4)
    listener = MegaAccountListener()
    api.addListener(listener)
    api._listener_ref = listener

    try:
        err = await _do_sync_step(api, listener, MegaRequest.TYPE_LOGIN,
                                   api.login, email, password, step_name="login")
        if err:
            return f"⌬ <b>Mega Account Info</b>\n│\n┖ Login failed: {err}"

        err = await _do_sync_step(api, listener, MegaRequest.TYPE_FETCH_NODES,
                                   api.fetchNodes, step_name="fetchNodes")
        if err:
            return f"⌬ <b>Mega Account Info</b>\n│\n┖ Fetch nodes failed: {err}"

        err = await _do_sync_step(api, listener, MegaRequest.TYPE_ACCOUNT_DETAILS,
                                   api.getAccountDetails, step_name="getAccountDetails")
        if err:
            return f"⌬ <b>Mega Account Info</b>\n│\n┖ Account details failed: {err}"

        info = listener.result
        if not info:
            return "⌬ <b>Mega Account Info</b>\n│\n┖ No account details available."

        storage_max = info["storage_max"]
        storage_used = info["storage_used"]
        transfer_max = info["transfer_max"]
        transfer_used = info["transfer_used"]
        pro_level = info["pro_level"]
        pro_expiration = info["pro_expiration"]

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
                num_files = info["num_files"]
                num_folders = info["num_folders"]
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
            api.logout(False, None)
        except Exception:
            pass
        if base_dir and await aiopath.exists(base_dir):
            await rmtree(base_dir, ignore_errors=True)
