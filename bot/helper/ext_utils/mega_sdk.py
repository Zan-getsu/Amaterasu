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
        MegaUploadOptions,
    )
except (ImportError, ModuleNotFoundError) as e:
    MEGA_SDK_AVAILABLE = False
    MEGA_SDK_IMPORT_ERROR = e

    MegaApi = None
    MegaCancelToken = None
    MegaTransfer = object
    MegaUploadOptions = None

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


def mega_sdk_missing_message():
    return (
        "Mega SDK Python bindings are not installed in this image. "
        "The bot can run, but Mega download/upload/account tools are unavailable."
    )
