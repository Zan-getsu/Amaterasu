import ast
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = (
    ROOT
    / "bot"
    / "helper"
    / "mirror_leech_utils"
    / "download_utils"
    / "yt_dlp_download.py"
)


def _load_definitions(*names, namespace=None):
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    loaded = {"__name__": "ytdlp_thumbnail_recovery_test"}
    loaded.update(namespace or {})
    exec(compile(module, str(SOURCE_PATH), "exec"), loaded)
    return tuple(loaded[name] for name in names)


def test_invalid_thumbnail_is_nonfatal_but_other_errors_are_not_hidden():
    class FakePostProcessingError(Exception):
        pass

    class FakeEmbedThumbnailPP:
        error = None

        def run(self, info):
            if self.error:
                raise self.error
            return ["thumbnail"], info

        def report_warning(self, message):
            self.warning = message

    (resilient_pp,) = _load_definitions(
        "ResilientEmbedThumbnailPP",
        namespace={
            "EmbedThumbnailPP": FakeEmbedThumbnailPP,
            "PostProcessingError": FakePostProcessingError,
        },
    )

    processor = resilient_pp()
    info = {"filepath": "video.mp4"}
    assert processor.run(info) == (["thumbnail"], info)

    processor.error = FakePostProcessingError("could not determine image type")
    assert processor.run(info) == ([], info)
    assert "keeping the downloaded media" in processor.warning

    processor.error = RuntimeError("disk write failed")
    try:
        processor.run(info)
    except RuntimeError as error:
        assert str(error) == "disk write failed"
    else:
        raise AssertionError("Non-thumbnail failures must remain fatal")


def test_embed_postprocessor_is_replaced_without_mutating_original_options():
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            self.added = []

        def add_post_processor(self, processor, when="post_process"):
            self.added.append((processor, when))

    class FakeResilientPP:
        def __init__(self, downloader, **options):
            self.downloader = downloader
            self.options = options

    (builder,) = _load_definitions(
        "_build_resilient_ytdlp",
        namespace={
            "YoutubeDL": FakeYoutubeDL,
            "ResilientEmbedThumbnailPP": FakeResilientPP,
        },
    )
    options = {
        "postprocessors": [
            {"key": "FFmpegMetadata"},
            {
                "key": "EmbedThumbnail",
                "already_have_thumbnail": True,
                "when": "post_process",
            },
        ]
    }

    downloader = builder(options)

    assert options["postprocessors"][1]["key"] == "EmbedThumbnail"
    assert downloader.options["postprocessors"] == [{"key": "FFmpegMetadata"}]
    assert len(downloader.added) == 1
    processor, when = downloader.added[0]
    assert when == "post_process"
    assert processor.options == {"already_have_thumbnail": True}


def test_extractor_filename_entities_are_decoded_and_download_uses_recovery():
    (decode_entities,) = _load_definitions(
        "_decode_filename_entities",
        namespace={"unescape": unescape},
    )
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert decode_entities("Video.mp4&#x20;") == "Video.mp4"
    assert decode_entities("A&amp;#x20;B.mp4") == "A B.mp4"
    assert decode_entities("") == ""
    assert "with _build_resilient_ytdlp(self.opts) as ydl:" in source


def test_ytdlp_download_reports_unexpected_errors_instead_of_hiding_them():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "YoutubeDLHelper"
    )
    download = next(
        node
        for node in helper.body
        if isinstance(node, ast.FunctionDef) and node.name == "_download"
    )

    suppress_calls = [
        node
        for node in ast.walk(download)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "suppress"
    ]
    assert not suppress_calls
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "_on_download_error"
        for node in ast.walk(download)
    )
