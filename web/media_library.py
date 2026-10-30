"""Private per-bot catalog, indexed by stable Telegram message pointers."""

import asyncio
import re
from datetime import UTC, datetime


def channel_target(value):
    match = re.fullmatch(r"https://t\.me/(?:c/(\d+)|([A-Za-z][A-Za-z0-9_]{3,}))/(\d+)", value)
    if not match:
        raise ValueError("Use the last post link: /link index https://t.me/c/123456/500")
    private, public, last = match.groups()
    if not 1 <= int(last) < 2**31:
        raise ValueError("Invalid last message ID.")
    return int(f"-100{private}") if private else public, int(last)


class MediaLibrary:
    def __init__(self, files, scans):
        self.files, self.scans = files, scans

    async def ensure_indexes(self):
        await self.files.create_index([("channel_id", 1), ("message_id", 1)], unique=True)

    async def page(self, query="", page=1):
        where = {"name": {"$regex": re.escape(query[:100]), "$options": "i"}} if query else {}
        total = await self.files.count_documents(where)
        pages = max(1, (total + 29) // 30)
        page = max(1, min(page, pages))
        items = (
            await self.files.find(where)
            .sort([("channel_id", 1), ("message_id", -1)])
            .skip((page - 1) * 30)
            .limit(30)
            .to_list(length=30)
        )
        return dict(items=items, total=total, page=page, pages=pages)

    async def scan(self, client, channel, end, stop, describe, report, *, rescan=False):
        state = await self.scans.find_one({"_id": channel}) or {}
        start = 1 if rescan else int(state.get("last", 0)) + 1
        last, added = start - 1, 0
        for first in range(start, end + 1, 50):
            if stop.is_set():
                break
            ids = list(range(first, min(first + 50, end + 1)))
            while True:
                try:
                    messages = await asyncio.wait_for(
                        client.get_messages(channel, message_ids=ids), 45
                    )
                    break
                except Exception as exc:
                    if type(exc).__name__ != "FloodWait":
                        raise
                    try:
                        await asyncio.wait_for(stop.wait(), max(1, exc.value))
                    except TimeoutError:
                        continue
                    return last, added
            found = {m.id: m for m in messages if m and not getattr(m, "empty", False)}
            for ident in ids:
                if stop.is_set():
                    return last, added
                item = describe(found[ident]) if ident in found else None
                if item:
                    await self.files.update_one(
                        {"channel_id": channel, "message_id": ident},
                        {"$set": {**item, "updated_at": datetime.now(UTC)}},
                        upsert=True,
                    )
                    added += 1
                elif rescan:
                    await self.files.delete_one({"channel_id": channel, "message_id": ident})
                last = ident
                await self.scans.update_one(
                    {"_id": channel}, {"$max": {"last": ident}}, upsert=True
                )
            await report(last, end, added)
            await asyncio.sleep(0.3)
        return last, added
