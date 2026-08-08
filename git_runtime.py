"""Build Git commands that preserve bind-mounted repository ownership.

The application container runs as root for its media-engine capabilities, but
the project directory may be owned by any host UID/GID.  Git commands are
therefore routed through a tiny wrapper that drops only the Git child process
to the project directory's numeric owner.  No host path, username, UID, or GID
is assumed.
"""

from pathlib import Path
from sys import executable

_WRAPPER = Path(__file__).resolve().parent / "scripts" / "git_as_repo_owner.py"


def git_command(*args, repo="."):
    """Return a command line that runs Git as *repo*'s numeric owner."""
    return [
        executable,
        str(_WRAPPER),
        "--repo",
        str(Path(repo).resolve()),
        "--",
        *args,
    ]
