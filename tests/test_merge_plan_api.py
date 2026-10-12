"""Exercise the production merge handlers through ASGI without starting bot services."""

import ast
import json
import re
from asyncio import to_thread
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from web import merge_plan_store as store
from web.security import make_short_token, verify_short_token


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_BASE_DIR", str(tmp_path / "plans"))
    assert store.create_plan("proof", 7, -100, "Proof", 2)
    store.register_source("proof", "first", 1, "First")
    store.register_source("proof", "second", 2, "Second")
    tree = ast.parse((Path(__file__).resolve().parents[1] / "web/wserver.py").read_text(encoding="utf-8"))
    names = {"_merge_plan_auth", "merge_plan_api", "_pin_rate_limited", "_record_pin_attempt"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    namespace = {
        "Request": Request, "JSONResponse": JSONResponse, "to_thread": to_thread,
        "read_merge_plan": store.read_plan, "update_merge_order": store.update_order,
        "public_merge_plan": store.public_plan, "verify_short_token": verify_short_token,
        "_web_secret": lambda: "fixture-secret", "_SAFE_GID": re.compile(r"^[A-Za-z0-9_-]{1,64}$"),
        "_pin_attempts": {}, "_PIN_RATE_LIMIT": 5, "_PIN_RATE_WINDOW": 60,
    }
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, "web/wserver.py", "exec"), namespace)
    app = FastAPI()
    app.add_api_route("/api/merge-plan/{plan_id}", namespace["merge_plan_api"], methods=["GET", "POST"])
    return app, {"X-Merge-Plan-Pin": make_short_token("fixture-secret", "merge-plan", "merge_proof")}


@pytest.mark.asyncio
async def test_api_authorization_save_conflict_lock_and_private_response(api):
    app, headers = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://merge.test") as client:
        assert (await client.get("/api/merge-plan/proof")).status_code == 403
        response = await client.get("/api/merge-plan/proof", headers=headers)
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        plan = response.json()
        assert not {"owner_id", "chat_id", "frozen_order"} & plan.keys()
        order = [item["id"] for item in reversed(plan["items"])]
        payload = {"order": order, "order_revision": plan["order_revision"]}
        saved = await client.post("/api/merge-plan/proof", headers=headers, json=payload)
        assert saved.status_code == 200
        assert [item["id"] for item in saved.json()["items"]] == order
        stale = await client.post("/api/merge-plan/proof", headers=headers, json=payload)
        assert stale.status_code == 409
        assert stale.json()["plan"]["order_revision"] == saved.json()["order_revision"]
        store.set_plan_status("proof", "processing", locked=True)
        locked = await client.post("/api/merge-plan/proof", headers=headers,
                                   json=dict(payload, order_revision=saved.json()["order_revision"]))
        assert locked.status_code == 409
        assert locked.json()["plan"]["locked"]


@pytest.mark.asyncio
async def test_api_invalid_and_unicode_pin_never_crashes(api):
    app, headers = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://merge.test") as client:
        response = await client.get("/api/merge-plan/proof", params={"pin": "日本語"})
        assert response.status_code == 403
        assert (await client.get("/api/merge-plan/missing", headers=headers)).status_code == 404
        revision = store.read_plan("proof")["order_revision"]
        for body in ("{", "[]", json.dumps({"order": [["bad"], ["worse"]], "order_revision": revision})):
            response = await client.post("/api/merge-plan/proof", headers=headers,
                                        content=body, follow_redirects=False)
            assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_pin_attempts_are_rate_limited(api):
    app, headers = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://merge.test") as client:
        for _ in range(5):
            assert (await client.get("/api/merge-plan/proof")).status_code == 403
        response = await client.get("/api/merge-plan/proof", headers=headers)
        assert response.status_code == 429
        assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_api_does_not_acknowledge_failed_disk_write(api, monkeypatch):
    app, headers = api
    monkeypatch.setattr(store, "_write_unlocked", lambda *args, **kwargs: False)
    plan = store.read_plan("proof")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://merge.test") as client:
        response = await client.post("/api/merge-plan/proof", headers=headers,
            json={"order": [item["id"] for item in reversed(plan["items"])], "order_revision": plan["order_revision"]})
        assert response.status_code == 400
        assert "Could not save" in response.json()["message"]
        assert store.read_plan("proof")["items"] == plan["items"]
