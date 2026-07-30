LEECH_FONT_STYLES = ("b", "i", "u", "s", "code", "spoiler")


def normalize_leech_font(value):
    font = str(value or "").strip().lower()
    return font if font in LEECH_FONT_STYLES else ""


def resolve_leech_font(user_settings, default=""):
    user_font = normalize_leech_font((user_settings or {}).get("LEECH_FONT"))
    return user_font or normalize_leech_font(default)


def apply_leech_font(text, value):
    font = normalize_leech_font(value)
    return f"<{font}>{text}</{font}>" if font else text
