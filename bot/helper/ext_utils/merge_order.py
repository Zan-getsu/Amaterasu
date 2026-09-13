"""Stable filename ordering for downloaded folders and torrent episodes."""

import re

_EXPLICIT_EPISODE = (
    re.compile(r"(?<![A-Za-z0-9])s(\d{1,3})[ ._-]*e(\d{1,4})(?!\d)", re.I),
    re.compile(r"(?<![A-Za-z0-9])(\d{1,3})x(\d{1,4})(?!\d)", re.I),
    re.compile(r"(?<![A-Za-z0-9])(?:episode|ep)[ ._-]*(\d{1,4})(?!\d)", re.I),
)
_SEASON_DIRECTORY = re.compile(r"^(?:season|s)[ ._-]*(\d{1,3})$", re.I)


def natural_key(value):
    normalized = str(value).replace("\\", "/")
    parts = tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", normalized)
    )
    return parts, normalized


def episode_sort_key(value):
    text = str(value).replace("\\", "/")
    name = text.rsplit("/", 1)[-1]
    for pattern in _EXPLICIT_EPISODE[:2]:
        match = pattern.search(name)
        if match:
            return (0, int(match[1]), int(match[2]), natural_key(text))
    match = _EXPLICIT_EPISODE[2].search(name)
    if match:
        season = next(
            (int(found[1]) for part in reversed(text.split("/")[:-1])
             if (found := _SEASON_DIRECTORY.fullmatch(part))),
            0,
        )
        return (0, season, int(match[1]), natural_key(text))
    return (1, 0, 0, natural_key(text))
