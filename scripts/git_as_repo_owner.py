#!/usr/bin/env python3
"""Execute Git using the numeric owner of a repository working directory."""

import os
import sys
from argparse import REMAINDER, ArgumentParser
from pathlib import Path
from subprocess import run


def main():
    parser = ArgumentParser(add_help=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("git_args", nargs=REMAINDER)
    parsed = parser.parse_args()

    repo = Path(parsed.repo).resolve()
    git_args = parsed.git_args
    if git_args[:1] == ["--"]:
        git_args = git_args[1:]
    if not git_args:
        parser.error("a Git command is required")

    repo_stat = os.stat(repo)
    env = os.environ.copy()

    # A mismatch is usually evidence that an older root-running updater has
    # already damaged ownership. Refuse to guess or perpetuate it; the project
    # owner must remain the authority for both the worktree and Git metadata.
    git_marker = repo / ".git"
    if os.name == "posix" and os.geteuid() == 0 and git_marker.exists():
        git_stat = os.stat(git_marker)
        if git_stat.st_uid != repo_stat.st_uid:
            print(
                "Refusing Git write: project directory and .git have different "
                "owners. Repair the existing ownership mismatch once on the host.",
                file=sys.stderr,
            )
            raise SystemExit(73)

    # On Linux containers the parent is root. Drop only this Git process to
    # the bind mount owner's numeric identity; no passwd entry is required.
    if os.name == "posix" and os.geteuid() == 0 and (
        repo_stat.st_uid != os.geteuid() or repo_stat.st_gid != os.getegid()
    ):
        os.setgroups([])
        os.setgid(repo_stat.st_gid)
        os.setuid(repo_stat.st_uid)
        # Do not inherit root's global Git config after dropping privileges.
        env["HOME"] = "/nonexistent"
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"

    command = [
        "git",
        "-c",
        f"safe.directory={repo}",
        "-c",
        "user.email=AmaterasuBot@users.noreply.github.com",
        "-c",
        "user.name=Amaterasu",
        *git_args,
    ]
    # Keep the wrapper process so exit codes are propagated consistently on
    # both Linux and Windows test hosts. The Git child inherits the identity
    # already dropped above.
    result = run(command, env=env, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
