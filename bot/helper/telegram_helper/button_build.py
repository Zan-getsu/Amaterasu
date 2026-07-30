from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ...core.config_manager import Config

_BUTTON_LABELS = {
    "Back": "↩ BACK",
    "↩ Back": "↩ BACK",
    "← Back": "↩ BACK",
    "No, Back": "↩ BACK",
    "Back To Root": "↩ ROOT",
    "Previous": "❮ PREV",
    "<< Previous": "❮ PREV",
    "Prev Page": "❮ PREV",
    "Next": "NEXT ❯",
    "Next >>": "NEXT ❯",
    "Next Page": "NEXT ❯",
    "Next →": "NEXT ❯",
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
}
_LEGACY_MENU_PREFIXES = ("◉ ", "▣ ", "◈ ", "⌁ ", "⌬ ", "◆ ", "⚙ ")
_PREMIUM_PREFIXES = (
    "✦ ",
    "↩ ",
    "↻ ",
    "✕ ",
)


def _btn_style(style=None):
    if Config.COLORED_BTNS and style:
        return style
    return ButtonStyle.DEFAULT


def _premium_label(label):
    """Keep inline-keyboard typography consistent across every bot surface."""
    if not isinstance(label, str):
        return label
    label = label.replace("\u2756", "✦").strip()
    label = _BUTTON_LABELS.get(label, label)
    for prefix in _LEGACY_MENU_PREFIXES:
        if label.startswith(prefix):
            label = f"✦ {label[len(prefix):]}"
            break
    for prefix in _PREMIUM_PREFIXES:
        if label.startswith(prefix):
            return f"{prefix}{label[len(prefix):].upper()}"
    return label


class ButtonMaker:
    def __init__(self):
        self.buttons = {
            "default": [],
            "header": [],
            "f_body": [],
            "l_body": [],
            "footer": [],
        }

    def url_button(self, key, link, position=None, style=None):
        self.buttons[position if position in self.buttons else "default"].append(
            InlineKeyboardButton(
                text=_premium_label(key), url=link, style=_btn_style(style)
            )
        )

    def data_button(self, key, data, position=None, style=None):
        self.buttons[position if position in self.buttons else "default"].append(
            InlineKeyboardButton(
                text=_premium_label(key),
                callback_data=data,
                style=_btn_style(style),
            )
        )

    def build_menu(self, b_cols=1, h_cols=8, fb_cols=2, lb_cols=2, f_cols=8):
        def chunk(lst, n):
            return [lst[i : i + n] for i in range(0, len(lst), n)]

        menu = chunk(self.buttons["default"], b_cols)
        menu = (
            chunk(self.buttons["header"], h_cols) if self.buttons["header"] else []
        ) + menu
        for key, cols in (("f_body", fb_cols), ("l_body", lb_cols), ("footer", f_cols)):
            if self.buttons[key]:
                menu += chunk(self.buttons[key], cols)
        return InlineKeyboardMarkup(menu)

    def reset(self):
        for key in self.buttons:
            self.buttons[key].clear()
