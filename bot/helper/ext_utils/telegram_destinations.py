from html import escape as html_escape

_LEGACY_MODE_PREFIXES = ("b:", "u:", "h:")
MAX_LEECH_DUMP_DESTINATIONS = 10
MAX_MANUAL_LEECH_DUMPS = 3
MAX_LEECH_DUMP_NAME_LENGTH = 32


def _destination_parts(value):
    if value is None or value == "":
        return []
    values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def _destination_key(chat_id, topic_id):
    chat_key = chat_id.lower() if isinstance(chat_id, str) else chat_id
    return chat_key, topic_id


def parse_leech_dump_destination(value, user_id=None):
    """Parse one Telegram chat/topic target into a canonical pair."""
    item = str(value).strip()
    if item[:2].lower() in _LEGACY_MODE_PREFIXES:
        item = item[2:].strip()

    chat_value, separator, topic_value = item.partition("|")
    chat_value = chat_value.strip()
    topic_value = topic_value.strip()
    if not chat_value:
        raise ValueError("A Leech Dump destination cannot be empty.")

    if chat_value.lower() == "pm":
        if separator:
            raise ValueError("PM destinations cannot include a topic ID.")
        chat_id = user_id if user_id is not None else "pm"
    elif chat_value.lstrip("-").isdigit():
        chat_id = int(chat_value)
        if chat_id == 0:
            raise ValueError("A Telegram chat ID cannot be zero.")
    elif (
        chat_value.startswith("@")
        and len(chat_value) > 1
        and chat_value[1:].isascii()
        and chat_value[1:].replace("_", "").isalnum()
    ):
        chat_id = chat_value
    else:
        raise ValueError(
            f"Invalid Leech Dump destination: {html_escape(chat_value)}. "
            "Use a numeric chat ID, @username, or pm. Usernames may only "
            "contain English letters, numbers, and underscores."
        )

    topic_id = None
    if separator:
        if not topic_value.isdigit() or int(topic_value) <= 0:
            raise ValueError(
                f"Invalid topic ID for {html_escape(chat_value)}. "
                "Topic IDs must be positive numbers."
            )
        topic_id = int(topic_value)
    return chat_id, topic_id


def parse_leech_dump_destinations(value, user_id=None):
    """Parse comma-separated Telegram dump targets into unique chat/topic pairs."""
    destinations = []
    seen = set()
    for item in _destination_parts(value):
        destination = parse_leech_dump_destination(item, user_id)
        key = _destination_key(*destination)
        if key in seen:
            continue
        seen.add(key)
        destinations.append(destination)
        if len(destinations) > MAX_LEECH_DUMP_DESTINATIONS:
            raise ValueError(
                f"A maximum of {MAX_LEECH_DUMP_DESTINATIONS} Leech Dump destinations is allowed."
            )
    return destinations


def format_leech_dump_destination(destination):
    chat_id, topic_id = destination
    return f"{chat_id}|{topic_id}" if topic_id is not None else str(chat_id)


def format_leech_dump_destinations(destinations):
    """Return a canonical legacy value suitable for storing in user settings."""
    return ", ".join(format_leech_dump_destination(item) for item in destinations)


def parse_named_leech_dumps(value):
    """Parse an atomic, newline-separated ``name destination`` configuration."""
    dumps = {}
    names = set()
    destinations = set()
    lines = str(value or "").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            name, raw_destination = line.rsplit(maxsplit=1)
        except ValueError as err:
            raise ValueError(
                f"Line {line_number}: use NAME DESTINATION, for example Movies -1001234567890."
            ) from err

        name = " ".join(name.split())
        if not name:
            raise ValueError(f"Line {line_number}: the dump name cannot be empty.")
        if len(name) > MAX_LEECH_DUMP_NAME_LENGTH:
            raise ValueError(
                f"Line {line_number}: dump names can contain at most "
                f"{MAX_LEECH_DUMP_NAME_LENGTH} characters."
            )
        if "," in name:
            raise ValueError(
                f"Line {line_number}: dump names cannot contain commas because "
                "commas separate names in -ud."
            )
        name_key = name.casefold()
        if name_key == "all":
            raise ValueError(f"Line {line_number}: 'all' is reserved for selecting every dump.")
        if name_key in names:
            raise ValueError(f"Line {line_number}: duplicate dump name '{html_escape(name)}'.")

        try:
            destination = parse_leech_dump_destination(raw_destination)
        except ValueError as err:
            raise ValueError(f"Line {line_number}: {err}") from err
        destination_key = _destination_key(*destination)
        if destination_key in destinations:
            raise ValueError(
                f"Line {line_number}: destination {html_escape(raw_destination)} "
                "is already saved "
                "under another name."
            )

        names.add(name_key)
        destinations.add(destination_key)
        dumps[name] = destination
        if len(dumps) > MAX_LEECH_DUMP_DESTINATIONS:
            raise ValueError(
                f"A maximum of {MAX_LEECH_DUMP_DESTINATIONS} saved Leech Dumps is allowed."
            )

    if not dumps:
        raise ValueError("Send at least one named Leech Dump destination.")
    return dumps


def format_named_leech_dumps(dumps):
    """Convert named canonical pairs into the dictionary stored in user data."""
    return {name: format_leech_dump_destination(destination) for name, destination in dumps.items()}


def normalize_named_leech_dumps(value, legacy_value=None, user_id=None):
    """Load current named dumps, with transparent legacy-setting compatibility."""
    raw_dumps = value if isinstance(value, dict) else {}
    if not raw_dumps and legacy_value:
        raw_dumps = {
            f"Legacy {index}": destination
            for index, destination in enumerate(_destination_parts(legacy_value), start=1)
        }

    normalized = []
    seen_names = set()
    seen_destinations = set()
    for name, raw_destination in raw_dumps.items():
        clean_name = " ".join(str(name).split())
        if not clean_name:
            raise ValueError("A saved Leech Dump has an empty name.")
        name_key = clean_name.casefold()
        if name_key in seen_names:
            raise ValueError(f"Duplicate saved Leech Dump name: {html_escape(clean_name)}.")
        destination = parse_leech_dump_destination(raw_destination, user_id)
        destination_key = _destination_key(*destination)
        if destination_key in seen_destinations:
            continue
        seen_names.add(name_key)
        seen_destinations.add(destination_key)
        normalized.append((clean_name, *destination))
        if len(normalized) > MAX_LEECH_DUMP_DESTINATIONS:
            raise ValueError(
                f"A maximum of {MAX_LEECH_DUMP_DESTINATIONS} saved Leech Dumps is allowed."
            )
    return normalized


def select_named_leech_dumps(dumps, requested):
    """Resolve ``-ud`` names; manual lists are capped while ``all`` is not."""
    requested = str(requested or "").strip()
    if not requested:
        return None
    if requested.casefold() == "all":
        return list(dumps)

    names = []
    seen_names = set()
    for name in requested.split(","):
        name = name.strip()
        name_key = name.casefold()
        if name and name_key not in seen_names:
            seen_names.add(name_key)
            names.append(name)
    if not names:
        raise ValueError("-ud requires a dump name or 'all'.")
    if len(names) > MAX_MANUAL_LEECH_DUMPS:
        raise ValueError(f"Choose at most {MAX_MANUAL_LEECH_DUMPS} named dumps, or use -ud all.")

    by_name = {item[0].casefold(): item for item in dumps}
    selected = []
    seen = set()
    for name in names:
        item = by_name.get(name.casefold())
        if item is None:
            available = ", ".join(html_escape(entry[0]) for entry in dumps) or "None"
            raise ValueError(
                f"Leech Dump '{html_escape(name)}' was not found. Available dumps: {available}."
            )
        destination_key = _destination_key(item[1], item[2])
        if destination_key not in seen:
            seen.add(destination_key)
            selected.append(item)
    return selected
