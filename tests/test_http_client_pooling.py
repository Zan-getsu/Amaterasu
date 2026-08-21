"""Regression checks for the shared HTTPX connection pool."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bot/helper/ext_utils/http_client.py"
SPEC = spec_from_file_location("amaterasu_http_client", MODULE_PATH)
assert SPEC and SPEC.loader
http_client = module_from_spec(SPEC)
SPEC.loader.exec_module(http_client)


@pytest.mark.asyncio
async def test_shared_client_is_reused_and_closed(monkeypatch):
    created = []

    class FakeClient:
        is_closed = False
        follow_redirects = True

        async def aclose(self):
            self.is_closed = True

    def create_client():
        client = FakeClient()
        created.append(client)
        return client

    monkeypatch.setattr(http_client, "_create_client", create_client)
    first = await http_client.get_client()
    second = await http_client.get_client()

    assert first is second
    assert first.follow_redirects is True

    await http_client.close_client()
    assert first.is_closed

    replacement = await http_client.get_client()
    assert replacement is not first
    assert created == [first, replacement]
    await http_client.close_client()


def test_http2_extra_is_declared_for_the_enabled_transport():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "httpx[http2]==0.28.1" in requirements


def test_image_callers_use_the_shared_pool():
    bot_utils = (ROOT / "bot/helper/ext_utils/bot_utils.py").read_text(encoding="utf-8")
    images = (ROOT / "bot/modules/images.py").read_text(encoding="utf-8")
    main = (ROOT / "bot/__main__.py").read_text(encoding="utf-8")

    assert "from .http_client import get_client" in bot_utils
    assert "from ..helper.ext_utils.http_client import get_client" in images
    assert "AsyncSession(" not in bot_utils
    assert "AsyncClient(" not in images
    assert "await close_client()" in main
