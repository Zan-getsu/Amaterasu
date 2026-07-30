"""Shared presentation rules for Amaterasu inline keyboards."""

UI_MARK = "✦"


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
}


def style_inline_button(label):
    """Return a consistent label without changing its callback or URL."""
    if not isinstance(label, str):
        return label
    label = label.replace("\u2756", UI_MARK)
    return _BUTTON_LABELS.get(label, label)
