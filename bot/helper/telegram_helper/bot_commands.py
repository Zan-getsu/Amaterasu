from ...core.config_manager import Config
from ...core.plugin_manager import get_plugin_manager


class BotCommands:
    StartCommand = "start"
    LoginCommand = "login"

    _static_commands = {
        "Mirror": ["mirror", "m"],
        "QbMirror": ["qbmirror", "qm"],
        "JdMirror": ["jdmirror", "jm"],
        "Ytdl": ["ytdl", "y"],
        "UpHoster": ["uphoster", "up"],
        "NzbMirror": ["nzbmirror", "nm"],
        "Leech": ["leech", "l"],
        "QbLeech": ["qbleech", "ql"],
        "JdLeech": ["jdleech", "jl"],
        "YtdlLeech": ["ytdlleech", "yl"],
        "NzbLeech": ["nzbleech", "nl"],
        "Clone": ["clone", "cl"],
        "Count": "count",
        "Delete": "del",
        "Purge": ["purge", "clear_drive"],
        "List": "list",
        "Search": "search",
        "Users": "users",
        "CancelTask": ["cancel", "c"],
        "CancelAll": ["cancelall", "call"],
        "ForceStart": ["forcestart", "fs"],
        "Status": ["status", "s", "statusall", "status_me", "s_me"],
        "MediaInfo": ["mediainfo", "mi"],
        "Ping": "ping",
        "Restart": ["restart", "r", "restartall"],
        "RestartSessions": ["restartses", "rses"],
        "Broadcast": ["broadcast", "bc"],
        "Stats": ["stats", "st"],
        "Help": ["help", "h"],
        "Log": "log",
        "Shell": "shell",
        "AExec": "aexec",
        "Exec": "exec",
        "ClearLocals": "clearlocals",
        "IMDB": "imdb",
        "Rss": "rss",
        "AddImage": ["addimage", "ai"],
        "Images": ["images", "image", "img"],
        "Authorize": ["authorize", "a"],
        "UnAuthorize": ["unauthorize", "ua"],
        "AddSudo": ["addsudo", "as"],
        "RmSudo": ["rmsudo", "rs"],
        "BlackList": ["blacklist", "bl"],
        "RmBlackList": ["rmblacklist", "rbl"],
        "BotSet": ["bset", "bsetting", "bs"],
        "UserSet": ["uset", "usetting", "us"],
        "Select": ["select", "sel"],
        "NzbSearch": ["nzbsearch", "ns"],
        "GenPyroSess": "exportsession",
        "CategorySelect": ["category", "ctsel"],
        "GDClean": ["gdclean", "gdc"],
        "Plugins": "plugins",
        "SpeedTest": ["speedtest", "stest"],
        "Telegraph": ["tg", "telegraph"],
        "FileToLink": ["link", "stream", "f2l"],
        "AutoRename": ["autorename", "ar"],
        "Sort": "sort",
        "Setup": ["setup", "init"],  # Phase 5.8 — interactive setup wizard
    }

    @classmethod
    def get_commands(cls):
        commands = cls._static_commands.copy()

        plugin_manager = get_plugin_manager()
        if plugin_manager:
            for plugin_info in plugin_manager.list_plugins():
                if plugin_info.enabled and plugin_info.commands:
                    for cmd in plugin_info.commands:
                        if any(
                            cmd == existing
                            or (isinstance(existing, list) and cmd in existing)
                            for existing in commands.values()
                        ):
                            continue
                        key = cmd.capitalize()
                        if key not in commands:
                            commands[key] = [cmd]
                        elif isinstance(commands[key], list):
                            if cmd not in commands[key]:
                                commands[key].append(cmd)
                        else:
                            commands[key] = [commands[key], cmd]
        return commands

    @classmethod
    def _build_command_vars(cls):
        commands = cls.get_commands()

        for key, cmds in commands.items():
            setattr(
                cls,
                f"{key}Command",
                (
                    [
                        (
                            f"{cmd}{Config.CMD_SUFFIX}"
                            if cmd not in ["restartall", "statusall"]
                            else cmd
                        )
                        for cmd in cmds
                    ]
                    if isinstance(cmds, list)
                    else f"{cmds}{Config.CMD_SUFFIX}"
                ),
            )

    @classmethod
    def refresh_commands(cls):
        cls._build_command_vars()


BotCommands._build_command_vars()
