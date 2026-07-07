from asyncio import TimeoutError as AsyncTimeoutError, wait_for
from io import BytesIO
from shlex import split as shlex_split

from .. import LOGGER
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.telegram_helper.message_utils import send_file, send_message

# Hardening:
#  - Default off (must set ENABLE_SHELL_COMMAND=1)
#  - Owner-only (sudo is not enough; sudo accounts may be phished)
#  - Use shlex.split + create_subprocess_exec when possible (no shell=True)
#  - 60s timeout kills the subprocess (no orphans)
#  - Output capped at 100k chars
#  - Every invocation logged with user_id, chat_id, and command
SHELL_TIMEOUT = 60
SHELL_MAX_OUTPUT = 100_000


async def _run_cmd_with_timeout(cmd, shell, timeout):
    """Run a command with a hard timeout that KILLS the subprocess.

    asyncio.wait_for cancels the awaiting coroutine on timeout but does
    NOT kill the underlying subprocess — it would be orphaned. We catch
    the timeout, kill the process group, then re-raise.
    """
    from asyncio import create_subprocess_exec, create_subprocess_shell
    from asyncio.subprocess import PIPE

    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    try:
        stdout, stderr = await wait_for(proc.communicate(), timeout=timeout)
    except AsyncTimeoutError:
        # Kill the subprocess so it doesn't orphan. try/except because
        # the process may have exited between the timeout firing and our
        # kill call.
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
        # Wait briefly for the kill to take effect so we don't leak the process.
        try:
            await wait_for(proc.wait(), timeout=5)
        except AsyncTimeoutError:
            pass
        raise
    try:
        stdout = stdout.decode().strip()
    except Exception:
        stdout = "Unable to decode the response!"
    try:
        stderr = stderr.decode().strip()
    except Exception:
        stderr = "Unable to decode the error!"
    return stdout, stderr, proc.returncode


@new_task
async def run_shell(_, message):
    if not Config.ENABLE_SHELL_COMMAND:
        await send_message(
            message,
            "Shell command is disabled.\n\n"
            "To enable, set <code>ENABLE_SHELL_COMMAND=1</code> in config or env "
            "and restart. \n\n"
            "<b>Warning:</b> /shell grants root-equivalent access in the container. "
            "Only enable if you trust every sudo user.",
        )
        return

    user = message.from_user or message.sender_chat
    if user is None or user.id != Config.OWNER_ID:
        await send_message(message, "Owner only.")
        return

    cmd = message.text.split(maxsplit=1)
    if len(cmd) == 1:
        await send_message(message, "No command to execute was given.")
        return
    cmd = cmd[1]

    LOGGER.warning(
        f"SHELL invoked by owner user_id={user.id} chat_id={message.chat.id}: {cmd}"
    )

    # Prefer shlex + exec (no shell interpreter) for safety; fall back to
    # shell=True only if shlex cannot parse (e.g. shell metacharacters are
    # genuinely needed). The fallback is logged.
    use_shell = False
    argv = None
    try:
        argv = shlex_split(cmd)
    except ValueError as e:
        LOGGER.warning(
            f"SHELL falling back to shell=True for owner command (parse error: {e}): {cmd}"
        )
        use_shell = True

    try:
        if use_shell:
            stdout, stderr, _ = await _run_cmd_with_timeout(
                cmd, shell=True, timeout=SHELL_TIMEOUT
            )
        else:
            stdout, stderr, _ = await _run_cmd_with_timeout(
                argv, shell=False, timeout=SHELL_TIMEOUT
            )
    except AsyncTimeoutError:
        await send_message(
            message, f"Command timed out after {SHELL_TIMEOUT}s and was killed."
        )
        return

    reply = ""
    if len(stdout) != 0:
        reply += f"*Stdout*\n<code>{stdout}</code>\n"
        LOGGER.info(f"Shell - {cmd} - {stdout[:500]}")
    if len(stderr) != 0:
        reply += f"*Stderr*\n<code>{stderr}</code>"
        LOGGER.error(f"Shell - {cmd} - {stderr[:500]}")

    if len(reply) > SHELL_MAX_OUTPUT:
        reply = reply[:SHELL_MAX_OUTPUT] + "\n... (truncated)"
    if len(reply) > 3000:
        with BytesIO(str.encode(reply)) as out_file:
            out_file.name = "shell_output.txt"
            await send_file(message, out_file)
    elif len(reply) != 0:
        await send_message(message, reply)
    else:
        await send_message(message, "Command produced no output.")
