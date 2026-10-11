"""Exercise the installed shutdown callbacks without starting bot services."""

import ast
import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_installed_signal_callback_requests_shutdown(fallback, signum):
    source = Path(__file__).resolve().parents[1] / "bot/__main__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_signal_handler", "_install_signal_handlers"}
    ]
    loop = SimpleNamespace(
        add_signal_handler=Mock(side_effect=NotImplementedError if fallback else None)
    )
    signal_api = SimpleNamespace(
        SIGTERM=signal.SIGTERM,
        SIGINT=signal.SIGINT,
        Signals=signal.Signals,
        signal=Mock(),
    )
    shutdown = SimpleNamespace(set=Mock())
    logger = Mock()
    namespace = {
        "signal": signal_api,
        "bot_loop": loop,
        "_shutdown_event": shutdown,
        "LOGGER": logger,
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    namespace["_install_signal_handlers"]()

    registration = signal_api.signal if fallback else loop.add_signal_handler
    assert registration.call_count == 2
    registered = next(call.args for call in registration.call_args_list if call.args[0] == signum)
    _, callback, *args = registered
    if fallback:
        callback(signum, None)
    else:
        callback(*args)
    shutdown.set.assert_called_once_with()
    assert signal.Signals(signum).name in logger.info.call_args.args[0]
