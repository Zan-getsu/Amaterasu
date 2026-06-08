from shutil import rmtree as shutil_rmtree
from tempfile import mkdtemp

from mega import MegaApi, MegaError, MegaListener, MegaRequest

from ... import LOGGER
from .bot_utils import sync_to_async
from .status_utils import get_readable_file_size


class MegaAccountListener(MegaListener):
    def __init__(self):
        self._done = False
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
            self._done = True
        except Exception as e:
            LOGGER.error(f"MegaAccountListener.onRequestFinish exception: {e}", exc_info=True)
            self.error = str(e)
            self._done = True

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


def _get_mega_account_info_sync(email: str, password: str) -> str:
    from time import sleep, gmtime, strftime, time

    LOGGER.info("[MegaAccountInfo] _get_mega_account_info_sync START")
    t0 = time()

    if not email or not password:
        LOGGER.info("[MegaAccountInfo] No credentials configured, returning early")
        return (
            "⌬ <b>Mega Account Info</b>\n"
            "│\n"
            "┖ <i>No credentials configured.</i>"
        )

    LOGGER.info("[MegaAccountInfo] Creating temp dir")
    base_dir = mkdtemp(prefix=".mega_account_")

    LOGGER.info("[MegaAccountInfo] Calling MegaApi constructor...")
    t1 = time()
    api = MegaApi("", base_dir, "WZML-X", 4)
    LOGGER.info(f"[MegaAccountInfo] MegaApi constructor done in {time()-t1:.3f}s")

    LOGGER.info("[MegaAccountInfo] Creating listener")
    listener = MegaAccountListener()
    api.addListener(listener)
    api._listener_ref = listener
    LOGGER.info("[MegaAccountInfo] Listener attached")

    try:
        for expected_type, method, args, step_name in [
            (MegaRequest.TYPE_LOGIN, api.login, (email, password), "login"),
            (MegaRequest.TYPE_FETCH_NODES, api.fetchNodes, (), "fetchNodes"),
            (MegaRequest.TYPE_ACCOUNT_DETAILS, api.getAccountDetails, (), "getAccountDetails"),
        ]:
            listener._done = False
            listener.expected_type = expected_type
            listener.error = None
            listener.result = None

            LOGGER.info(f"[MegaAccountInfo] Calling {step_name}...")
            t2 = time()
            method(*args)
            LOGGER.info(f"[MegaAccountInfo] {step_name} returned (sync call done in {time()-t2:.3f}s), polling for callback...")

            for i in range(50):
                if listener._done:
                    LOGGER.info(f"[MegaAccountInfo] {step_name} callback received after {i*0.1:.1f}s")
                    break
                sleep(0.1)
            else:
                LOGGER.info(f"[MegaAccountInfo] {step_name} TIMEOUT after 5s")
                return f"⌬ <b>Mega Account Info</b>\n│\n┖ {step_name} timed out after 5s"

            if listener.error:
                LOGGER.info(f"[MegaAccountInfo] {step_name} error: {listener.error}")
                return f"⌬ <b>Mega Account Info</b>\n│\n┖ {step_name} failed: {listener.error}"

            LOGGER.info(f"[MegaAccountInfo] {step_name} OK")

        info = listener.result
        LOGGER.info(f"[MegaAccountInfo] All steps done in {time()-t0:.3f}s, building response text")

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

        LOGGER.info(f"[MegaAccountInfo] Returning result, total {time()-t0:.3f}s")
        return text

    except Exception as e:
        LOGGER.error(f"[MegaAccountInfo] Exception: {e}", exc_info=True)
        return f"⌬ <b>Mega Account Info</b>\n│\n┖ Error: {e}"
    finally:
        LOGGER.info("[MegaAccountInfo] Cleaning up (logout + rmtree)")
        try:
            api.logout(False, None)
        except Exception:
            pass
        try:
            shutil_rmtree(base_dir, ignore_errors=True)
        except Exception:
            pass
        LOGGER.info("[MegaAccountInfo] Cleanup done")


async def get_mega_account_info(email: str, password: str) -> str:
    LOGGER.info("[MegaAccountInfo] get_mega_account_info called, submitting to thread pool")
    result = await sync_to_async(_get_mega_account_info_sync, email, password)
    LOGGER.info("[MegaAccountInfo] Thread pool task completed")
    return result
