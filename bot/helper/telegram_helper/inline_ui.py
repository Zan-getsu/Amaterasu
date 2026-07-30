"""Shared presentation rules for Amaterasu's Telegram interface."""

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
    "Owner Config": "✦ OWNER CONFIG",
    "My Config": "✦ MY CONFIG",
    "Owner Token": "✦ OWNER TOKEN",
    "My Token": "✦ MY TOKEN",
    "Service Accounts": "✦ SERVICE ACCOUNTS",
    "📜 TSTATS": "📊 TASK STATS",
}

_LEGACY_MENU_PREFIXES = ("◉ ", "▣ ", "◈ ", "⌁ ", "⌬ ", "◆ ", "⚙ ")
_PREMIUM_PREFIXES = ("✦ ", "↩ ", "↻ ", "✕ ")


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


def style_inline_text(text, has_buttons=False):
    """Normalize only the panel header and preserve fields and code blocks."""
    del has_buttons
    return style_panel_text(text)
