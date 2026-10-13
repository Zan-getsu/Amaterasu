"""Give episode font packs distinct identities without changing their glyphs."""

from hashlib import sha256
from io import BytesIO


def namespace_font(data, prefix):
    try:
        from fontTools.ttLib import TTCollection, TTFont, TTLibError
    except ImportError as error:
        raise ValueError("FontTools is required to resolve embedded font conflicts; update the runtime dependencies.") from error

    aliases = {}

    def rename(original, *, postscript=False):
        value = prefix + original
        # PostScript font identifiers must fit the OpenType 63-character limit.
        if postscript and len(value) > 63:
            value = value[:46] + "_" + sha256(value.encode()).hexdigest()[:16]
        return value

    output = BytesIO()
    collection = None
    fonts = []
    try:
        if data[:4] == b"ttcf":
            collection = TTCollection(BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
            fonts = collection.fonts
        else:
            fonts = [TTFont(BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)]
        for font in fonts:
            for name in list(font["name"].names):
                if name.nameID not in {1, 3, 4, 6, 16, 18, 21}:
                    continue
                original = name.toUnicode()
                renamed = rename(original, postscript=name.nameID == 6)
                if name.nameID != 3:
                    aliases[original.strip().casefold()] = renamed
                font["name"].setName(renamed, name.nameID, name.platformID, name.platEncID, name.langID)
            if "CFF " in font:
                cff = font["CFF "].cff
                cff.fontNames = [rename(name, postscript=True) for name in cff.fontNames]
                for top in cff.topDictIndex:
                    for field in ("FamilyName", "FullName", "FontName"):
                        if hasattr(top, field):
                            setattr(top, field, rename(getattr(top, field), postscript=field == "FontName"))
            # A signature cannot remain valid after changing a font's names.
            if "DSIG" in font:
                del font["DSIG"]
        if collection:
            collection.save(output)
        else:
            fonts[0].save(output)
    except (TTLibError, KeyError, UnicodeError) as error:
        raise ValueError(f"Could not rename a conflicting embedded font: {error}") from error
    finally:
        for font in fonts:
            font.close()
    return output.getvalue(), aliases
