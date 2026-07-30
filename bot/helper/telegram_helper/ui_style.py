"""Shared, non-destructive presentation rules for Telegram messages."""

from re import compile as re_compile

UI_MARK = "✦"

_UNDERLINED_HEADER = re_compile(
    r"^(?P<space>\s*)<b><u>(?P<title>[^<\n]+)</u></b>"
)
_PLAIN_HEADER = re_compile(
    r"^(?P<space>\s*)(?P<icon>[^<\w\n]{0,8}\s*)"
    r"<b>(?P<title>[^<\n]+)</b>"
)
_LEADING_SYMBOLS = re_compile(r"^[^\w<]+")


def _render_header(title):
    title = title.strip()
    if title.startswith(UI_MARK):
        return f"<b>{title}</b>"
    title = _LEADING_SYMBOLS.sub("", title)
    return f"<b>{UI_MARK} {title.upper()}</b>"


def style_panel_text(text):
    """Normalize only the first panel header; never rewrite fields or code."""
    if not isinstance(text, str) or not text:
        return text

    text = text.replace("\u2756", UI_MARK)

    match = _UNDERLINED_HEADER.match(text)
    if match:
        return (
            f"{match.group('space')}"
            f"{_render_header(match.group('title'))}"
            f"{text[match.end():]}"
        )

    match = _PLAIN_HEADER.match(text)
    if not match:
        return text
    return (
        f"{match.group('space')}"
        f"{_render_header(match.group('title'))}"
        f"{text[match.end():]}"
    )
