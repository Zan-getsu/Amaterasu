"""Shared presentation rules for Amaterasu's Telegram interface."""

from re import DOTALL, compile as re_compile

UI_MARK = "✦"
SYSTEM_METRICS_MARKER = "<b>✦ SYSTEM METRICS</b>"

_PANEL_HEADER = re_compile(r"(?<!<blockquote>)<b>✦ ([^<\n]+)</b>")
_FIRST_MENU_TITLE = re_compile(r"^\s*<b>(?!✦ )([^<\n]+)</b>")
_TREE_BLOCK = re_compile(r"<(?P<tag>code|pre)>(?P<body>.*?)</(?P=tag)>", DOTALL)
_TREE_PREFIXES = ("┌─", "├─", "└─")


_BUTTON_LABELS = {
    "Back": "‹ BACK",
    "↩ Back": "‹ BACK",
    "↩ BACK": "‹ BACK",
    "← Back": "‹ BACK",
    "No, Back": "‹ BACK",
    "Close": "✕ CLOSE",
    "Cancel": "✕ CANCEL",
    "❌ Cancel": "✕ CANCEL",
    "Cancel Process": "✕ CANCEL",
    "Check Again": "↻ CHECK AGAIN",
    "Previous": "‹ PREV",
    "<< Previous": "‹ PREV",
    "Prev Page": "‹ PREV",
    "❮ PREV": "‹ PREV",
    "Next": "NEXT ›",
    "Next >>": "NEXT ›",
    "Next Page": "NEXT ›",
    "Next →": "NEXT ›",
    "NEXT ❯": "NEXT ›",
    "Done Selecting": "✓ DONE",
    "Pincode": "⌗ PINCODE",
    "Yes!": "✓ CONFIRM",
    "✅ Confirm": "✓ CONFIRM",
    "No": "✕ CANCEL",
    "Edit": "✎ EDIT",
    "View": "◉ VIEW",
    "Reset": "↻ RESET",
    "↻ Reset": "↻ RESET",
    "Add New": "＋ ADD NEW",
    "Add new key": "＋ ADD KEY",
    "Create New File": "＋ CREATE FILE",
    "➕ Create Profile": "＋ CREATE PROFILE",
    "Remove Image": "✕ REMOVE IMAGE",
    "Remove All": "✕ REMOVE ALL",
    "Remove Server": "✕ REMOVE SERVER",
    "Skip": "SKIP ›",
    "General Settings": "✦ GENERAL SETTINGS",
    "⚙ Mirror Settings": "☁ MIRROR SETTINGS",
    "⚙ Leech Settings": "📨 LEECH SETTINGS",
    "⚙ Uphoster Settings": "🔗 UPHOSTER SETTINGS",
    "⚙ FF Media Settings": "🎛 FF MEDIA SETTINGS",
    "🎬 Encode Profiles": "🎬 ENCODE PROFILES",
    "Mics Settings": "⚙ MISC SETTINGS",
    "Reset All": "↻ RESET ALL",
    "Config Variables": "⚙ CONFIG VARIABLES",
    "Module Settings": "🧩 MODULE SETTINGS",
    "Private Files": "🔐 PRIVATE FILES",
    "Qbit Settings": "🧲 QBITTORRENT SETTINGS",
    "Aria2c Settings": "⚡ ARIA2C SETTINGS",
    "Sabnzbd Settings": "📰 SABNZBD SETTINGS",
    "JDownloader Sync": "🔄 JDOWNLOADER SYNC",
    "Encode Preset": "🎬 ENCODE PRESET",
    "📜 TSTATS": "📊 TASK STATS",
}


def style_inline_button(label):
    """Return a consistent label without changing its callback or URL."""
    if not isinstance(label, str):
        return label
    label = label.replace("\u2756", UI_MARK)
    return _BUTTON_LABELS.get(label, label)


def _format_tree_fields(line):
    fields = []
    for part in line.split(" | "):
        if ":" not in part:
            return None
        label, value = part.split(":", 1)
        label = label.strip()
        if not label:
            return None
        value = value.strip()
        value_markup = (
            value if "<" in value and ">" in value else f"<code>{value}</code>"
        )
        fields.append(f"<b>{label}:</b> {value_markup}")
    return "  •  ".join(fields)


def _style_tree_block(match):
    body = match.group("body")
    lines = body.strip("\n").splitlines()
    tree_rows = sum(
        line.lstrip().startswith(_TREE_PREFIXES) for line in lines
    )
    if tree_rows < 2:
        return match.group(0)

    styled = []
    for raw_line in lines:
        line = raw_line.strip()
        for prefix in _TREE_PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix) :].strip()
                break

        if not line:
            continue
        if "───" in line:
            title = line.replace("─", "").strip()
            if title:
                styled.append(f"\n<b><i>{title}</i></b>")
            continue

        fields = _format_tree_fields(line)
        if fields:
            styled.append(f" • {fields}")
        else:
            styled.append(f"<b><i>{line}</i></b>")

    return "\n".join(styled)


def style_inline_text(text, has_buttons=False):
    """Apply the shared panel language while preserving System Metrics verbatim."""
    if not isinstance(text, str) or not text:
        return text

    metrics_index = text.find(SYSTEM_METRICS_MARKER)
    if metrics_index >= 0:
        editable = text[:metrics_index]
        protected_metrics = text[metrics_index:]
    else:
        editable = text
        protected_metrics = ""

    editable = _PANEL_HEADER.sub(
        lambda match: (
            f"<blockquote><b>{UI_MARK} {match.group(1)}</b></blockquote>"
        ),
        editable,
    )
    if has_buttons and not editable.lstrip().startswith("<blockquote>"):
        editable = _FIRST_MENU_TITLE.sub(
            lambda match: (
                f"<blockquote><b>{UI_MARK} {match.group(1)}</b></blockquote>"
            ),
            editable,
            count=1,
        )
    editable = _TREE_BLOCK.sub(_style_tree_block, editable)
    return f"{editable}{protected_metrics}"
