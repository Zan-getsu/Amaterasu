from asyncio import Event, TimeoutError as AsyncTimeoutError, wait_for
from time import time

from mega import MegaApi, MegaError, MegaListener, MegaRequest, MegaTransfer

from ... import LOGGER, bot_loop
from ..ext_utils.bot_utils import async_to_sync, sync_to_async

_ACTIVE_LISTENERS = []


async def mega_cleanup():
    from ... import task_dict, task_dict_lock

    async with task_dict_lock:
        for tk in list(task_dict.values()):
            if hasattr(tk, "_obj") and hasattr(tk._obj, "cancel_task"):
                await tk._obj.cancel_task()


_REQUEST_TIMEOUT_SECONDS = 300

MEGA_ERRORS = {
    "-16": "File(s) Banned",
    "-9": "File(s) not found or deleted",
    "-11": "File(s) Access Denied",
    "-15": "Decryption key error",
    "-13": "Incomplete transfer",
    "-6": "Too many requests",
}


def _mega_error_format(raw_error):
    if not raw_error:
        return raw_error
    stripped = str(raw_error).lstrip()
    for code, friendly in MEGA_ERRORS.items():
        if stripped.startswith(code):
            return friendly
    return raw_error


class AsyncMega:
    def __init__(self):
        self.api = None
        self.folder_api = None
        self._folder_listener = None
        self.continue_event = Event()
        self._transfer_event = Event()
        self._expected_request_type = None
        self._expected_request_source = None
        self._download_is_folder = False

    def _download_api(self):
        return self.folder_api if self.folder_api else self.api

    def _request_type_for_name(self, name):
        request_types = {
            "login": getattr(MegaRequest, "TYPE_LOGIN", None),
            "loginToFolder": getattr(MegaRequest, "TYPE_LOGIN", None),
            "fetchNodes": getattr(MegaRequest, "TYPE_FETCH_NODES", None),
            "getPublicNode": getattr(MegaRequest, "TYPE_GET_PUBLIC_NODE", None),
            "logout": getattr(MegaRequest, "TYPE_LOGOUT", None),
        }
        return request_types.get(name)

    def _request_type_for(self, function):
        return self._request_type_for_name(getattr(function, "__name__", ""))

    async def run(self, function, *args, expected_type=None, expected_source="main", **kwargs):
        self.continue_event.clear()
        self._expected_request_type = (
            self._request_type_for(function) if expected_type is None else expected_type
        )
        self._expected_request_source = expected_source
        LOGGER.info(f"AsyncMega.run: expecting type={self._expected_request_type}, source={expected_source}")
        try:
            await sync_to_async(function, *args, **kwargs)
            try:
                await wait_for(self.continue_event.wait(), timeout=_REQUEST_TIMEOUT_SECONDS)
            except AsyncTimeoutError:
                msg = (
                    f"Mega SDK timed out after {_REQUEST_TIMEOUT_SECONDS}s waiting for "
                    f"{getattr(function, '__name__', 'request')} ({expected_source})"
                )
                LOGGER.error(msg)
                listener = getattr(self, "_mega_listener", None)
                if listener is not None and not listener.error:
                    listener.error = msg
                self._transfer_event.set()
        finally:
            LOGGER.info(f"AsyncMega.run: finished, clearing expected_type/source")
            self._expected_request_type = None
            self._expected_request_source = None

    async def wait_for_transfer(self):
        await self._transfer_event.wait()

    async def logout(self):
        if self.folder_api:
            await self.run(
                self.folder_api.logout,
                expected_type=self._request_type_for_name("logout"),
                expected_source="folder",
            )
        if self.api:
            await self.run(
                self.api.logout,
                expected_type=self._request_type_for_name("logout"),
                expected_source="main",
            )

    async def fetchNodes(self, api=None, source="main"):
        api = api or self.api
        return await self.run(
            api.fetchNodes,
            expected_type=self._request_type_for_name("fetchNodes"),
            expected_source=source,
        )

    async def login(self, email, password):
        return await self.run(
            self.api.login,
            email,
            password,
            expected_type=self._request_type_for_name("login"),
            expected_source="main",
        )

    async def getPublicNode(self, link):
        return await self.run(
            self.api.getPublicNode,
            link,
            expected_type=self._request_type_for_name("getPublicNode"),
            expected_source="main",
        )

    async def loginToFolder(self, link):
        return await self.run(
            self.folder_api.loginToFolder,
            link,
            expected_type=self._request_type_for_name("loginToFolder"),
            expected_source="folder",
        )

    async def startDownload(self, node, localPath, name, listener, startFirst, cancelToken, collisionCheck, collisionResolution, undelete):
        self.continue_event.clear()
        self._transfer_event.clear()
        self._expected_request_type = None
        self._expected_request_source = None

        ml = getattr(self, "_mega_listener", None)
        if ml:
            self._download_is_folder = ml._is_folder
            if not ml._name:
                ml._name = name
            ml._target_handle = ml._handle
            LOGGER.info(f"startDownload: name='{ml._name}', target_handle={ml._target_handle}, is_folder={self._download_is_folder}")

        await sync_to_async(
            self._download_api().startDownload,
            node,
            localPath,
            name,
            listener,
            startFirst,
            cancelToken,
            collisionCheck,
            collisionResolution,
            undelete,
        )
        try:
            await wait_for(self.continue_event.wait(), timeout=_REQUEST_TIMEOUT_SECONDS)
        except AsyncTimeoutError:
            pass

    def __getattr__(self, name):
        attr = getattr(self.api, name)
        if callable(attr):

            async def wrapper(*args, **kwargs):
                return await self.run(
                    attr,
                    *args,
                    expected_type=self._request_type_for_name(name),
                    **kwargs,
                )

            return wrapper
        return attr


class MegaAppListener(MegaListener):
    def __init__(self, async_api: AsyncMega, listener):
        self._async_api = async_api
        self.continue_event = async_api.continue_event
        self._transfer_event = async_api._transfer_event
        self.listener = listener
        self.is_cancelled = False
        self.error = None
        self.retryable_error = None
        self._bytes_transferred = 0
        self._total_downloaded_bytes = 0
        self._speed = 0
        self._smoothed_speed = 0
        self._last_speed_time = 0
        self._caller_manages_completion = False
        self._cancel_token = None
        self._subfolder_target = None
        self.node = None
        self.public_node = None
        self._name = ""
        self._size = 0
        self._handle = None
        self._is_folder = False
        self._target_handle = None
        super().__init__()

    @property
    def speed(self):
        if self._last_speed_time and (time() - self._last_speed_time) > 2:
            return 0
        return int(self._smoothed_speed)

    @property
    def downloaded_bytes(self):
        return self._total_downloaded_bytes + self._bytes_transferred

    def _set_request_event(self):
        try:
            bot_loop.call_soon_threadsafe(self.continue_event.set)
        except Exception as e:
            LOGGER.error(f"Mega request event signal failed: {e}")

    def _set_transfer_event(self):
        try:
            bot_loop.call_soon_threadsafe(self._transfer_event.set)
        except Exception as e:
            LOGGER.error(f"Mega transfer event signal failed: {e}")

    def _cache_node_data(self, node):
        try:
            self._name = node.getName()
            self._handle = node.getHandle()
            self._is_folder = node.isFolder()
        except Exception:
            pass

    def _is_expected_request(self, request_type):
        expected = self._async_api._expected_request_type
        return expected is None or request_type == expected

    def _is_expected_source(self, source):
        expected = self._async_api._expected_request_source
        return expected is None or source == expected

    def _is_target_transfer(self, transfer, for_finish=False):
        if self._async_api._download_is_folder:
            if for_finish:
                try:
                    return transfer.isFolderTransfer()
                except Exception:
                    return False
            return True
        target_match = False
        if self._target_handle is not None:
            try:
                if transfer.getNodeHandle() == self._target_handle:
                    target_match = True
            except Exception:
                pass
        if not target_match:
            try:
                if transfer.getFileName() == self._name:
                    target_match = True
            except Exception:
                pass
        return target_match

    def onRequestStart(self, api, request):
        pass

    def onRequestUpdate(self, api, request):
        pass

    def onRequestFinish(self, api, request, error, source="main"):
        try:
            request_type = request.getType()
            err_code = error.getErrorCode() if error else MegaError.API_OK
            LOGGER.info(f"onRequestFinish: type={request_type}, source={source}, err={err_code}")
            if err_code != MegaError.API_OK:
                if self.is_cancelled:
                    self._set_request_event()
                    self._set_transfer_event()
                    return
                if err_code in (MegaError.API_EAGAIN, MegaError.API_ERATELIMIT):
                    return
                if not (self._is_expected_request(request_type) and self._is_expected_source(source)):
                    LOGGER.info(f"Ignoring unexpected request: type={request_type}, source={source}")
                    return
                self.error = f"{err_code} {error.toString()}"
                LOGGER.error(f"Mega onRequestFinishError: {self.error}")
                self._set_request_event()
                self._set_transfer_event()
                return

            if request_type == MegaRequest.TYPE_GET_PUBLIC_NODE:
                try:
                    self.public_node = request.getPublicMegaNode()
                except Exception:
                    self.public_node = None
                if self.public_node:
                    self._cache_node_data(self.public_node)
                    try:
                        self._size = self.public_node.getSize()
                    except Exception:
                        pass
            elif request_type == MegaRequest.TYPE_LOGIN:
                root = api.getRootNode()
                if source == "folder":
                    self.node = root
                    LOGGER.info(f"TYPE_LOGIN (folder source): set node={root is not None}")
                else:
                    self.public_node = root
                    LOGGER.info(f"TYPE_LOGIN (main source): set public_node={root is not None}")
                if root:
                    self._cache_node_data(root)
            elif request_type == MegaRequest.TYPE_FETCH_NODES:
                root_node = api.getRootNode()
                LOGGER.info(f"TYPE_FETCH_NODES: setting node={root_node is not None}, source={source}")
                self.node = root_node
                if self.node:
                    self._cache_node_data(self.node)
                if self._subfolder_target is not None and self.node:
                    try:
                        LOGGER.info(f"TYPE_FETCH_NODES: looking up subfolder target={self._subfolder_target}")
                        children = api.getChildren(self.node)
                        if children:
                            for i in range(children.size()):
                                child = children.get(i)
                                if child.getHandle() == self._subfolder_target:
                                    self.node = child
                                    self._cache_node_data(self.node)
                                    self._size = 0
                                    try:
                                        self._size = api.getSize(self.node)
                                    except Exception as e:
                                        LOGGER.warning(f"TYPE_FETCH_NODES: getSize error: {e}")
                                    LOGGER.info(f"TYPE_FETCH_NODES: subfolder resolved, name={self._name}, size={self._size}, is_folder={self._is_folder}")
                                    break
                    except Exception as e:
                        LOGGER.error(f"TYPE_FETCH_NODES: subfolder lookup error: {e}")

            LOGGER.info(f"onRequestFinish: after setting node, self.node={self.node is not None}, public_node={self.public_node is not None}")

            if self._is_expected_request(request_type) and self._is_expected_source(source):
                LOGGER.info(f"onRequestFinish: setting continue_event (expected_type={self._async_api._expected_request_type}, expected_source={self._async_api._expected_request_source})")
                self._set_request_event()
        except Exception as e:
            self.error = f"Mega request callback exception: {e}"
            LOGGER.error(self.error, exc_info=True)
            self._set_request_event()
            self._set_transfer_event()

    def onRequestTemporaryError(self, api, request, error: MegaError, source="main"):
        if self.is_cancelled:
            self._set_request_event()

    def onTransferStart(self, api, transfer):
        try:
            if not self._is_target_transfer(transfer):
                return
            self._bytes_transferred = 0
            self._set_request_event()
        except Exception as e:
            LOGGER.error(f"Mega transfer start callback exception: {e}", exc_info=True)

    def onTransferUpdate(self, api: MegaApi, transfer: MegaTransfer):
        try:
            if not self._is_target_transfer(transfer):
                return
            if self.is_cancelled:
                token = self._cancel_token
                if token is not None:
                    try:
                        if not token.isCancelled():
                            token.cancel()
                    except Exception:
                        pass
                else:
                    try:
                        api.cancelTransfer(transfer, None)
                    except Exception:
                        pass
                return
            self._speed = transfer.getSpeed()
            alpha = 0.3
            self._smoothed_speed = alpha * self._speed + (1 - alpha) * self._smoothed_speed
            self._last_speed_time = time()
            self._bytes_transferred = transfer.getTransferredBytes()
        except Exception as e:
            LOGGER.error(f"Mega transfer update callback exception: {e}", exc_info=True)

    def onTransferFinish(self, api: MegaApi, transfer: MegaTransfer, error):
        try:
            err_code = error.getErrorCode() if error else MegaError.API_OK
            if self.is_cancelled:
                self._set_transfer_event()
                return
            if not self._is_target_transfer(transfer, for_finish=True):
                return
            if err_code != MegaError.API_OK:
                self.error = f"{err_code} {error.toString()}"
                if err_code == MegaError.API_EINCOMPLETE:
                    self.retryable_error = self.error
                    self._set_transfer_event()
                    return
                LOGGER.error(f"Mega onTransferFinishError: {self.error}")
                self.is_cancelled = True
                async_to_sync(self.listener.on_download_error, _mega_error_format(self.error))
                self._set_transfer_event()
                return
            if not self._caller_manages_completion:
                async_to_sync(self.listener.on_download_complete)
            self._set_transfer_event()
        except Exception as e:
            LOGGER.error(f"onTransferFinish exception: {e}")
            self._set_transfer_event()

    def onTransferTemporaryError(self, api, transfer, error):
        try:
            if self.is_cancelled:
                return
            err_code = error.getErrorCode() if error else 0
            err_str = error.toString() if error else "unknown"
            if err_code == MegaError.API_EOVERQUOTA:
                msg = f"TransferTempError: Over quota: {err_str}"
                self.error = msg
                self.is_cancelled = True
                async_to_sync(self.listener.on_download_error, _mega_error_format(msg))
                self._set_transfer_event()
                return
            if err_code == MegaError.API_EINCOMPLETE:
                self.retryable_error = f"{err_code} {err_str}"
        except Exception as e:
            LOGGER.error(
                f"Mega transfer temporary-error callback exception: {e}",
                exc_info=True,
            )

    async def cancel_task(self):
        if self.is_cancelled:
            return
        self.is_cancelled = True
        token = self._cancel_token
        if token is not None:
            try:
                if not token.isCancelled():
                    token.cancel()
            except Exception as e:
                LOGGER.error(f"Mega cancel-token cancel failed: {e}")
        self._set_request_event()
        self._set_transfer_event()

    def onUsersUpdate(self, api, users):
        pass

    def onUserAlertsUpdate(self, api, alerts):
        pass

    def onNodesUpdate(self, api, nodes):
        pass

    def onAccountUpdate(self, api):
        pass

    def onSetsUpdate(self, api, sets):
        pass

    def onSetElementsUpdate(self, api, elements):
        pass

    def onContactRequestsUpdate(self, api, requests):
        pass

    def onReloadNeeded(self, api):
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

    def onGlobalSyncStateChanged(self, api):
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

    def onChatsUpdate(self, api, chats):
        pass

    def onEvent(self, api, event):
        pass

    def onMountAdded(self, *args):
        pass

    def onMountChanged(self, *args):
        pass


class MegaFolderListener(MegaListener):
    def __init__(self, main_listener: MegaAppListener):
        self._main = main_listener
        super().__init__()

    def onRequestStart(self, api, request):
        pass

    def onRequestFinish(self, api, request, error):
        self._main.onRequestFinish(api, request, error, source="folder")

    def onRequestUpdate(self, api, request):
        pass

    def onRequestTemporaryError(self, api, request, error):
        self._main.onRequestTemporaryError(api, request, error, source="folder")

    def onTransferStart(self, api, transfer):
        self._main.onTransferStart(api, transfer)

    def onTransferUpdate(self, api, transfer):
        self._main.onTransferUpdate(api, transfer)

    def onTransferFinish(self, api, transfer, error):
        self._main.onTransferFinish(api, transfer, error)

    def onTransferTemporaryError(self, api, transfer, error):
        self._main.onTransferTemporaryError(api, transfer, error)

    def onUsersUpdate(self, api, users):
        pass

    def onUserAlertsUpdate(self, api, alerts):
        pass

    def onNodesUpdate(self, api, nodes):
        pass

    def onAccountUpdate(self, api):
        pass

    def onSetsUpdate(self, api, sets):
        pass

    def onSetElementsUpdate(self, api, elements):
        pass

    def onContactRequestsUpdate(self, api, requests):
        pass

    def onReloadNeeded(self, api):
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

    def onGlobalSyncStateChanged(self, api):
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

    def onChatsUpdate(self, api, chats):
        pass

    def onEvent(self, api, event):
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
