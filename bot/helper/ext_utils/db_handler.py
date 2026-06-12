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
    token = getattr(Config, "BOT_TOKEN", "") or ""
    return token.split(":", 1)[0] or "0"


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

    async def connect(self):
        try:
            if self._conn is not None:
                self._conn.close()
            self._conn = AsyncIOMotorClient(
                Config.DATABASE_URL, server_api=ServerApi("1")
            )
            self.db = self._conn.amaterasu
            self._return = False
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
        async with aiopen("sabnzbd/SABnzbd.ini", "rb+") as pf:
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
        self, cid, link, tag, user_id=None, command="", reply_to_msg_id=0, name=""
    ):
        if self._return:
            return
        data = {
            "cid": cid,
            "tag": tag,
            "link": link,
            "restart_notified": False,
            "schema_version": INCOMPLETE_TASK_SCHEMA,
            "created_at": datetime.now(timezone.utc),
        }
        if user_id is not None:
            data["user_id"] = user_id
        if command:
            data["command"] = command
        if reply_to_msg_id:
            data["reply_to_msg_id"] = reply_to_msg_id
        if name:
            data["name"] = name
        await self.db.tasks[TgClient.ID].update_one(
            {"_id": link}, {"$set": data}, upsert=True
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
        if self._return:
            return
        query = {"$or": [{"_id": link}, {"link": link}]}
        collection = str(TgClient.ID)
        await self.db.tasks[collection].delete_many(query)
        legacy_collection = _part()
        if legacy_collection != collection:
            await self.db.tasks[legacy_collection].delete_many(query)

    async def discard_legacy_incomplete_tasks(self):
        if self._return:
            return 0
        result = await self.db.tasks[str(TgClient.ID)].delete_many(
            {"schema_version": {"$ne": INCOMPLETE_TASK_SCHEMA}}
        )
        return result.deleted_count

    async def get_incomplete_task_docs(self, notified=False):
        if self._return:
            return []
        query = {"schema_version": INCOMPLETE_TASK_SCHEMA}
        if not notified:
            query["restart_notified"] = {"$ne": True}
        return [
            row async for row in self.db.tasks[TgClient.ID].find(query)
        ]

    async def update_incomplete_task(self, link, data):
        if self._return:
            return
        await self.db.tasks[TgClient.ID].update_one(
            {"_id": link}, {"$set": data}
        )

    async def mark_incomplete_tasks_notified(self, links):
        if self._return or not links:
            return
        await self.db.tasks[TgClient.ID].update_many(
            {"_id": {"$in": links}}, {"$set": {"restart_notified": True}}
        )

    async def get_user_incomplete_tasks(self, user_id):
        if self._return:
            return []
        return [
            row
            async for row in self.db.tasks[TgClient.ID].find(
                {
                    "user_id": user_id,
                    "schema_version": INCOMPLETE_TASK_SCHEMA,
                }
            )
        ]

    async def clear_user_incomplete_tasks(self, user_id):
        if self._return:
            return 0
        result = await self.db.tasks[TgClient.ID].delete_many({"user_id": user_id})
        return result.deleted_count

    async def clear_incomplete_tasks_by_links(self, links):
        if self._return or not links:
            return 0
        result = await self.db.tasks[TgClient.ID].delete_many(
            {"_id": {"$in": links}}
        )
        return result.deleted_count

    async def get_incomplete_tasks(self):
        notifier_dict = {}
        if self._return:
            return notifier_dict
        if await self.db.tasks[_part()].find_one():
            rows = self.db.tasks[_part()].find({})
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
        await self.db.tasks[_part()].drop()
        return notifier_dict

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


database = DbManager()
