MEGA_SDK_AVAILABLE = True
MEGA_SDK_IMPORT_ERROR = None

try:
    from mega import (
        MegaApi,
        MegaCancelToken,
        MegaError,
        MegaListener,
        MegaRequest,
        MegaTransfer,
    )
except (ImportError, ModuleNotFoundError) as e:
    MEGA_SDK_AVAILABLE = False
    MEGA_SDK_IMPORT_ERROR = e

    MegaApi = None
    MegaCancelToken = None
    MegaTransfer = type("MegaTransfer", (), {"TYPE_DOWNLOAD": 0, "TYPE_UPLOAD": 1})

    class MegaListener:
        pass

    class MegaError:
        API_OK = 0
        API_EAGAIN = -3
        API_ERATELIMIT = -4
        API_EINCOMPLETE = -13
        API_EOVERQUOTA = -24

    class MegaRequest:
        TYPE_LOGIN = 1
        TYPE_FETCH_NODES = 2
        TYPE_GET_PUBLIC_NODE = 3
        TYPE_LOGOUT = 4
        TYPE_ACCOUNT_DETAILS = 5
        TYPE_EXPORT = 6
        TYPE_CREATE_FOLDER = 7
        TYPE_IMPORT_LINK = 8

# MegaUploadOptions is only available in the unreleased master branch of
# meganz/sdk (added 2026-06-04). Release tags (v7.0.0 through v9.15.1) do
# NOT have it. We try to import it separately so the SDK still works on
# release tags — mega_listener.py falls back to the old startUpload API.
try:
    from mega import MegaUploadOptions
except (ImportError, ModuleNotFoundError):
    MegaUploadOptions = None


def mega_sdk_missing_message():
    return (
        "Mega SDK Python bindings are not installed in this image. "
        "Rebuild the Docker image from the current Dockerfile to enable Mega "
        "download/upload/account tools."
    )