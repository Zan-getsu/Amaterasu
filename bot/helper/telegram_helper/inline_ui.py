"""Shared presentation rules for Amaterasu's Telegram interface."""

from re import DOTALL
from re import compile as re_compile

try:
    from .ui_style import style_panel_text
except ImportError:  # Support direct module loading in isolated tests.
    from bot.helper.telegram_helper.ui_style import style_panel_text

UI_MARK = "✦"

_BUTTON_LABELS = {
    "Back": "↩ BACK",
    "↩ Back": "↩ BACK",
    "↩ BACK": "↩ BACK",
    "← Back": "↩ BACK",
    "No, Back": "↩ BACK",
    "Back To Root": "↩ ROOT",
    "Previous": "❮ PREV",
    "<< Previous": "❮ PREV",
    "Prev Page": "❮ PREV",
    "❮ PREV": "❮ PREV",
    "Next": "NEXT ❯",
    "Next >>": "NEXT ❯",
    "Next Page": "NEXT ❯",
    "Next →": "NEXT ❯",
    "NEXT ❯": "NEXT ❯",
    "Close": "✕ CLOSE",
    "Cancel": "✕ CANCEL",
    "❌ Cancel": "✕ CANCEL",
    "Cancel Process": "✕ CANCEL",
    "No": "✕ CANCEL",
    "Yes!": "✓ CONFIRM",
    "✅ Confirm": "✓ CONFIRM",
    "Done": "✓ DONE",
    "Done Selecting": "✓ DONE",
    "Skip": "↷ SKIP",
    "Check Again": "↻ CHECK AGAIN",
    "Refresh": "↻ REFRESH",
    "Edit": "✦ EDIT",
    "View": "✦ VIEW",
    "Reset": "↻ RESET",
    "↻ Reset": "↻ RESET",
    "Add New": "✦ ADD NEW",
    "Add new key": "✦ ADD KEY",
    "Create New File": "✦ CREATE FILE",
    "➕ Create Profile": "✦ CREATE PROFILE",
    "Remove Image": "✕ REMOVE IMAGE",
    "Remove All": "✕ REMOVE ALL",
    "Remove Server": "✕ REMOVE SERVER",
    "Clear Selection": "✕ CLEAR SELECTION",
    "Git Repo": "✦ GIT REPO",
    "Updates": "✦ UPDATES",
    "Owner Config": "✦ OWNER CONFIG",
    "My Config": "✦ MY CONFIG",
    "Owner Token": "✦ OWNER TOKEN",
    "My Token": "✦ MY TOKEN",
    "Service Accounts": "✦ SERVICE ACCOUNTS",
    "📜 TSTATS": "📊 TASK STATS",
}

_LEGACY_MENU_PREFIXES = ("◉ ", "▣ ", "◈ ", "⌁ ", "⌬ ", "◆ ", "⚙ ")
_PREMIUM_PREFIXES = ("✦ ", "↩ ", "↻ ", "✕ ")
_LEGACY_TREE_BLOCK = re_compile(r"<code>(?P<body>.*?)</code>", DOTALL)
_TREE_PREFIXES = ("┌─", "├─", "└─")


def style_inline_button(label):
    """Return a consistent label without changing its callback or URL."""
    if not isinstance(label, str):
        return label

    label = label.replace("\u2756", UI_MARK).strip()
    label = _BUTTON_LABELS.get(label, label)
    for prefix in _LEGACY_MENU_PREFIXES:
        if label.startswith(prefix):
            label = f"{UI_MARK} {label[len(prefix):]}"
            break
    for prefix in _PREMIUM_PREFIXES:
        if label.startswith(prefix):
            return f"{prefix}{label[len(prefix):].upper()}"
    return label


def _style_legacy_tree(match):
    """Upgrade legacy code-tree cards while leaving ordinary code untouched."""
    lines = match.group("body").strip("\n").splitlines()
    if not lines or any(
        not line.strip().startswith(_TREE_PREFIXES) for line in lines
    ):
        return match.group(0)

    fields = []
    for raw_line in lines:
        row = raw_line.strip()[2:].strip()
        if ":" not in row:
            return match.group(0)
        label, value = row.split(":", 1)
        label = label.strip()
        value = value.strip()
        if not label:
            return match.group(0)
        fields.append((label, value))

    rendered = []
    for index, (label, value) in enumerate(fields):
        if len(fields) == 1 or index == len(fields) - 1:
            branch = "╰─"
        elif index == 0:
            branch = "╭─"
        else:
            branch = "├─"
        rendered.append(
            f"{branch} <b>{label}</b> : <code>{value}</code>"
        )
    return "\n".join(rendered)


def style_inline_text(text, has_buttons=False):
    """Apply premium cards while preserving intentional preformatted panels."""
    del has_buttons
    styled = style_panel_text(text)
    return _LEGACY_TREE_BLOCK.sub(_style_legacy_tree, styled)
