"""Join same-format text tracks without flattening ASS styling."""

import re
from decimal import Decimal


def _seconds(clock):
    hours, minutes, seconds = clock.strip().replace(",", ".").split(":")
    return Decimal(hours) * 3600 + Decimal(minutes) * 60 + Decimal(seconds)


def _clock(value, ass=False):
    scale = 100 if ass else 1000
    ticks = int((value * scale).to_integral_value())
    hours, ticks = divmod(ticks, 3600 * scale)
    minutes, ticks = divmod(ticks, 60 * scale)
    seconds, fraction = divmod(ticks, scale)
    return (f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}" if ass
            else f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}")


def read_document(text, codec):
    if codec == "subrip":
        events = []
        for block in re.split(r"\n\s*\n", text.lstrip("\ufeff").strip().replace("\r\n", "\n")):
            lines = block.splitlines()
            if not lines:
                continue
            if lines[0].strip().isdigit():
                lines.pop(0)
            if not lines:
                raise ValueError("An SRT subtitle contains an incomplete event.")
            match = re.fullmatch(r"\s*(\d+:\d+:\d+[, .]\d+)\s*-->\s*(\d+:\d+:\d+[, .]\d+)(.*)", lines[0])
            if not match:
                raise ValueError("An SRT subtitle contains an unreadable event.")
            events.append((_seconds(match[1]), _seconds(match[2]), match[3], "\n".join(lines[1:])))
        return {"codec": codec, "key": (), "events": events}

    sections = {}
    section = None
    for line in text.lstrip("\ufeff").splitlines():
        if line.strip().startswith("[") and line.strip().endswith("]"):
            section = line.strip().casefold()
            sections.setdefault(section, [])
        elif section and line.strip() and not line.lstrip().startswith(";"):
            sections[section].append(line)
    if set(sections) - {"[script info]", "[v4+ styles]", "[events]"}:
        raise ValueError("This ASS script has additional sections that require independent tracks.")
    settings = {}
    for line in sections.get("[script info]", []):
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError("An ASS subtitle contains unreadable script settings.")
        settings[key.strip().casefold()] = value.strip()
    style_format = []
    styles = []
    for line in sections.get("[v4+ styles]", []):
        key, _, value = line.partition(":")
        if key.strip().casefold() == "format":
            style_format = [field.strip() for field in value.split(",")]
        elif key.strip().casefold() == "style":
            fields = [field.strip() for field in value.split(",")]
            if len(fields) != len(style_format):
                raise ValueError("An ASS subtitle contains an unreadable style.")
            styles.append(dict(zip(style_format, fields, strict=True)))
    event_format = []
    events = []
    for line in sections.get("[events]", []):
        key, _, value = line.partition(":")
        if key.strip().casefold() == "format":
            event_format = [field.strip() for field in value.split(",")]
        elif key.strip().casefold() == "dialogue":
            fields = value.lstrip().split(",", len(event_format) - 1)
            if len(fields) != len(event_format):
                raise ValueError("An ASS subtitle contains an unreadable dialogue.")
            event = dict(zip(event_format, fields, strict=True))
            if not {"Start", "End", "Style", "Text"} <= event.keys():
                raise ValueError("An ASS subtitle has an unsupported event format.")
            event["Start"] = _seconds(event["Start"])
            event["End"] = _seconds(event["End"])
            events.append(event)
    if "Name" not in style_format or not event_format or event_format[-1] != "Text":
        raise ValueError("An ASS subtitle has an unsupported style or event format.")
    # Informational credits do not affect rendering; every other setting does.
    credits = {"title", "original script", "original translation", "original editing",
               "original timing", "synch point", "script updated by", "update details"}
    identity = tuple(sorted((key, value) for key, value in settings.items() if key not in credits))
    return {"codec": codec, "key": (identity, tuple(style_format), tuple(event_format)),
            "settings": settings, "style_format": style_format, "styles": styles,
            "event_format": event_format, "events": events}


def join_documents(documents):
    codec = documents[0]["codec"]
    if any((doc["codec"], doc["key"]) != (codec, documents[0]["key"]) for doc in documents):
        raise ValueError("Subtitle formats or ASS rendering settings differ.")
    if codec == "subrip":
        events = sorted((event for doc in documents for event in doc["events"]), key=lambda event: event[0])
        return "\n\n".join(
            f"{index}\n{_clock(start)} --> {_clock(end)}{suffix}\n{text}"
            for index, (start, end, suffix, text) in enumerate(events, 1)
        ) + "\n"

    styles = []
    events = []
    for index, doc in enumerate(documents, 1):
        names = {style["Name"]: f"Part{index}_{style['Name']}" for style in doc["styles"]}
        if len(names) != len(doc["styles"]):
            raise ValueError("An ASS subtitle contains duplicate style names.")
        styles.extend(dict(style, Name=names[style["Name"]]) for style in doc["styles"])
        for original in doc["events"]:
            event = original.copy()
            if event["Style"] not in names:
                raise ValueError("An ASS dialogue refers to a missing style.")
            event["Style"] = names[event["Style"]]
            # Named resets inside override blocks must follow the renamed style.
            event["Text"] = re.sub(
                r"\{[^}]*\}",
                lambda block, names=names: _rename_resets(block[0], names),
                event["Text"],
            )
            events.append(event)
    base = documents[0]
    lines = ["[Script Info]"]
    lines.extend(f"{key}: {value}" for key, value in base["settings"].items())
    lines += ["[V4+ Styles]", "Format: " + ", ".join(base["style_format"])]
    lines.extend("Style: " + ",".join(style[key] for key in base["style_format"]) for style in styles)
    lines += ["[Events]", "Format: " + ", ".join(base["event_format"])]
    for event in sorted(events, key=lambda event: event["Start"]):
        lines.append("Dialogue: " + ",".join(
            _clock(event[key], ass=True) if key in {"Start", "End"} else event[key]
            for key in base["event_format"]
        ))
    return "\n".join(lines) + "\n"


def _rename_resets(block, names):
    def rename(match):
        if match[1] not in names:
            raise ValueError("An ASS override refers to a missing style.")
        return "\\r" + names[match[1]]
    return re.sub(r"\\r([^\\}]+)", rename, block)
