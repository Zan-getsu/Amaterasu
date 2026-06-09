from asyncio import gather, sleep, wait_for, TimeoutError
from pyrogram.enums import ButtonStyle
from platform import platform, version
from re import search as research
from time import time

from aiofiles.os import path as aiopath
from psutil import (
    Process,
    boot_time,
    cpu_count,
    cpu_freq,
    cpu_percent,
    disk_io_counters,
    disk_usage,
    getloadavg,
    net_io_counters,
    swap_memory,
    virtual_memory,
    process_iter,
    NoSuchProcess,
    AccessDenied,
)

from .. import LOGGER, bot_cache, bot_start_time, bot_loop
from ..core.config_manager import Config, BinConfig
from ..helper.ext_utils.bot_utils import cmd_exec, compare_versions, new_task
from ..helper.ext_utils.status_utils import (
    get_progress_bar_string,
    get_readable_file_size,
    get_readable_time,
)
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)
from ..version import get_version

commands = {
    "aria2": ([BinConfig.ARIA2_NAME, "--version"], r"aria2 version ([\d.]+)"),
    "qBittorrent": ([BinConfig.QBIT_NAME, "--version"], r"qBittorrent v([\d.]+)"),
    "SABnzbd+": (
        [BinConfig.SABNZBD_NAME, "--version"],
        rf"{BinConfig.SABNZBD_NAME}-([\d.]+)",
    ),
    "python": (["python3", "--version"], r"Python ([\d.]+)"),
    "rclone": ([BinConfig.RCLONE_NAME, "--version"], r"rclone v([\d.]+)"),
    "yt-dlp": (["yt-dlp", "--version"], r"([\d.]+)"),
    "ffmpeg": (
        [BinConfig.FFMPEG_NAME, "-version"],
        r"ffmpeg version ([\d.]+(-\w+)?).*",
    ),
    "7z": (["7z", "i"], r"7-Zip ([\d.]+)"),
    "aiohttp": (["uv", "pip", "show", "aiohttp"], r"Version: ([\d.]+)"),
    "pyrotgfork": (["uv", "pip", "show", "pyrotgfork"], r"Version: ([\d.]+)"),
    "gapi": (["uv", "pip", "show", "google-api-python-client"], r"Version: ([\d.]+)"),
    "mega": (["mega-version"], r"version: ([\d.]+)"),
}


async def get_stats(event, key="home"):
    user_id = event.from_user.id
    btns = ButtonMaker()
    if key == "home":
        btns = ButtonMaker()
        btns.data_button("⚙ BOT", f"stats {user_id} stbot")
        btns.data_button("⚙ OS", f"stats {user_id} stsys")
        btns.data_button("⚙ REPO", f"stats {user_id} strepo")
        btns.data_button("⚙ PKGS", f"stats {user_id} stpkgs")
        btns.data_button("⚙ LIMITS", f"stats {user_id} tlimits")
        btns.data_button("⚙ SYS", f"stats {user_id} systasks")
        msg = "<b>❖ SYSTEM DASHBOARD</b>"
    elif key == "stbot":
        total, used, free, disk = disk_usage("/")
        swap = swap_memory()
        memory = virtual_memory()
        disk_io = disk_io_counters()
        msg = f"""<b>❖ SYSTEM METRICS</b>
<pre>
├─ {'Uptime':<11}: ⏳ {get_readable_time(time() - bot_start_time)}
├─ ─── MEMORY ────────────────────
├─ {'Usage':<11}: {get_progress_bar_string(memory.percent)} {memory.percent}%
├─ {'Allocation':<11}: {get_readable_file_size(memory.used)} / {get_readable_file_size(memory.total)}
├─ ─── SWAP ──────────────────────
├─ {'Usage':<11}: {get_progress_bar_string(swap.percent)} {swap.percent}%
├─ {'Allocation':<11}: {get_readable_file_size(swap.used)} / {get_readable_file_size(swap.total)}
├─ ─── STORAGE ───────────────────
├─ {'Usage':<11}: {get_progress_bar_string(disk)} {disk}%
├─ {'Read':<11}: ▼ {f"{get_readable_file_size(disk_io.read_bytes)} ({get_readable_time(disk_io.read_time / 1000)})" if disk_io else "Access Denied"}
├─ {'Write':<11}: ▲ {f"{get_readable_file_size(disk_io.write_bytes)} ({get_readable_time(disk_io.write_time / 1000)})" if disk_io else "Access Denied"}
└─ {'Allocation':<11}: {get_readable_file_size(used)} / {get_readable_file_size(total)}
</pre>"""
    elif key == "stsys":
        cpu_usage = cpu_percent(interval=0.5)
        msg = f"""<b>❖ OS SYSTEM</b>
<pre>
├─ {'Uptime':<11}: ⏳ {get_readable_time(time() - boot_time())}
├─ {'Version':<11}: {version()}
├─ {'Arch':<11}: {platform()}
├─ ─── NETWORK ───────────────────
├─ {'Upload':<11}: ▲ {get_readable_file_size(net_io_counters().bytes_sent)}
├─ {'Download':<11}: ▼ {get_readable_file_size(net_io_counters().bytes_recv)}
├─ {'Pkts Sent':<11}: {str(net_io_counters().packets_sent)[:-3]}k
├─ {'Pkts Recv':<11}: {str(net_io_counters().packets_recv)[:-3]}k
├─ {'Total I/O':<11}: ⇅ {get_readable_file_size(net_io_counters().bytes_recv + net_io_counters().bytes_sent)}
├─ ─── CPU ───────────────────────
├─ {'Usage':<11}: {get_progress_bar_string(cpu_usage)} {cpu_usage}%
├─ {'Freq':<11}: {f"{cpu_freq().current / 1000:.2f} GHz" if cpu_freq() else "Access Denied"}
├─ {'Avg Load':<11}: {"%, ".join(str(round((x / cpu_count() * 100), 2)) for x in getloadavg())}%
├─ {'Cores':<11}: {cpu_count(logical=False)}P / {cpu_count(logical=True) - cpu_count(logical=False)}V / {cpu_count(logical=True)}T
└─ {'Usable':<11}: {len(Process().cpu_affinity())}
</pre>"""
    elif key == "strepo":
        last_commit, changelog = "No Data", "N/A"
        if await aiopath.exists(".git"):
            last_commit = (
                await cmd_exec(
                    "git log -1 --pretty='%cd ( %cr )' --date=format-local:'%d/%m/%Y'",
                    True,
                )
            )[0]
            changelog = (
                await cmd_exec(
                    "git log -1 --pretty=format:'<code>%s</code> <i>By %an</i>'", True
                )
            )[0]
        official_v = (
            await cmd_exec(
                f"curl -o latestversion.py https://raw.githubusercontent.com/its-niloy/Amaterasu/{Config.UPSTREAM_BRANCH}/bot/version.py -s && python3 latestversion.py && rm latestversion.py",
                True,
            )
        )[0]
        official_v = official_v.strip() or "N/A"
        msg = f"""<b>❖ REPO METRICS</b>
<pre>
├─ {'Updated':<10}: {last_commit}
├─ {'Current':<10}: {get_version()}
├─ {'Latest':<10}: {official_v}
├─ {'ChangeLog':<10}: {changelog}
└─ {'Remarks':<10}: {compare_versions(get_version(), official_v)}
</pre>"""
    elif key == "stpkgs":
        ver = bot_cache.get("eng_versions", {})
        msg = f"""<b>❖ PACKAGES</b>
<pre>
├─ {'Python':<11}: {ver.get("python", "N/A")}
├─ {'Aria2':<11}: {ver.get("aria2", "N/A")}
├─ {'qBittorrent':<11}: {ver.get("qBittorrent", "N/A")}
├─ {'SABnzbd+':<11}: {ver.get("SABnzbd+", "N/A")}
├─ {'Rclone':<11}: {ver.get("rclone", "N/A")}
├─ {'yt-dlp':<11}: {ver.get("yt-dlp", "N/A")}
├─ {'FFmpeg':<11}: {ver.get("ffmpeg", "N/A")}
├─ {'7z':<11}: {ver.get("7z", "N/A")}
├─ {'Aiohttp':<11}: {ver.get("aiohttp", "N/A")}
├─ {'PyroTgFork':<11}: {ver.get("pyrotgfork", "N/A")}
├─ {'Google API':<11}: {ver.get("gapi", "N/A")}
└─ {'Mega CMD':<11}: {ver.get("mega", "N/A")}
</pre>"""
    elif key == "tlimits":
        msg = f"""<b>❖ TASK LIMITS</b>
<pre>
├─ {'Direct':<11}: {Config.DIRECT_LIMIT or "∞"} GB
├─ {'Torrent':<11}: {Config.TORRENT_LIMIT or "∞"} GB
├─ {'GDrive':<11}: {Config.GD_DL_LIMIT or "∞"} GB
├─ {'RClone':<11}: {Config.RC_DL_LIMIT or "∞"} GB
├─ {'Clone':<11}: {Config.CLONE_LIMIT or "∞"} GB
├─ {'JDown':<11}: {Config.JD_LIMIT or "∞"} GB
├─ {'NZB':<11}: {Config.NZB_LIMIT or "∞"} GB
├─ {'YT-DLP':<11}: {Config.YTDLP_LIMIT or "∞"} GB
├─ {'Playlist':<11}: {Config.PLAYLIST_LIMIT or "∞"}
├─ {'Mega':<11}: {Config.MEGA_LIMIT or "∞"} GB
├─ {'Leech':<11}: {Config.LEECH_LIMIT or "∞"} GB
├─ {'Archive':<11}: {Config.ARCHIVE_LIMIT or "∞"} GB
├─ {'Extract':<11}: {Config.EXTRACT_LIMIT or "∞"} GB
├─ {'Threshold':<11}: {Config.STORAGE_LIMIT or "∞"} GB
├─ ─── GLOBAL LIMITS ─────────────
├─ {'Token Val':<11}: {get_readable_time(Config.VERIFY_TIMEOUT) if Config.VERIFY_TIMEOUT else "Disabled"}
├─ {'User Time':<11}: {Config.USER_TIME_INTERVAL or "0"}s
├─ {'User Tasks':<11}: {Config.USER_MAX_TASKS or "∞"}
└─ {'Bot Tasks':<11}: {Config.BOT_MAX_TASKS or "∞"}
</pre>"""

    elif key == "systasks":
        from html import escape
        try:
            processes = []
            for proc in process_iter(
                ["pid", "name", "cpu_percent", "memory_percent", "username"]
            ):
                try:
                    info = proc.info
                    if (
                        info.get("cpu_percent", 0) > 1.0
                        or info.get("memory_percent", 0) > 1.0
                    ):
                        processes.append(info)
                except (NoSuchProcess, AccessDenied):
                    continue
            processes.sort(
                key=lambda x: x.get("cpu_percent", 0) + x.get("memory_percent", 0),
                reverse=True,
            )
            processes = processes[:15]
        except Exception:
            processes = []

        msg = "<b>❖ SYSTEM TASKS</b>\n<pre>\n"

        if processes:
            for i, proc in enumerate(processes, 1):
                name = escape(proc.get("name", "Unknown")[:15])
                cpu = proc.get("cpu_percent", 0)
                mem = proc.get("memory_percent", 0)
                user = escape(proc.get("username", "Unknown")[:8])
                prefix_top = "├─"
                prefix_bot = "├─" if i < len(processes) else "└─"
                msg += f"{prefix_top} {i:02d} {name} (PID:{proc['pid']})\n"
                msg += f"{prefix_bot}    CPU:{cpu:4.1f}% MEM:{mem:4.1f}% {user}\n"
                btns.data_button(f"✕ {i:02d}", f"stats {user_id} killproc {proc['pid']}")
            msg += "\n⚑ Click number to terminate process\n"
        else:
            msg += "└─ No high usage processes found\n"
            
        msg += "</pre>"

        btns.data_button("↻ REFRESH", f"stats {user_id} systasks", "header", style=ButtonStyle.PRIMARY)

    btns.data_button("↩ BACK", f"stats {user_id} home", "footer")
    btns.data_button("✕ CLOSE", f"stats {user_id} close", "footer", style=ButtonStyle.DANGER)
    return msg, btns.build_menu(8 if key == "systasks" else 2)


@new_task
async def bot_stats(_, message):
    msg, btns = await get_stats(message)
    await send_message(message, msg, btns, photo="IMAGES")


@new_task
async def stats_pages(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message, message.reply_to_message)
    elif data[2] == "killproc":
        if not await CustomFilters.owner(_, query):
            await query.answer("Sorry! You cannot Kill System Tasks!", show_alert=True)
            return
        pid = int(data[3])
        try:
            process = Process(pid)
            proc_name = process.name()
            process.terminate()
            await sleep(2)
            if process.is_running():
                process.kill()
                status = "🔥 Force killed"
            else:
                status = "✅ Terminated"
            await query.answer(f"{status}: {proc_name} (PID: {pid})", show_alert=True)
        except NoSuchProcess:
            await query.answer(
                "❌ Process not found or already terminated!", show_alert=True
            )
        except AccessDenied:
            await query.answer(
                "❌ Access denied! Cannot kill this process.", show_alert=True
            )
        except Exception as e:
            await query.answer(f"❌ Error: {str(e)}", show_alert=True)

        msg, btns = await get_stats(query, "systasks")
        await edit_message(message, msg, btns)
    else:
        if data[2] == "systasks" and not await CustomFilters.sudo(_, query):
            await query.answer("Sorry! You cannot open System Tasks!", show_alert=True)
            return
        await query.answer()
        msg, btns = await get_stats(query, data[2])
        await edit_message(message, msg, btns)


async def get_version_async(command, regex, timeout=5):
    try:
        out, err, code = await wait_for(cmd_exec(command), timeout=timeout)
        if code != 0:
            return f"Error: {err}"
        match = research(regex, out)
        return match.group(1) if match else "-"
    except TimeoutError:
        return "Timeout"
    except Exception as e:
        return f"Exception: {str(e)}"


async def retry_mega_version():
    await sleep(60)
    command, regex = commands["mega"]
    version = await get_version_async(command, regex, timeout=10)
    if version != "Timeout" and not version.startswith("Exception"):
        bot_cache["eng_versions"]["mega"] = version
        LOGGER.info(f"MegaCMD Version Fetched: {version}")
    else:
        LOGGER.warning(f"Failed to fetch MegaCMD Version: {version}")


@new_task
async def get_packages_version():
    tasks = [get_version_async(command, regex) for command, regex in commands.values()]
    versions = await gather(*tasks)
    bot_cache["eng_versions"] = {}
    for tool, ver in zip(commands.keys(), versions):
        bot_cache["eng_versions"][tool] = ver
    if await aiopath.exists(".git"):
        last_commit = await cmd_exec(
            "git log -1 --date=short --pretty=format:'%cd <b>From</b> %cr'", True
        )
        last_commit = last_commit[0]
    else:
        last_commit = "No UPSTREAM_REPO"
    bot_cache["commit"] = last_commit

    if bot_cache["eng_versions"]["mega"] in ["Timeout", "N/A"] or bot_cache[
        "eng_versions"
    ]["mega"].startswith("Exception"):
        bot_loop.create_task(retry_mega_version())

    LOGGER.info("Fetched Package Versions!")
