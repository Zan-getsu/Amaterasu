def get_user_mention(user):
    """Return a mention across WZGram's property and Pyrogram's method APIs."""
    mention = getattr(user, "mention", None)
    if callable(mention):
        try:
            return mention(style="html")
        except TypeError:
            return mention()
    if mention:
        return str(mention)
    return getattr(user, "title", "Unknown")
