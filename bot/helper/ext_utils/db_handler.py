from datetime import datetime, timezone
from importlib import import_module
from uuid import uuid4

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
from pymongo.server_api import ServerApi

from ... import LOGGER, qbit_options, rss_dict, user_data
from ...core.config_manager import Config
from ...core.tg_client import TgClient, db_partition_id

INCOMPLETE_TASK_SCHEMA = 2


def _bot_id():
    if TgClient.ID:
        return str(TgClient.ID)
    return Config.BOT_TOKEN.split(":", 1)[0]


def _part():
    if not TgClient.PARTITION:
        TgClient.PARTITION = db_partition_id(_bot_id())
    return TgClient.PARTITION


def _new_uuid():
    return uuid4().hex


class DbManager:
    def __init__(self):
        self._return = True
        self._conn = None
        self.db = None

    def _tasks(self):
        return self.db.tasks[_bot_id()]

    async def connect(self):
        try:
            if self._conn is not None:
                self._conn.close()
            # Phase 1.10 — MongoDB connection pooling. maxPoolSize=50
            # handles 50 concurrent operations (plenty for a single-bot
            # deployment with 10 concurrent tasks). minPoolSize=5 keeps
            # warm connections ready. serverSelectionTimeoutMS=5000 fails
            # fast if MongoDB is unreachable (default 30s is too long for
            # a bot that should degrade gracefully).
            self._conn = AsyncIOMotorClient(
                Config.DATABASE_URL,
                server_api=ServerApi("1"),
                maxPoolSize=50,
                minPoolSize=5,
                serverSelectionTimeoutMS=5000,
            )
            self.db = self._conn.amaterasu
            self._return = False
            # Phase 1.5 — create TTL index on blacklisted_users.expires_at.
            # MongoDB automatically deletes documents when expires_at < now.
            # Sparse index so permanent bans (expires_at=None) are excluded
            # from the TTL and never auto-expire.
            try:
                await self.db.blacklisted_users.create_index(
                    "expires_at",
                    expireAfterSeconds=0,
                    sparse=True,
                    name="ttl_expires_at",
                )
                # Also index user_id for fast lookup
                await self.db.blacklisted_users.create_index(
                    "user_id",
                    unique=True,
                    name="uniq_user_id",
                )
            except PyMongoError as e:
                LOGGER.warning(f"blacklisted_users index creation: {e}")
            # Phase 3.10 — create indexes for common query patterns.
            # background=True so index creation doesn't block startup.
            try:
                # user_stats: index on user_id for fast per-user lookups
                await self.db.user_stats.create_index(
                    "user_id", unique=True, background=True, name="uniq_user_id"
                )
                # tasks: index on the partition key (_id already indexed
                # by MongoDB). Add user_id index for per-user task queries.
                # The tasks collection is sharded by _bot_id(), so we
                # index within each shard.
                # Note: tasks[_bot_id()] is a per-bot collection; we
                # create indexes on it after TgClient.ID is set (in
                # load_settings). Here we just create indexes on the
                # global collections.
                LOGGER.info("DB indexes created (blacklisted_users, user_stats)")
            except PyMongoError as e:
                LOGGER.warning(f"Phase 3.10 index creation: {e}")
        except PyMongoError as e:
            LOGGER.error(f"Error in DB connection: {e}")
            self.db = None
            self._return = True
            self._conn = None

    async def disconnect(self):
        self._return = True
        if self._conn is not None:
            self._conn.close()
        self._conn = None

    async def migrate_from_wzmlx(self):
        """One-time migration from WZML-X (wzmlx db) to Amaterasu (amaterasu db).

        Only runs on first deployment when amaterasu database has no data.
        Copies all collections from wzmlx except settings.deployConfig.
        """
        if self._return or self._conn is None:
            return

        try:
            # Check if amaterasu db already has data (any collection with documents)
            amaterasu_collections = await self.db.list_collection_names()
            for coll_name in amaterasu_collections:
                if await self.db[coll_name].count_documents({}, limit=1) > 0:
                    LOGGER.info(
                        "Amaterasu database already has data. "
                        "Skipping WZML-X migration."
                    )
                    return

            # Check if wzmlx database exists with data
            wzmlx_db = self._conn.wzmlx
            wzmlx_collections = await wzmlx_db.list_collection_names()
            if not wzmlx_collections:
                LOGGER.info(
                    "No WZML-X (wzmlx) database found. Skipping migration."
                )
                return

            LOGGER.info(
                "WZML-X database detected! Starting one-time migration "
                "from wzmlx → amaterasu..."
            )

            total_docs = 0
            total_collections = 0

            for coll_name in wzmlx_collections:
                source_coll = wzmlx_db[coll_name]
                doc_count = await source_coll.count_documents({})
                if doc_count == 0:
                    continue

                target_coll = self.db[coll_name]
                cursor = source_coll.find({})
                docs = await cursor.to_list(length=None)

                if docs:
                    try:
                        result = await target_coll.insert_many(
                            docs, ordered=False
                        )
                        inserted = len(result.inserted_ids)
                        total_docs += inserted
                        total_collections += 1
                        LOGGER.info(
                            f"  Migrated: {coll_name} "
                            f"({inserted}/{doc_count} documents)"
                        )
                    except Exception as e:
                        LOGGER.warning(
                            f"  Partial migration for {coll_name}: {e}"
                        )

            LOGGER.info(
                f"WZML-X → Amaterasu migration complete! "
                f"Migrated {total_docs} documents across "
                f"{total_collections} collections."
            )

        except PyMongoError as e:
            LOGGER.error(f"Error during WZML-X migration: {e}")
        except Exception as e:
            LOGGER.error(f"Unexpected error during WZML-X migration: {e}")

    async def update_deploy_config(self):
        if self._return:
            return
        settings = import_module("config")
        config_file = {
            key: value.strip() if isinstance(value, str) else value
            for key, value in vars(settings).items()
            if not key.startswith("__")
        }
        await self.db.settings.deployConfig.replace_one(
            {"_id": _part()}, config_file, upsert=True
        )

    async def update_config(self, dict_):
        if self._return:
            LOGGER.warning("update_config skipped: DB not connected")
            return
        await self.db.settings.config.update_one(
            {"_id": _part()}, {"$set": dict_}, upsert=True
        )

    async def update_aria2(self, key, value):
        if self._return:
            return
        await self.db.settings.aria2c.update_one(
            {"_id": _part()}, {"$set": {key: value}}, upsert=True
        )

    async def update_qbittorrent(self, key, value):
        if self._return:
            return
        await self.db.settings.qbittorrent.update_one(
            {"_id": _part()}, {"$set": {key: value}}, upsert=True
        )

    async def save_qbit_settings(self):
        if self._return:
            return
        await self.db.settings.qbittorrent.update_one(
            {"_id": _part()}, {"$set": qbit_options}, upsert=True
        )

    async def update_private_file(self, path):
        if self._return:
            return
        db_path = path.replace(".", "__")
        if await aiopath.exists(path):
            async with aiopen(path, "rb+") as pf:
                pf_bin = await pf.read()
            await self.db.settings.files.update_one(
                {"_id": _part()}, {"$set": {db_path: pf_bin}}, upsert=True
            )
            if path == "config.py":
                await self.update_deploy_config()
        else:
            await self.db.settings.files.update_one(
                {"_id": _part()}, {"$unset": {db_path: ""}}, upsert=True
            )

    async def update_nzb_config(self):
        if self._return:
            return
        async with aiopen("configs/sabnzbd/SABnzbd.ini", "rb+") as pf:
            nzb_conf = await pf.read()
        await self.db.settings.nzb.replace_one(
            {"_id": _part()}, {"SABnzbd__ini": nzb_conf}, upsert=True
        )

    async def update_user_data(self, user_id):
        if self._return:
            return
        data = user_data.get(user_id, {})
        data = data.copy()
        for key in ("THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "USER_COOKIE_FILE"):
            data.pop(key, None)
        pipeline = [
            {
                "$replaceRoot": {
                    "newRoot": {
                        "$mergeObjects": [
                            {"_id": user_id},
                            data,
                            {
                                "$arrayToObject": {
                                    "$filter": {
                                        "input": {"$objectToArray": "$$ROOT"},
                                        "as": "field",
                                        "cond": {
                                            "$in": [
                                                "$$field.k",
                                                [
                                                    "THUMBNAIL",
                                                    "RCLONE_CONFIG",
                                                    "TOKEN_PICKLE",
                                                    "USER_COOKIE_FILE",
                                                ],
                                            ]
                                        },
                                    }
                                }
                            },
                        ]
                    }
                }
            }
        ]
        await self.db.users[_part()].update_one(
            {"_id": user_id}, pipeline, upsert=True
        )

    async def update_user_doc(self, user_id, key, path=""):
        if self._return:
            return
        if path:
            async with aiopen(path, "rb+") as doc:
                doc_bin = await doc.read()
            await self.db.users[_part()].update_one(
                {"_id": user_id}, {"$set": {key: doc_bin}}, upsert=True
            )
        else:
            await self.db.users[_part()].update_one(
                {"_id": user_id}, {"$unset": {key: ""}}, upsert=True
            )

    async def rss_update_all(self):
        if self._return:
            return
        for user_id in list(rss_dict.keys()):
            await self.db.rss[_part()].replace_one(
                {"_id": user_id}, rss_dict[user_id], upsert=True
            )

    async def rss_update(self, user_id):
        if self._return:
            return
        await self.db.rss[_part()].replace_one(
            {"_id": user_id}, rss_dict[user_id], upsert=True
        )

    async def rss_delete(self, user_id):
        if self._return:
            return
        await self.db.rss[_part()].delete_one({"_id": user_id})

    async def add_incomplete_task(
        self, cid, link, tag, user_id=None, command="", reply_to_msg_id=0, name="", is_pm=False
    ):
        if self._return:
            return
        await self._tasks().update_one(
            {"_id": link},
            {"$setOnInsert": {
                "cid": cid,
                "tag": tag,
                "user_id": user_id,
                "command": command,
                "reply_to_msg_id": reply_to_msg_id,
                "name": name,
                "is_pm": is_pm,
                "restart_notified": False,
                "schema_version": INCOMPLETE_TASK_SCHEMA,
                "created_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    async def get_pm_uids(self):
        if self._return:
            return
        return [doc["_id"] async for doc in self.db.pm_users[_part()].find({})]

    async def set_pm_users(self, user_id):
        if self._return:
            return
        if not bool(await self.db.pm_users[_part()].find_one({"_id": user_id})):
            await self.db.pm_users[_part()].insert_one({"_id": user_id})
            LOGGER.info(f"New PM User Added : {user_id}")

    async def rm_pm_user(self, user_id):
        if self._return:
            return
        await self.db.pm_users[_part()].delete_one({"_id": user_id})

    async def rm_complete_task(self, link):
        if self._return or not link:
            return
        # Normalize: ensure consistent format
        normalized = str(link).strip()
        result = await self._tasks().delete_one({"_id": normalized})
        if result.deleted_count == 0:
            LOGGER.debug(f"rm_complete_task: no doc found for link={normalized!r}")

    async def discard_legacy_incomplete_tasks(self):
        if self._return:
            return 0
        result = await self._tasks().delete_many(
            {"schema_version": {"$ne": INCOMPLETE_TASK_SCHEMA}}
        )
        return result.deleted_count

    async def get_incomplete_task_docs(self, notified=False):
        if self._return:
            return []
        query = {"schema_version": INCOMPLETE_TASK_SCHEMA}
        if notified is None:
            pass  # no filter on restart_notified
        elif not notified:
            query["restart_notified"] = {"$ne": True}
        else:
            query["restart_notified"] = True
        cursor = self._tasks().find(query)
        return await cursor.to_list(length=None)

    async def update_incomplete_task(self, link, data):
        if self._return:
            return
        await self._tasks().update_one(
            {"_id": link}, {"$set": data}
        )

    async def mark_incomplete_tasks_notified(self, links):
        if self._return or not links:
            return
        await self._tasks().update_many(
            {"_id": {"$in": links}}, {"$set": {"restart_notified": True}}
        )

    async def get_user_incomplete_tasks(self, user_id):
        if self._return:
            return []
        return [
            row
            async for row in self._tasks().find(
                {
                    "user_id": user_id,
                    "schema_version": INCOMPLETE_TASK_SCHEMA,
                }
            )
        ]

    async def clear_user_incomplete_tasks(self, user_id):
        if self._return:
            return 0
        result = await self._tasks().delete_many({"user_id": user_id})
        return result.deleted_count

    async def clear_incomplete_tasks_by_links(self, links):
        if self._return or not links:
            return 0
        result = await self._tasks().delete_many(
            {"_id": {"$in": links}}
        )
        return result.deleted_count

    async def get_incomplete_tasks(self):
        notifier_dict = {}
        if self._return:
            return notifier_dict
        if await self._tasks().find_one():
            rows = self._tasks().find({})
            async for row in rows:
                link = row.get("link") or row.get("_id")
                if not link:
                    continue
                cid = row["cid"]
                tag = row["tag"]
                task_data = {
                    "link": link,
                    "command": row.get("command", ""),
                    "user_id": row.get("user_id", 0),
                    "reply_to_msg_id": row.get("reply_to_msg_id", 0),
                    "name": row.get("name", ""),
                }
                if cid in notifier_dict:
                    if tag in notifier_dict[cid]:
                        notifier_dict[cid][tag].append(task_data)
                    else:
                        notifier_dict[cid][tag] = [task_data]
                else:
                    notifier_dict[cid] = {tag: [task_data]}
        return notifier_dict

    async def drop_incomplete_tasks(self):
        if self._return:
            return
        await self._tasks().drop()

    async def trunc_table(self, name):
        if self._return:
            return
        collection = str(TgClient.ID) if name == "tasks" else _part()
        await self.db[name][collection].drop()
        if name == "tasks" and collection != _part():
            await self.db[name][_part()].drop()

    async def get_encode_profiles(self, user_id):
        if self._return:
            return {}
        profiles = await self.db.encode_profiles.find_one({"_id": f"{TgClient.ID}_{user_id}"})
        return profiles or {}

    async def save_encode_profile(self, user_id, profile_id, profile_data):
        if self._return:
            return
        await self.db.encode_profiles.update_one(
            {"_id": f"{TgClient.ID}_{user_id}"},
            {"$set": {profile_id: profile_data}},
            upsert=True,
        )

    async def delete_encode_profile(self, user_id, profile_id):
        if self._return:
            return
        await self.db.encode_profiles.update_one(
            {"_id": f"{TgClient.ID}_{user_id}"},
            {"$unset": {profile_id: ""}},
        )

    async def set_default_encode_profile(self, user_id, profile_id):
        if self._return:
            return
        profiles = await self.get_encode_profiles(user_id)
        if not profiles or profile_id not in profiles:
            return
        update_dict = {}
        for pid, pdata in profiles.items():
            if pid == "_id":
                continue
            if pdata.get("is_default"):
                update_dict[f"{pid}.is_default"] = False
        if update_dict:
            await self.db.encode_profiles.update_one(
                {"_id": f"{TgClient.ID}_{user_id}"},
                {"$set": update_dict}
            )
        await self.db.encode_profiles.update_one(
            {"_id": f"{TgClient.ID}_{user_id}"},
            {"$set": {f"{profile_id}.is_default": True}},
            upsert=True
        )

    # ────────────────────────────────────────────────────────────────────
    # Phase 1.5 — Blacklist system with MongoDB TTL index
    # ────────────────────────────────────────────────────────────────────
    # The blacklisted_users collection uses a TTL index on expires_at
    # (sparse, expireAfterSeconds=0). MongoDB automatically deletes
    # documents when expires_at < now. Permanent bans set expires_at=None
    # and are excluded from the TTL (sparse index skips null values).
    #
    # Schema: {
    #   _id: ObjectId,
    #   user_id: int (unique indexed),
    #   added_by: int (owner/sudo user_id who issued the ban),
    #   added_at: datetime (UTC),
    #   expires_at: datetime | None (None = permanent),
    #   reason: str
    # }
    async def add_blacklist(self, user_id, added_by, expires_at=None, reason=""):
        """Add a user to the blacklist. If user_id already exists, update
        the existing record (upsert). expires_at is a datetime in UTC, or
        None for a permanent ban. Returns True on success."""
        if self._return:
            return False
        from datetime import datetime, timezone
        doc = {
            "user_id": user_id,
            "added_by": added_by,
            "added_at": datetime.now(timezone.utc),
            "expires_at": expires_at,
            "reason": reason,
        }
        try:
            await self.db.blacklisted_users.update_one(
                {"user_id": user_id},
                {"$set": doc},
                upsert=True,
            )
            return True
        except PyMongoError as e:
            LOGGER.error(f"add_blacklist error: {e}")
            return False

    async def remove_blacklist(self, user_id):
        """Remove a user from the blacklist. Returns True if a document
        was deleted, False if the user wasn't blacklisted or on error."""
        if self._return:
            return False
        try:
            result = await self.db.blacklisted_users.delete_one(
                {"user_id": user_id}
            )
            return result.deleted_count > 0
        except PyMongoError as e:
            LOGGER.error(f"remove_blacklist error: {e}")
            return False

    async def get_blacklist(self, user_id):
        """Return the blacklist document for user_id, or None if not
        blacklisted. Expired temporary bans are auto-deleted by the TTL
        index, so any document returned is an active ban."""
        if self._return:
            return None
        try:
            return await self.db.blacklisted_users.find_one(
                {"user_id": user_id}, {"_id": 0}
            )
        except PyMongoError as e:
            LOGGER.error(f"get_blacklist error: {e}")
            return None

    async def get_all_blacklisted(self):
        """Return a list of all active blacklist documents. Used by owner
        to list current bans."""
        if self._return:
            return []
        try:
            cursor = self.db.blacklisted_users.find({}, {"_id": 0})
            return await cursor.to_list(length=None)
        except PyMongoError as e:
            LOGGER.error(f"get_all_blacklisted error: {e}")
            return []

    # ────────────────────────────────────────────────────────────────────
    # Phase 5.4 — Per-user usage statistics
    # ────────────────────────────────────────────────────────────────────
    async def increment_user_stats(self, user_id, downloads=0, uploads=0,
                                    bytes_downloaded=0, bytes_uploaded=0,
                                    engine=None):
        """Increment per-user usage stats. Called after each completed
        task. Creates the user_stats document on first call (upsert).
        engine is the engine name (e.g., 'aria2', 'qbit') — increments
        the engines_used.<engine> counter."""
        if self._return:
            return
        from datetime import datetime, timezone
        update = {
            "$inc": {
                "total_downloads": downloads,
                "total_uploads": uploads,
                "bytes_downloaded": bytes_downloaded,
                "bytes_uploaded": bytes_uploaded,
            },
            "$set": {"last_active": datetime.now(timezone.utc)},
        }
        if engine:
            update["$inc"][f"engines_used.{engine}"] = 1
        try:
            await self.db.user_stats.update_one(
                {"user_id": user_id}, update, upsert=True
            )
        except PyMongoError as e:
            LOGGER.error(f"increment_user_stats error: {e}")

    async def get_user_stats(self, user_id):
        """Return the stats document for user_id, or None."""
        if self._return:
            return None
        try:
            return await self.db.user_stats.find_one(
                {"user_id": user_id}, {"_id": 0}
            )
        except PyMongoError as e:
            LOGGER.error(f"get_user_stats error: {e}")
            return None

    async def add_user_daily_usage(self, user_id, bytes_):
        """Add bytes to the user's daily usage counter. Resets lazily
        (check on next request, not via cron)."""
        if self._return:
            return
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        try:
            doc = await self.db.user_stats.find_one({"user_id": user_id})
            if doc is None:
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$inc": {"daily_bytes": bytes_},
                     "$set": {"daily_reset_at": now, "monthly_reset_at": now,
                              "monthly_bytes": bytes_}},
                    upsert=True,
                )
                return
            # Reset daily if >24h since last reset
            daily_reset = doc.get("daily_reset_at", now)
            if (now - daily_reset).total_seconds() > 86400:
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$set": {"daily_bytes": bytes_, "daily_reset_at": now}},
                )
            else:
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$inc": {"daily_bytes": bytes_}},
                )
            # Reset monthly if >30 days since last reset
            monthly_reset = doc.get("monthly_reset_at", now)
            if (now - monthly_reset).total_seconds() > 30 * 86400:
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$set": {"monthly_bytes": bytes_, "monthly_reset_at": now}},
                )
            else:
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$inc": {"monthly_bytes": bytes_}},
                )
        except PyMongoError as e:
            LOGGER.error(f"add_user_daily_usage error: {e}")

    async def get_user_quota_usage(self, user_id):
        """Return (daily_bytes, monthly_bytes, daily_reset_at, monthly_reset_at).
        Lazily resets counters that have expired."""
        if self._return:
            return 0, 0, None, None
        from datetime import datetime, timezone
        try:
            doc = await self.db.user_stats.find_one({"user_id": user_id})
            if doc is None:
                return 0, 0, None, None
            now = datetime.now(timezone.utc)
            daily_bytes = doc.get("daily_bytes", 0)
            monthly_bytes = doc.get("monthly_bytes", 0)
            daily_reset = doc.get("daily_reset_at")
            monthly_reset = doc.get("monthly_reset_at")
            # Lazy daily reset
            if daily_reset and (now - daily_reset).total_seconds() > 86400:
                daily_bytes = 0
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$set": {"daily_bytes": 0, "daily_reset_at": now}},
                )
            # Lazy monthly reset
            if monthly_reset and (now - monthly_reset).total_seconds() > 30 * 86400:
                monthly_bytes = 0
                await self.db.user_stats.update_one(
                    {"user_id": user_id},
                    {"$set": {"monthly_bytes": 0, "monthly_reset_at": now}},
                )
            return daily_bytes, monthly_bytes, daily_reset, monthly_reset
        except PyMongoError as e:
            LOGGER.error(f"get_user_quota_usage error: {e}")
            return 0, 0, None, None


database = DbManager()
