"""Reproducible tiny media fixtures for the FFmpeg/MKVToolNix copy backends."""

import asyncio
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.helper.ext_utils.merge_fonts import namespace_font
from bot.helper.ext_utils.merge_media import (
    _check_selected_streams,
    _font_names,
    _json_command,
    _mkvmerge_binary,
    _origin,
    _video_span,
    associate_sidecars,
    merge_copy,
    merge_encode,
    validate_merge_encode_profile,
)
from bot.helper.ext_utils.merge_subtitles import join_documents, read_document, rename_fonts


def _run(*args):
    subprocess.run(args, check=True, capture_output=True)


def _probe(path, *fields):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_data_hash", "sha256", *fields, "-of", "json", str(path)
    ]))


def _expected_embedded_times(sources, chapters):
    times = []
    for source, chapter in zip(sources, chapters, strict=True):
        info = _probe(source, "-show_streams", "-show_packets")
        tracks = {stream["index"] for stream in info["streams"] if stream["codec_type"] == "subtitle"}
        offset = float(chapter["start_time"]) - float(_origin(info))
        times.extend(float(packet["pts_time"]) + offset for packet in info["packets"] if packet["stream_index"] in tracks)
    return sorted(times)


def _ass(title, size, colour):
    return f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 640
PlayResY: 360
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{size},{colour},&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.20,0:00:00.80,Default,,0,0,0,,{title}
"""


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe") and _mkvmerge_binary()):
        pytest.skip("FFmpeg and MKVToolNix are required for the media integration fixtures")
    root = tmp_path_factory.mktemp("merge-media")
    subtitles = (
        ("first.ass", _ass("First", 22, "&H00FFFFFF")),
        ("second.ass", _ass("Second", 32, "&H0000FFFF")),
        ("third.srt", "1\n00:00:00,200 --> 00:00:00,800\nThird\n"),
    )
    files = []
    for index, (name, content) in enumerate(subtitles, 1):
        subtitle = root / name
        subtitle.write_text(content, encoding="utf-8")
        output = root / f"{index}.mkv"
        _run(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=24:d=1.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
            "-i", str(subtitle), "-map", "0:v", "-map", "1:a", "-map", "2:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-c:s", "copy", str(output),
        )
        files.append(output)
    return root, files


@pytest.fixture(scope="module")
def cover_media(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe") and _mkvmerge_binary()):
        pytest.skip("FFmpeg and MKVToolNix are required for the media integration fixtures")
    root = tmp_path_factory.mktemp("merge-cover")
    base = root / "base.mp4"
    art = root / "cover.jpg"
    _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=1.5",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base),
    )
    _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=64x64:r=1:d=1",
        "-frames:v", "1", str(art),
    )
    files = []
    for index in (1, 2):
        target = root / f"episode-{index}.mp4"
        _run(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(base), "-i", str(art),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:v:0",
            "-c", "copy", "-disposition:v:1", "attached_pic", str(target),
        )
        files.append(target)
    return root, files


def _listener():
    return SimpleNamespace(is_cancelled=False, subproc=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("difference", [
    "header", "missing-header", "index", "audio-rate", "language", "disposition",
    "origin", "opus", "duration", "subtitle-tail", "missing-duration", "newline",
])
async def test_concat_keeps_unproven_inputs_on_mkv_path(tmp_path, monkeypatch, difference):
    from copy import deepcopy

    from bot.helper.ext_utils import merge_media as backend

    probe = {"format": {"start_time": "0", "duration": "1.5"}, "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "extradata_hash": "video",
         "start_time": "0", "duration": "1.5"},
        {"index": 1, "codec_type": "audio", "codec_name": "aac", "extradata_hash": "audio",
         "start_time": "0", "duration": "1.5", "sample_rate": "48000"},
    ]}
    changed = deepcopy(probe)
    video, audio = changed["streams"]
    files = [str(tmp_path / "first.mkv"), str(tmp_path / "second.mkv")]
    if difference == "header":
        video["extradata_hash"] = "different"
    elif difference == "missing-header":
        video.pop("extradata_hash")
    elif difference == "index":
        audio["index"] = 2
    elif difference == "audio-rate":
        audio["sample_rate"] = "44100"
    elif difference == "language":
        audio["tags"] = {"language": "eng"}
    elif difference == "disposition":
        audio["disposition"] = {"default": 1}
    elif difference == "origin":
        video["start_time"] = audio["start_time"] = "0.12"
    elif difference == "opus":
        audio["codec_name"] = "opus"
    elif difference in {"duration", "subtitle-tail"}:
        changed["format"]["duration"] = "12"
        if difference == "subtitle-tail":
            changed["streams"].append({"index": 2, "codec_type": "subtitle", "duration": "12"})
    elif difference == "missing-duration":
        video.pop("duration")
    else:
        files[1] += "\nfile malicious"

    async def unexpected_run(*args, **kwargs):
        pytest.fail("Unsafe inputs must not enter FFmpeg concat")

    monkeypatch.setattr(backend, "_run", unexpected_run)
    assert not await backend._concat_av(files, [probe, changed], str(tmp_path / "out.mkv"), str(tmp_path), _listener())


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["plain", "subtitles", "video-only", "mp4", "hevc", "fallback", "shifted", "cancel"])
async def test_ffmpeg_concat_retains_all_tracks_and_mkv_safeguards(media, monkeypatch, case):
    from bot.helper.ext_utils import merge_media as backend

    root, sources = media
    folder = root / f"concat {case} l'été"
    folder.mkdir()
    selected = []
    has_audio = case not in {"video-only", "fallback", "shifted"}
    for index in range(3):
        target = folder / f"part '{index}.{'mp4' if case == 'mp4' else 'mkv'}"
        # Delay-free audio keeps concat coverage independent of AAC priming conventions.
        command = ["ffmpeg", "-v", "error", "-y",
                   "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=24:d=1.5",
                   "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
                   "-i", str(sources[index % 2]), "-map", "0:v"]
        if has_audio:
            command += ["-map", "1:a", "-map", "1:a", "-metadata:s:a:0", "language=jpn",
                        "-metadata:s:a:0", "title=Japanese", "-metadata:s:a:1", "language=eng",
                        "-metadata:s:a:1", "title=English", "-disposition:a:0", "0", "-disposition:a:1", "0"]
        if case == "subtitles":
            command += ["-map", "2:s", "-metadata:s:s:0", "language=eng", "-disposition:s:0", "default"]
        command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac" if case == "mp4" else "alac", "-c:s", "copy"]
        if case == "hevc":
            command += ["-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "pools=1:frame-threads=1:log-level=error:bframes=0"]
        if case != "mp4":
            command += ["-avoid_negative_ts", "make_zero"]
        _run(*command, "-metadata", "title=Series", str(target))
        selected.append(str(target))
    probes = [_probe(path, "-show_streams", "-show_format") for path in selected]
    hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    original_run = backend._run
    original_json = backend._json_command
    concat_commands = []
    append_commands = []

    async def run(arguments, listener, **kwargs):
        if "concat" in arguments:
            concat_commands.append(arguments)
            if case in {"fallback", "cancel"}:
                Path(arguments[-1]).write_bytes(b"partial concat output")
                listener.is_cancelled = case == "cancel"
                return 1, "Injected concat failure"
        if "--generate-chapters" in arguments:
            append_commands.append(arguments)
        return await original_run(arguments, listener, **kwargs)

    async def inspect(arguments, listener):
        result = await original_json(arguments, listener)
        if case == "shifted" and Path(arguments[-1]).name == "timeline.mkv" and not append_commands:
            result["streams"][0]["start_time"] = "0.5"
        return result

    monkeypatch.setattr(backend, "_run", run)
    monkeypatch.setattr(backend, "_json_command", inspect)
    if case == "mp4":
        # Keep a real multi-audio AAC fallback case on every toolchain.
        monkeypatch.setattr(backend, "_concat_av", AsyncMock(return_value=False))
    listener = _listener()
    target = folder / "merged.mkv"
    output, error = await merge_copy(listener, selected, str(target), probes)
    assert len(concat_commands) <= 1 if case == "mp4" else len(concat_commands) == 1
    if case != "mp4":
        assert bool(append_commands) == (case in {"fallback", "shifted"})
    else:
        assert append_commands
    assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    assert not list(folder.glob("merge-*/"))
    if case == "cancel":
        assert output is False and "cancelled" in error.lower()
        assert not target.exists()
        return
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets", "-show_format")
    assert len(info["chapters"]) == 3
    assert info["format"]["tags"]["title"] == "Series"
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    source_audio = [stream for stream in probes[0]["streams"] if stream["codec_type"] == "audio"]
    source_identity = json.loads(subprocess.check_output([backend._mkvmerge_binary(), "-J", selected[0]]))
    source_titles = [(track.get("properties") or {}).get("track_name") for track in source_identity["tracks"] if track["type"] == "audio"]
    assert len(audio) == len(source_audio) == (2 if has_audio else 0)
    assert [(stream.get("tags", {}).get("language"), stream.get("tags", {}).get("title"), stream["disposition"]["default"]) for stream in audio] == [
        (stream.get("tags", {}).get("language"), title, stream["disposition"]["default"]) for stream, title in zip(source_audio, source_titles, strict=True)
    ]
    for position, stream in enumerate(audio):
        expected = []
        times = []
        for source, probe, chapter in zip(selected, probes, info["chapters"], strict=True):
            packets = _probe(source, "-select_streams", f"a:{position}", "-show_packets")["packets"]
            expected += [packet["data_hash"] for packet in packets]
            times += [float(packet["pts_time"]) + float(chapter["start_time"]) - float(_origin(probe)) for packet in packets]
        actual = [packet for packet in info["packets"] if packet["stream_index"] == stream["index"]]
        assert [packet["data_hash"] for packet in actual] == expected
        if case != "mp4":
            assert [float(packet["pts_time"]) for packet in actual] == pytest.approx(times, abs=0.003)
    frames = []
    for source in selected:
        frames.extend((await backend._video_frames(source, [0], listener))[0])
    assert await backend._video_frames(output, [0], listener) == {0: frames}
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(subtitles) == int(case == "subtitles")
    if subtitles:
        assert [float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] == subtitles[0]["index"]] == pytest.approx(
            _expected_embedded_times(selected, info["chapters"]), abs=0.006)
        document = read_document(subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", output, "-map", "0:s", "-c:s", "copy", "-f", "ass", "pipe:1"
        ]).decode("utf-8-sig"), "ass")
        assert {style["Fontsize"] for style in document["styles"]} == {"22", "32"}
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a?", "-f", "null", "-")


@pytest.mark.asyncio
async def test_json_inspection_uses_stdout_when_tool_warns_on_stderr():
    result = await _json_command(
        [
            sys.executable,
            "-c",
            "import json, sys; sys.stderr.write('harmless warning\\n'); "
            "sys.stdout.write(json.dumps({'tracks': [], 'padding': 'x' * 20000}))",
        ],
        _listener(),
    )

    assert result["tracks"] == []
    assert len(result["padding"]) == 20000


def _font_bytes(family="Example", postscript="Example-Regular"):
    names = [(1, family), (2, "Regular"), (6, postscript)]
    strings = b""
    records = []
    for name_id, value in names:
        encoded = value.encode("utf-16-be")
        records.append(struct.pack(">HHHHHH", 3, 1, 1033, name_id, len(encoded), len(strings)))
        strings += encoded
    name_table = struct.pack(">HHH", 0, len(records), 6 + len(records) * 12) + b"".join(records) + strings
    return struct.pack(">IHHHH", 0x00010000, 1, 0, 0, 0) + struct.pack(">4sIII", b"name", 0, 28, len(name_table)) + name_table


def _renderable_font(variant=0, kind="ttf", family="MergeCollision"):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTCollection, TTFont

    if kind == "ttc":
        collection = TTCollection()
        collection.fonts = [TTFont(BytesIO(_renderable_font(variant, family=family))),
                            TTFont(BytesIO(_renderable_font(variant, family=family + "Alternate")))]
        output = BytesIO()
        collection.save(output)
        collection.close()
        return output.getvalue()
    builder = FontBuilder(1000, isTTF=kind == "ttf")
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({65: "A"})
    glyphs = {}
    for name in (".notdef", "A"):
        pen = TTGlyphPen(None) if kind == "ttf" else T2CharStringPen(600, None)
        if name == "A":
            pen.moveTo((50, 0))
            pen.lineTo((50, 700))
            pen.lineTo((250 + variant * 200, 700))
            pen.lineTo((250 + variant * 200, 0))
            pen.closePath()
        glyphs[name] = pen.glyph() if kind == "ttf" else pen.getCharString()
    if kind == "ttf":
        builder.setupGlyf(glyphs)
    else:
        builder.setupCFF(family + "-Regular", {"FamilyName": family, "FullName": family + " Regular"}, glyphs, {})
    builder.setupHorizontalMetrics({name: (600, 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": "Regular",
                           "fullName": family + " Regular", "psName": family + "-Regular",
                           "uniqueFontIdentifier": family + str(variant)})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    output = BytesIO()
    builder.save(output)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["ttf", "otf", "ttc"])
def test_conflicting_font_namespace_keeps_glyphs_and_metrics(kind):
    from fontTools.ttLib import TTCollection, TTFont

    original = _renderable_font(kind=kind)
    renamed, aliases = namespace_font(original, "Episode2_")
    assert aliases["mergecollision"] == "Episode2_MergeCollision"
    assert not (_font_names(original) & _font_names(renamed))
    before = TTCollection(BytesIO(original)) if kind == "ttc" else TTFont(BytesIO(original))
    after = TTCollection(BytesIO(renamed)) if kind == "ttc" else TTFont(BytesIO(renamed))
    before_fonts = before.fonts if kind == "ttc" else [before]
    after_fonts = after.fonts if kind == "ttc" else [after]
    for source, result in zip(before_fonts, after_fonts, strict=True):
        for table in ("cmap", "hmtx", "OS/2", "glyf", "loca"):
            if table in source:
                assert source.getTableData(table) == result.getTableData(table)
        if "CFF " in source:
            assert result["CFF "].cff.fontNames == ["Episode2_" + name for name in source["CFF "].cff.fontNames]
            for glyph in source.getGlyphOrder():
                left = source["CFF "].cff.topDictIndex[0].CharStrings[glyph]
                right = result["CFF "].cff.topDictIndex[0].CharStrings[glyph]
                left.decompile()
                right.decompile()
                assert left.program == right.program
    before.close()
    after.close()


def test_ass_font_references_update_styles_and_overrides_only():
    document = read_document(_ass(r"{\fnArial}AAAA{\fn@ARIAL}A{\fn}Arial", 22, "&H00FFFFFF"), "ass")
    assert rename_fonts(document, {"arial": "Episode2_Arial"})
    assert document["styles"][0]["Fontname"] == "Episode2_Arial"
    assert document["events"][0]["Text"] == r"{\fnEpisode2_Arial}AAAA{\fn@Episode2_Arial}A{\fn}Arial"


@pytest.mark.parametrize("kind", ["ttf", "otf"])
def test_namespace_keeps_long_postscript_names_valid_and_distinct(kind):
    from fontTools.ttLib import TTFont

    source = _renderable_font(kind=kind, family="A" * 55)
    names = []
    for prefix in ("Episode1_", "Episode2_"):
        renamed, aliases = namespace_font(source, prefix)
        font = TTFont(BytesIO(renamed))
        postscript = font["name"].getDebugName(6)
        assert len(postscript) <= 63
        assert aliases[("A" * 55 + "-Regular").casefold()] == postscript
        if "CFF " in font:
            assert font["CFF "].cff.fontNames == [postscript]
        names.append(postscript)
        font.close()
    assert names[0] != names[1]


@pytest.mark.asyncio
async def test_ass_styles_join_continuously_and_srt_keeps_its_format(media):
    root, files = media
    probes = [_probe(path, "-show_streams", "-show_format") for path in files]
    output, error = await merge_copy(
        _listener(), list(map(str, files)), str(root / "merged.mkv"), probes
    )
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets", "-show_data_hash", "sha256")
    assert [stream["codec_name"] for stream in info["streams"] if stream["codec_type"] == "subtitle"] == [
        "ass", "subrip"
    ]
    assert len(info["chapters"]) == 3
    assert [chapter["tags"]["title"] for chapter in info["chapters"]] == ["1", "2", "3"]
    assert [float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] in {2, 3, 4}] == pytest.approx(
        _expected_embedded_times(files, info["chapters"]), abs=0.006
    )
    assert probes[0]["streams"][2]["codec_name"] == "ass"
    extracted = root / "joined.ass"
    _run("ffmpeg", "-v", "error", "-y", "-i", output, "-map", "0:s:0", "-c:s", "copy", str(extracted))
    text = extracted.read_text(encoding="utf-8-sig")
    assert "Part1_Default,Arial,22,&H00FFFFFF" in text
    assert "Part2_Default,Arial,32,&H0000FFFF" in text
    assert "Part1_Default,,0,0,0,,First" in text
    assert "Part2_Default,,0,0,0,,Second" in text
    ass_packets = [packet for packet in info["packets"] if packet["stream_index"] == 2]
    assert len(ass_packets) == 2


def test_font_name_parser_detects_internal_identity():
    assert ("family-style", "example", "regular") in _font_names(_font_bytes())
    assert ("postscript", "example-regular") in _font_names(_font_bytes())


@pytest.mark.asyncio
@pytest.mark.parametrize("hex_data,expected", [
    ("4c69 6e65 310a 4c69 6e65 32", b"Line1\nLine2"),
    ("4c69 6e65 310d 0a4c 696e 6532", b"Line1\nLine2"),
    ("4c69 6e65 310d 4c69 6e65 32", b"Line1\nLine2"),
    ("4c69 6e65 3120 0a4c 696e 6532", b"Line1 \nLine2"),
])
async def test_text_packet_hashes_normalize_only_line_endings(monkeypatch, hex_data, expected):
    from bot.helper.ext_utils import merge_media as backend

    async def inspect(arguments, listener):
        return {"packets": [{"data": f"\n00000000: {hex_data:<39}  text\n"}]}

    monkeypatch.setattr(backend, "_json_command", inspect)
    assert await backend._text_packet_hashes("unused.mkv", 0, _listener()) == [hashlib.sha256(expected).digest()]


@pytest.mark.asyncio
@pytest.mark.parametrize("packet", [{}, {"data": "invalid hex dump"}])
async def test_text_packet_hashes_reject_missing_or_unreadable_data(monkeypatch, packet):
    from bot.helper.ext_utils import merge_media as backend

    async def inspect(arguments, listener):
        return {"packets": [packet]}

    monkeypatch.setattr(backend, "_json_command", inspect)
    with pytest.raises(ValueError, match="Subtitle text packet data"):
        await backend._text_packet_hashes("unused.mkv", 0, _listener())


@pytest.mark.asyncio
@pytest.mark.parametrize("sidecar", [False, True])
@pytest.mark.parametrize("continuous", [False, True])
async def test_mixed_ass_and_multiline_srt_preserve_text_bytes_and_timing(media, sidecar, continuous):
    root, files = media
    prefix = f"multiline-{sidecar}-{continuous}"
    selected, sidecars, texts, event_times = [], {}, [], []
    for index, source in enumerate((files[0], files[1], files[0])):
        target = root / f"{prefix}-{index}.mkv"
        subtitle = root / f"{prefix}-{index}.en.srt"
        present = continuous or index == 2
        text = f"\t<i>日本語, part {index}</i>  \n  Second line, with comma"
        if present:
            subtitle.write_text(f"1\n00:00:00,200 --> 00:00:00,800\n{text}\n", encoding="utf-8")
            texts.append(text)
        command = ["ffmpeg", "-v", "error", "-y", "-i", str(source)]
        if present and not sidecar:
            command += ["-i", str(subtitle)]
        command += ["-map", "0"]
        if present and not sidecar:
            command += ["-map", "1:s"]
        _run(*command, "-c", "copy", str(target))
        selected.append(str(target))
        if present and sidecar:
            sidecars[str(target)] = [str(subtitle)]
    probes = [_probe(path, "-show_streams", "-show_format") for path in selected]
    hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    output, error = await merge_copy(_listener(), selected, str(root / f"{prefix}-merged.mkv"), probes, sidecars=sidecars)
    assert not error
    info = _probe(output, "-show_streams", "-show_packets", "-show_chapters", "-show_data_hash", "sha256")
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert sorted(stream["codec_name"] for stream in subtitles) == ["ass", "subrip"]
    srt_index = next(stream["index"] for stream in subtitles if stream["codec_name"] == "subrip")
    packets = [packet for packet in info["packets"] if packet["stream_index"] == srt_index]
    for index, chapter in enumerate(info["chapters"]):
        if not continuous and index != 2:
            continue
        if sidecar:
            source = _probe(sidecars[selected[index]][0], "-select_streams", "s", "-show_packets", "-show_data_hash", "sha256")
            offset = float(chapter["start_time"])
        else:
            source = _probe(selected[index], "-select_streams", "s:1", "-show_packets", "-show_data_hash", "sha256")
            offset = float(chapter["start_time"]) - float(_origin(probes[index]))
        event_times.extend(float(packet["pts_time"]) + offset for packet in source["packets"])
    assert [float(packet["pts_time"]) for packet in packets] == pytest.approx(event_times, abs=0.003)
    extracted = root / f"{prefix}-checked.srt"
    _run("ffmpeg", "-v", "error", "-y", "-i", output, "-map", f"0:{srt_index}", "-c:s", "copy", str(extracted))
    document = read_document(extracted.read_text(encoding="utf-8-sig"), "subrip")
    assert [event[-1] for event in document["events"]] == texts
    assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]


@pytest.mark.asyncio
@pytest.mark.parametrize("codec", ["ass", "subrip"])
async def test_subtitle_dialogue_mutation_fails_before_publication(media, monkeypatch, codec):
    from bot.helper.ext_utils import merge_media as backend

    root, files = media
    selected = files[:2]
    if codec == "subrip":
        selected = []
        for index, source in enumerate(files[:2]):
            subtitle = root / f"corruptible-{index}.srt"
            subtitle.write_text(f"1\n00:00:00,200 --> 00:00:00,800\n{'First' if index == 0 else 'Later'}\nSecond line\n", encoding="utf-8")
            target = root / f"corruptible-{index}.mkv"
            _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-i", str(subtitle),
                 "-map", "0:v", "-map", "0:a", "-map", "1:s", "-c", "copy", str(target))
            selected.append(target)
    original_run = backend._run
    hashes = [hashlib.sha256(path.read_bytes()).digest() for path in selected]

    async def corrupt_dialogue(arguments, listener, **kwargs):
        result = await original_run(arguments, listener, **kwargs)
        if Path(str(arguments[0])).stem.casefold() == "mkvmerge" and "--chapters" in arguments:
            candidate = Path(arguments[arguments.index("-o") + 1])
            data = candidate.read_bytes()
            before, after = (b",,First", b",,Wrong") if codec == "ass" else (b"First", b"Wrong")
            assert data.count(before) == 1
            candidate.write_bytes(data.replace(before, after))
        return result

    monkeypatch.setattr(backend, "_run", corrupt_dialogue)
    target = root / f"corrupted-subtitle-{codec}.mkv"
    output, error = await merge_copy(_listener(), list(map(str, selected)), str(target),
                                    [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert output is False
    assert error == "Subtitle event content changed for item 1."
    assert not target.exists()
    assert not list(root.glob("merge-*/"))
    assert hashes == [hashlib.sha256(path.read_bytes()).digest() for path in selected]


def test_font_collection_checks_identity_of_every_face():
    first = bytearray(_font_bytes("First", "First-Regular"))
    second = bytearray(_font_bytes("Second", "Second-Regular"))
    first_offset, second_offset = 20, 20 + len(first)
    for face, offset in ((first, first_offset), (second, second_offset)):
        struct.pack_into(">I", face, 20, struct.unpack_from(">I", face, 20)[0] + offset)
    data = struct.pack(">4sIIII", b"ttcf", 0x00010000, 2, first_offset, second_offset) + first + second
    names = _font_names(data)
    assert ("postscript", "first-regular") in names
    assert ("postscript", "second-regular") in names
    with pytest.raises(ValueError, match="face directory"):
        _font_names(struct.pack(">4sII", b"ttcf", 0x00010000, 0))


def test_continuous_profile_rejects_settings_it_cannot_honor():
    assert "keyframe interval" in validate_merge_encode_profile({
        "video_codec": "libx264", "audio_codec": "aac",
        "video_params": {"keyint_seconds": 4},
    })
    assert "burn-in" in validate_merge_encode_profile({
        "video_codec": "libx264", "audio_codec": "aac",
        "subtitle_mode": "burn", "video_params": {},
    })


def test_data_is_rejected_but_attached_cover_is_not_timeline_video():
    with pytest.raises(ValueError, match="data stream"):
        _check_selected_streams([{"streams": [{"codec_type": "data"}]}])
    probe = {"streams": [
        {"codec_type": "video", "disposition": {"attached_pic": 1}, "duration": "500", "start_time": "-2"},
        {"codec_type": "video", "index": 1, "duration": "2", "start_time": "0"},
    ]}
    _check_selected_streams([probe])
    assert _video_span(probe) == 2
    assert _origin(probe) == 0


@pytest.mark.asyncio
async def test_source_cover_art_is_omitted_from_copy_and_encode(cover_media):
    root, files = cover_media
    probes = [_probe(path, "-show_streams", "-show_format") for path in files]
    assert all(any((stream.get("disposition") or {}).get("attached_pic")
                   for stream in probe["streams"]) for probe in probes)
    for mode in ("copy", "encode"):
        output_path = str(root / f"merged-{mode}.mkv")
        if mode == "copy":
            output, error = await merge_copy(
                _listener(), list(map(str, files)), output_path, probes
            )
        else:
            output, error = await merge_encode(
                _listener(), list(map(str, files)), output_path, probes,
                {"video_codec": "libx264", "audio_codec": "aac",
                 "video_params": {"preset": "ultrafast", "crf": 28},
                 "audio_params": {"channels": 1, "sample_rate": 48000}},
            )
        assert not error
        info = _probe(output, "-show_streams", "-show_chapters")
        assert [stream["codec_type"] for stream in info["streams"]] == ["video", "audio"]
        assert len(info["chapters"]) == 2
        mkv = json.loads(subprocess.check_output([_mkvmerge_binary(), "-J", output]))
        assert not mkv.get("attachments")


@pytest.mark.asyncio
async def test_cancelled_merge_never_publishes_an_output(media):
    root, files = media
    listener = _listener()
    listener.is_cancelled = True
    target = root / "cancelled.mkv"
    output, error = await merge_copy(
        listener, list(map(str, files[:2])), str(target),
        [_probe(path, "-show_streams", "-show_format") for path in files[:2]],
    )
    assert output is False
    assert "cancelled" in error.lower()
    assert not target.exists()
    assert listener.subproc is None


@pytest.mark.asyncio
async def test_merge_does_not_replace_an_existing_artifact(media):
    root, files = media
    target = root / "already-owned.mkv"
    target.write_bytes(b"existing result")
    output, error = await merge_copy(
        _listener(), list(map(str, files[:2])), str(target),
        [_probe(path, "-show_streams", "-show_format") for path in files[:2]],
    )
    assert output is False
    assert "already exists" in error
    assert target.read_bytes() == b"existing result"


@pytest.mark.asyncio
async def test_missing_subtitle_interval_keeps_sparse_original_tracks(media):
    root, files = media
    no_sub = root / "second-without-subtitles.mkv"
    _run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(files[1]),
         "-map", "0:v", "-map", "0:a", "-c", "copy", str(no_sub))
    selected = [files[0], no_sub, files[2]]
    output, error = await merge_copy(
        _listener(), list(map(str, selected)), str(root / "missing-interval.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
    )
    assert not error
    info = _probe(output, "-show_streams", "-show_packets", "-show_chapters")
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert [stream["codec_name"] for stream in subtitles] == ["ass", "subrip"]
    starts = [float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] in {stream["index"] for stream in subtitles}]
    assert starts == pytest.approx(_expected_embedded_times(selected, info["chapters"]), abs=0.006)


@pytest.mark.asyncio
async def test_identical_font_attachment_is_deduplicated(media):
    root, files = media
    font = root / "proof.ttf"
    font.write_bytes(_font_bytes())
    with_font = []
    for index, source in enumerate(files[:2], 1):
        target = root / f"font-{index}.mkv"
        _run(_mkvmerge_binary(), "--quiet", "-o", str(target), "--attach-file", str(font), str(source))
        with_font.append(target)
    selected = [*with_font, files[2]]
    output, error = await merge_copy(
        _listener(), list(map(str, selected)), str(root / "with-font.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
    )
    assert not error
    identity = json.loads(subprocess.check_output([_mkvmerge_binary(), "-J", output]))
    assert len(identity["attachments"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ttf", "otf", "ttc"])
@pytest.mark.parametrize("encoded", [False, True])
async def test_conflicting_fonts_merge_and_render_each_episode_correctly(media, kind, encoded):
    root, files = media
    selected = []
    for index, source in enumerate(files[:2]):
        font = root / f"collision.{kind}"
        font.write_bytes(_renderable_font(index, kind))
        subtitle = root / f"collision-{kind}-{index}.ass"
        subtitle.write_text(_ass(r"AA{\fnMergeCollision}AA", 48, "&H00FFFFFF").replace(",Arial,", ",MergeCollision,"), encoding="utf-8")
        intermediate = root / f"collision-{kind}-{index}-base.mkv"
        target = root / f"collision-{kind}-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-i", str(subtitle),
             "-map", "0:v", "-map", "0:a", "-map", "1:s", "-c", "copy", str(intermediate))
        _run(_mkvmerge_binary(), "--quiet", "-o", str(target), "--attachment-mime-type",
             "font/otf" if kind == "otf" else "font/ttf", "--attach-file", str(font), str(intermediate))
        selected.append(str(target))
    source_hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    arguments = (_listener(), selected, str(root / f"font-conflicts-{kind}-{encoded}.mkv"),
                 [_probe(path, "-show_streams", "-show_format") for path in selected])
    if encoded:
        output, error = await merge_encode(*arguments, {
            "video_codec": "libx264", "audio_codec": "aac",
            "video_params": {"preset": "ultrafast", "crf": 0},
        })
    else:
        output, error = await merge_copy(*arguments)
    assert not error
    identity = json.loads(subprocess.check_output([_mkvmerge_binary(), "-J", output]))
    assert len(identity["attachments"]) == 2
    assert len([track for track in identity["tracks"] if track["type"] == "subtitles"]) == 1
    chapters = _probe(output, "-show_chapters")["chapters"]

    def rendered_frame(path, time):
        result = subprocess.check_output(["ffmpeg", "-v", "error", "-i", Path(path).name,
            "-vf", f"subtitles={Path(path).name}:si=0", "-ss", str(time), "-frames:v", "1", "-an", "-f", "framemd5", "pipe:1"], cwd=root)
        return [line.rsplit(b",", 1)[-1].strip() for line in result.splitlines() if line and not line.startswith(b"#")]

    originals = [rendered_frame(path, 0.4) for path in selected]
    assert originals[0] != originals[1]
    for index, original in enumerate(originals):
        assert original == rendered_frame(output, float(chapters[index]["start_time"]) + 0.4)
    assert source_hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]


@pytest.mark.asyncio
async def test_three_av1_aac_episodes_join_english_ass_with_conflicting_fonts(media):
    if b"libsvtav1" not in subprocess.check_output(["ffmpeg", "-v", "error", "-encoders"]):
        pytest.skip("SVT-AV1 is required for this production-format fixture")
    root, files = media
    selected = []
    for index, source in enumerate((files[0], files[1], files[0]), 1):
        font = root / "av1-collision.ttf"
        font.write_bytes(_renderable_font(index % 2))
        subtitle = root / f"av1-{index}.ass"
        subtitle.write_text(_ass("AAAA", 48, "&H00FFFFFF").replace(",Arial,", ",MergeCollision,"), encoding="utf-8")
        video = root / f"av1-{index}-base.mkv"
        target = root / f"av1-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-i", str(subtitle),
             "-map", "0:v", "-map", "0:a", "-map", "1:s", "-c:v", "libsvtav1",
             "-preset", "12", "-crf", "40", "-svtav1-params", "lp=2", "-c:a", "copy", "-c:s", "copy",
             "-metadata:s:a:0", "language=jpn", "-metadata:s:s:0", "language=eng",
             "-metadata:s:s:0", f"title=Episode {index:02d} - English", str(video))
        _run(_mkvmerge_binary(), "--quiet", "-o", str(target), "--attach-file", str(font), str(video))
        selected.append(str(target))
    output, error = await merge_copy(_listener(), selected, str(root / "av1-three-episodes.mkv"),
                                    [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets")
    video = [stream for stream in info["streams"] if stream["codec_type"] == "video"]
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(video) == len(audio) == len(subtitles) == 1
    assert (video[0]["codec_name"], audio[0]["codec_name"], subtitles[0]["codec_name"]) == ("av1", "aac", "ass")
    assert audio[0]["tags"]["language"] == "jpn"
    assert subtitles[0]["tags"]["language"] == "eng"
    assert subtitles[0]["disposition"]["default"]
    assert len(info["chapters"]) == 3
    events = [packet for packet in info["packets"] if packet["stream_index"] == subtitles[0]["index"]]
    assert [float(packet["pts_time"]) for packet in events] == pytest.approx(
        [float(chapter["start_time"]) + 0.2 for chapter in info["chapters"]], abs=0.03)
    frames = _probe(output, "-count_frames", "-select_streams", "v:0", "-show_streams")
    assert int(frames["streams"][0]["nb_read_frames"]) == 108
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a", "-f", "null", "-")


@pytest.mark.asyncio
@pytest.mark.parametrize("frames_ms", [(20, 20), (10, 60), (2.5, 40)])
async def test_av1_dual_opus_merge_preserves_audio_timestamps_and_multiline_subtitles(media, frames_ms, monkeypatch):
    from bot.helper.ext_utils import merge_media as backend

    original_run = backend._run

    async def run(arguments, listener, **kwargs):
        assert "concat" not in arguments, "Opus pre-skip requires the MKVToolNix append path"
        return await original_run(arguments, listener, **kwargs)

    monkeypatch.setattr(backend, "_run", run)
    root, _ = media
    label = f"opus-{frames_ms[0]}-{frames_ms[1]}"
    selected = []
    for index in range(3):
        ass = root / f"{label}-{index}.ass"
        srt = root / f"{label}-{index}.srt"
        ass.write_text(_ass(f"Episode {index}", 22, "&H00FFFFFF"), encoding="utf-8")
        srt.write_text(f"1\n00:00:00,200 --> 00:00:00,800\n<i>Français {index}</i>\n  Deuxième ligne\n", encoding="utf-8")
        target = root / f"{label}-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=24:d=1.5",
             "-f", "lavfi", "-i", f"sine=frequency={440 + index * 20}:sample_rate=48000:duration=1.5",
             "-f", "lavfi", "-i", f"sine=frequency={880 + index * 20}:sample_rate=48000:duration=1.5",
             "-i", str(ass), "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map", "4:s",
             "-c:v", "libsvtav1", "-preset", "12", "-crf", "40", "-pix_fmt", "yuv420p10le", "-svtav1-params", "lp=2",
             "-c:a", "libopus", "-ac:a", "2", "-frame_duration:a:0", str(frames_ms[0]),
             "-frame_duration:a:1", str(frames_ms[1]), "-c:s", "copy",
             "-metadata:s:a:0", "language=jpn", "-metadata:s:a:0", "title=Japanese", "-disposition:a:0", "default",
             "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English", "-disposition:a:1", "0",
             "-metadata:s:s:0", "language=eng", "-disposition:s:0", "default",
             "-metadata:s:s:1", "language=fra", "-disposition:s:1", "0", str(target))
        selected.append(str(target))
    probes = [_probe(path, "-show_streams", "-show_format", "-show_data_hash", "sha256") for path in selected]
    source_hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    output, error = await merge_copy(_listener(), selected, str(root / f"{label}-merged.mkv"), probes)
    assert not error
    info = _probe(output, "-show_streams", "-show_packets", "-show_chapters", "-show_data_hash", "sha256")
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert [(stream["codec_name"], stream["tags"]["language"], stream["tags"]["title"], stream["disposition"]["default"]) for stream in audio] == [
        ("opus", "jpn", "Japanese", 1), ("opus", "eng", "English", 0)]
    assert sorted(stream["codec_name"] for stream in subtitles) == ["ass", "subrip"]
    assert len(info["chapters"]) == 3
    for position, stream in enumerate(audio):
        actual = [packet for packet in info["packets"] if packet["stream_index"] == stream["index"]]
        times = [float(packet["pts_time"]) for packet in actual]
        assert all(right > left for left, right in zip(times, times[1:]))
        cursor = 0
        for path in selected:
            original = _probe(path, "-select_streams", f"a:{position}", "-show_packets", "-show_data_hash", "sha256")["packets"]
            part = actual[cursor:cursor + len(original)]
            assert [packet["data_hash"] for packet in part] == [packet["data_hash"] for packet in original]
            cursor += len(original)
        assert cursor == len(actual)
        # Earlier episodes' encoder padding does not extend the final timeline.
        expected_tail = float(info["chapters"][-1]["start_time"]) + float(original[-1]["pts_time"]) + float(original[-1]["duration_time"])
        assert times[-1] + float(actual[-1]["duration_time"]) == pytest.approx(expected_tail, abs=0.003)
    subtitle_indexes = {stream["index"] for stream in subtitles}
    assert sorted(float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] in subtitle_indexes) == pytest.approx(
        _expected_embedded_times(selected, info["chapters"]), abs=0.006)
    expected_frames = []
    for path in selected:
        expected_frames.extend((await backend._video_frames(path, [0], _listener()))[0])
    assert len(expected_frames) == 108
    assert await backend._video_frames(output, [0], _listener()) == {0: expected_frames}
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a", "-f", "null", "-")
    assert source_hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]


@pytest.mark.asyncio
async def test_external_ass_is_associated_with_only_its_episode(media):
    root, files = media
    no_sub = root / "second-without-subtitles.mkv"
    _run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(files[1]),
         "-map", "0:v", "-map", "0:a", "-c", "copy", str(no_sub))
    sidecar = root / "second-without-subtitles.en.forced.ass"
    sidecar.write_text(_ass("External", 28, "&H00FFFFFF"), encoding="utf-8")
    selected = [files[0], no_sub, files[2]]
    association = associate_sidecars(list(map(str, selected)), [str(sidecar)])
    assert association == {str(no_sub): [str(sidecar)]}
    output, error = await merge_copy(
        _listener(), list(map(str, selected)), str(root / "external.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
        sidecars=association,
    )
    assert not error
    info = _probe(output, "-show_streams", "-show_packets")
    assert [stream["codec_name"] for stream in info["streams"] if stream["codec_type"] == "subtitle"] == [
        "ass", "ass", "subrip"
    ]
    identity = json.loads(subprocess.check_output([_mkvmerge_binary(), "-J", output]))
    external = [track for track in identity["tracks"] if track["type"] == "subtitles"][1]
    assert external["properties"]["language"] in {"eng", "en"}
    assert external["properties"]["forced_track"] is True


def test_unmatched_sidecar_is_an_explicit_error(media):
    root, files = media
    with pytest.raises(ValueError, match="association is missing"):
        associate_sidecars(list(map(str, files)), [str(root / "unrelated.en.ass")])


@pytest.mark.parametrize("extension,content", [
    ("srt", "1\n00:00:00,200 --> 00:00:00,800\nExternal subtitle\n"),
    ("vtt", "WEBVTT\n\n00:00:00.200 --> 00:00:00.800\nExternal subtitle\n"),
])
@pytest.mark.asyncio
async def test_text_sidecar_formats_remain_selectable(media, extension, content):
    root, files = media
    sidecar = root / f"1_en.{extension}"
    sidecar.write_text(content, encoding="utf-8")
    selected = list(map(str, files[:2]))
    association = associate_sidecars(selected, [str(sidecar)])
    output, error = await merge_copy(
        _listener(), selected, str(root / f"external-{extension}.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
        sidecars=association,
    )
    assert not error
    info = _probe(output, "-show_streams", "-show_packets")
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    matching = [stream for stream in subtitles if stream["codec_name"] ==
                ("subrip" if extension == "srt" else "webvtt")]
    assert len(matching) == 1
    assert any(packet["stream_index"] == matching[0]["index"] for packet in info["packets"])


@pytest.mark.asyncio
async def test_mixed_resolution_and_codec_use_one_continuous_encode(media):
    root, files = media
    mixed = root / "second-mpeg4.mkv"
    _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(files[1]),
        "-map", "0", "-vf", "scale=320:240", "-c:v", "mpeg4",
        "-c:a", "copy", "-c:s", "copy", str(mixed),
    )
    selected = [files[0], mixed, files[2]]
    probes = [_probe(path, "-show_streams", "-show_format") for path in selected]
    output, error = await merge_encode(
        _listener(), list(map(str, selected)), str(root / "encoded.mkv"), probes,
        {"video_codec": "libx264", "audio_codec": "aac", "subtitle_mode": "copy",
         "video_params": {"preset": "medium", "crf": 28, "pix_fmt": "yuv420p", "profile": "high"},
         "audio_params": {"bitrate": "96k"}},
    )
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters")
    assert [stream["codec_name"] for stream in info["streams"] if stream["codec_type"] == "video"] == ["h264"]
    assert next(stream for stream in info["streams"] if stream["codec_type"] == "video")["profile"] == "High"
    assert [stream["codec_name"] for stream in info["streams"] if stream["codec_type"] == "subtitle"] == ["ass", "subrip"]
    assert len(info["chapters"]) == 3


def test_ass_named_style_resets_follow_namespaced_styles():
    first = _ass("First", 22, "&H00FFFFFF").replace("First\n", r"{\rDefault}First" + "\n")
    second = _ass("Second", 32, "&H0000FFFF")
    text = join_documents([read_document(first, "ass"), read_document(second, "ass")])
    assert r"{\rPart1_Default}First" in text
    assert "Part2_Default,Arial,32" in text
    with pytest.raises(ValueError, match="rendering settings"):
        join_documents([read_document(first, "ass"), read_document(second.replace("PlayResX: 640", "PlayResX: 1280"), "ass")])


@pytest.mark.asyncio
async def test_encode_accepts_equivalent_implicit_range_and_rejects_explicit_color_changes(media):
    root, files = media
    selected = list(map(str, files[:2]))
    profile = {"video_codec": "libx264", "audio_codec": "aac", "video_params": {"preset": "ultrafast"}}
    probes = [_probe(path, "-show_streams", "-show_format") for path in selected]
    videos = [next(stream for stream in probe["streams"] if stream["codec_type"] == "video") for probe in probes]
    videos[0].pop("color_range", None)
    videos[1]["color_range"] = "tv"
    output, error = await merge_encode(_listener(), selected, str(root / "implicit-limited-range.mkv"), probes, profile)
    assert output and not error
    for field, value in (("color_range", "pc"), ("color_transfer", "smpte2084")):
        original = videos[1].get(field)
        videos[1][field] = value
        output, error = await merge_encode(_listener(), selected, str(root / f"unsafe-{field}.mkv"), probes, profile)
        assert output is False
        assert "color or HDR" in error
        videos[1][field] = original


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_duration_is_rejected(value):
    with pytest.raises(ValueError, match="non-finite"):
        _video_span({"streams": [{"codec_type": "video", "duration": value}]})


@pytest.mark.asyncio
async def test_srt_sidecars_join_across_missing_interval_and_keep_languages(media):
    root, files = media
    selected = []
    for index, source in enumerate(files):
        target = root / f"srt-episode-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v", "-map", "0:a", "-c", "copy", str(target))
        selected.append(str(target))
    sidecars = []
    for index in (0, 2):
        for language in ("en", "ja"):
            sidecar = root / f"srt-episode-{index}.{language}.srt"
            sidecar.write_text(f"1\n00:00:00,200 --> 00:00:00,800\n{language} part {index}\n", encoding="utf-8")
            sidecars.append(str(sidecar))
    listener = _listener()
    output, error = await merge_copy(listener, selected, str(root / "continuous-srt.mkv"),
                                     [_probe(path, "-show_streams", "-show_format") for path in selected],
                                     sidecars=associate_sidecars(selected, sidecars))
    assert not error
    info = _probe(output, "-show_streams", "-show_packets", "-show_chapters")
    tracks = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(tracks) == 2
    assert {stream["tags"]["language"] for stream in tracks} == {"eng", "jpn"}
    for stream in tracks:
        events = [packet for packet in info["packets"] if packet["stream_index"] == stream["index"]]
        assert [float(packet["pts_time"]) for packet in events] == pytest.approx(
            [float(info["chapters"][index]["start_time"]) + 0.2 for index in (0, 2)], abs=0.003)
    assert listener.merge_subtitle_count == 2


@pytest.mark.asyncio
async def test_incompatible_ass_settings_stop_instead_of_separate_episode_tracks(media):
    root, files = media
    alternate = root / "alternate-resolution.ass"
    alternate.write_text(_ass("Alternate", 32, "&H0000FFFF").replace("PlayResX: 640", "PlayResX: 1280"), encoding="utf-8")
    second = root / "alternate-header.mkv"
    _run("ffmpeg", "-v", "error", "-y", "-i", str(files[1]), "-i", str(alternate),
         "-map", "0:v", "-map", "0:a", "-map", "1:s", "-c", "copy", str(second))
    selected = [str(files[0]), str(second)]
    output, error = await merge_copy(_listener(), selected, str(root / "separate-resolution.mkv"),
                                     [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert output is False
    assert "one continuous" in error
    assert "playresx" in error
    assert not (root / "separate-resolution.mkv").exists()


@pytest.mark.asyncio
async def test_video_only_continuous_encode(media):
    root, files = media
    selected = []
    for index, source in enumerate(files[:2]):
        target = root / f"silent-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v", "-c", "copy", str(target))
        selected.append(str(target))
    output, error = await merge_encode(_listener(), selected, str(root / "silent-encoded.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
        {"video_codec": "libx264", "audio_codec": "aac", "video_params": {"preset": "ultrafast"}})
    assert not error
    assert [s["codec_type"] for s in _probe(output, "-show_streams")["streams"]] == ["video"]


def test_srt_incomplete_block_is_a_validation_error():
    with pytest.raises(ValueError, match="SRT"):
        read_document("1", "subrip")


def test_ass_equal_start_events_keep_original_paint_order():
    text = _ass("Behind", 22, "&H00FFFFFF")
    text += "Dialogue: 0,0:00:00.20,0:00:00.40,Default,,0,0,0,,In front\n"
    result = read_document(join_documents([read_document(text, "ass")]), "ass")
    assert [event["Text"] for event in result["events"]] == ["Behind", "In front"]


@pytest.mark.asyncio
async def test_joined_ass_renders_identically_to_source_styles(media):
    root, files = media
    output, error = await merge_copy(_listener(), list(map(str, files[:2])), str(root / "render-proof.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in files[:2]])
    assert not error
    chapters = _probe(output, "-show_chapters")["chapters"]

    def rendered_frame(name, time):
        result = subprocess.run(["ffmpeg", "-v", "error", "-i", name,
            "-vf", f"subtitles={name}:si=0", "-ss", str(time), "-frames:v", "1", "-an", "-f", "framemd5", "pipe:1"],
            cwd=root, check=True, capture_output=True)
        return [line.rsplit(b",", 1)[-1].strip() for line in result.stdout.splitlines()
                if line and not line.startswith(b"#")]

    for index, source in enumerate(files[:2]):
        assert rendered_frame(source.name, 0.4) == rendered_frame("render-proof.mkv", float(chapters[index]["start_time"]) + 0.4)
    bare = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(files[0]), "-ss", "0.4",
                                   "-frames:v", "1", "-an", "-f", "framemd5", "pipe:1"])
    bare_hash = [line.rsplit(b",", 1)[-1].strip() for line in bare.splitlines() if line and not line.startswith(b"#")]
    assert rendered_frame(files[0].name, 0.4) != bare_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("episode_titles", [False, True])
async def test_three_english_ass_episodes_with_editor_metadata_join_into_one_track(media, episode_titles):
    root, files = media
    selected = []
    for index, source in enumerate((files[0], files[1], files[0]), 1):
        ass = root / f"episode-header-{index}.ass"
        text = _ass(f"Episode {index}", 18 + index * 3, "&H00FFFFFF")
        text = text.replace("ScriptType:", f"Episode: {index}\nScriptType:")
        if index != 1:
            text = text.replace("[V4+ Styles]", "WrapStyle: 0\nKerning: no\nCollisions: Normal\n[Aegisub Project Garbage]\nLast Style Storage: Episode " + str(index) + "\n[V4+ Styles]")
        ass.write_text(text, encoding="utf-8")
        target = root / f"english-episode-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-i", str(ass),
             "-map", "0:v", "-map", "0:a", "-map", "1:s", "-c", "copy",
             "-metadata:s:s:0", "language=eng", "-metadata:s:s:0",
             f"title={'English - Episode ' + str(index) if episode_titles else 'English'}", str(target))
        selected.append(str(target))
    output, error = await merge_copy(_listener(), selected, str(root / f"three-english-episodes-{episode_titles}.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert not error
    info = _probe(output, "-show_streams", "-show_packets", "-show_chapters")
    tracks = [s for s in info["streams"] if s["codec_type"] == "subtitle"]
    assert len(tracks) == 1
    assert tracks[0]["codec_name"] == "ass"
    assert tracks[0]["tags"]["language"] == "eng"
    assert len(info["chapters"]) == 3
    events = [p for p in info["packets"] if p["stream_index"] == tracks[0]["index"]]
    assert [float(p["pts_time"]) for p in events] == pytest.approx(
        _expected_embedded_times(selected, info["chapters"]), abs=0.006)


def test_ass_case_insensitive_style_references_join_correctly():
    text = _ass("Dialogue", 22, "&H00FFFFFF").replace(".80,Default", ".80,default")
    text = text.replace(",,Dialogue", r",,{\rDEFAULT}Dialogue")
    joined = join_documents([read_document(text, "ass")])
    assert "Part1_Default" in joined
    assert r"{\rPart1_Default}Dialogue" in joined
    assert "PlayResX: 640" in joined
    assert "PlayResY: 360" in joined


@pytest.mark.asyncio
@pytest.mark.parametrize("forced_signs", [False, True])
async def test_default_dialogue_track_is_continuous_when_signs_order_changes(media, forced_signs):
    root, files = media
    selected = []
    for index, source in enumerate(files[:2]):
        target = root / f"signs-dialogue-{forced_signs}-{index}.mkv"
        signs = root / f"signs-{index}.ass"
        signs.write_text(_ass(f"Signs {index}", 22, "&H00FFFFFF"), encoding="utf-8")
        dialogue_index = 1 - index
        signs_index = index
        subtitle_maps = ("1:s", "0:s") if index == 0 else ("0:s", "1:s")
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-i", str(signs),
             "-map", "0:v", "-map", "0:a", "-map", subtitle_maps[0], "-map", subtitle_maps[1], "-c", "copy",
             "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=eng",
             f"-metadata:s:s:{signs_index}", "title=Signs",
             f"-metadata:s:s:{dialogue_index}", "title=English Dialogue",
             f"-disposition:s:{signs_index}", "forced" if forced_signs else "0",
             f"-disposition:s:{dialogue_index}", "default", str(target))
        selected.append(str(target))
    output, error = await merge_copy(_listener(), selected, str(root / f"default-dialogue-{forced_signs}.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert not error
    info = _probe(output, "-show_streams", "-show_packets")
    tracks = [s for s in info["streams"] if s["codec_type"] == "subtitle"]
    assert len(tracks) == 2
    default = [s for s in tracks if s["disposition"]["default"]]
    assert len(default) == 1
    assert not default[0]["disposition"]["forced"]
    assert default[0]["tags"]["title"] == "English Dialogue"
    assert len([p for p in info["packets"] if p["stream_index"] == default[0]["index"]]) == 2
    text = subprocess.check_output(["ffmpeg", "-v", "error", "-i", output,
                                   "-map", f"0:{default[0]['index']}", "-c:s", "copy", "-f", "ass", "pipe:1"])
    assert [event["Text"] for event in read_document(text.decode("utf-8"), "ass")["events"]] == ["First", "Second"]


def test_video_span_excludes_nonzero_start_from_absolute_end_tags():
    probe = {"streams": [{"codec_type": "video", "start_time": "10", "tags": {"DURATION": "00:00:12.000"}}]}
    assert _video_span(probe) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", ["0.12", "0.25", "0.8", "5"])
async def test_copy_merge_accepts_valid_initial_timestamp_offset(media, offset):
    root, files = media
    shifted = root / f"initial-offset-{offset}.mkv"
    _run("ffmpeg", "-v", "error", "-y", "-copyts", "-itsoffset", offset, "-i", str(files[0]),
         "-map", "0", "-c", "copy", str(shifted))
    selected = [str(shifted), str(files[1])]
    hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    output, error = await merge_copy(_listener(), selected, str(root / f"offset-merged-{offset}.mkv"),
                                    [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets")
    assert float(info["chapters"][0]["start_time"]) > 0.05
    assert len(info["chapters"]) == 2
    subtitle = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(subtitle) == 1
    events = [packet for packet in info["packets"] if packet["stream_index"] == subtitle[0]["index"]]
    assert [float(packet["pts_time"]) for packet in events] == pytest.approx(
        _expected_embedded_times(selected, info["chapters"]), abs=0.006)
    frames = _probe(output, "-count_frames", "-select_streams", "v:0", "-show_streams")
    assert int(frames["streams"][0]["nb_read_frames"]) == 72
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a", "-f", "null", "-")
    assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]


@pytest.mark.asyncio
@pytest.mark.parametrize("case,offset", [
    ("short-audio", "0"), ("short-video", "0"), ("dual-audio", "0"),
    ("sparse-audio", "0"), ("dual-audio", "4300"),
])
async def test_playback_checks_handle_uneven_track_ends_and_gaps(media, case, offset):
    root, _ = media
    selected = []
    for index in range(3):
        duration = 4 if index == 2 else 2
        video_duration = 2 if case == "short-video" and index == 2 else duration
        audio_duration = 2 if case in {"short-audio", "dual-audio"} and index == 2 else duration
        if case == "sparse-audio":
            video_duration, audio_duration = 6 if index == 1 else 4, 1
        target = root / f"uneven-{case}-{offset}-{index}.mkv"
        subtitle = root / f"uneven-{case}-{offset}-{index}.ass"
        subtitle.write_text(_ass(f"Episode {index}", 22, "&H00FFFFFF"), encoding="utf-8")
        command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                   f"testsrc2=s=160x90:r=24:d={video_duration}", "-f", "lavfi", "-i",
                   f"sine=frequency=440:sample_rate=48000:duration={audio_duration}"]
        if case == "dual-audio":
            command += ["-f", "lavfi", "-i", f"sine=frequency=880:sample_rate=48000:duration={duration}"]
        command += ["-i", str(subtitle), "-map", "0:v", "-map", "1:a"]
        if case == "dual-audio":
            command += ["-map", "2:a"]
        command += ["-map", "3:s" if case == "dual-audio" else "2:s", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "copy"]
        if index == 0:
            command += ["-output_ts_offset", offset]
        _run(*command, str(target))
        selected.append(str(target))
    probes = [_probe(path, "-show_streams", "-show_format") for path in selected]
    hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    output, error = await merge_copy(_listener(), selected, str(root / f"uneven-{case}-{offset}-merged.mkv"), probes)
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets", "-show_data_hash", "sha256")
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(audio) == (2 if case == "dual-audio" else 1)
    assert len(subtitles) == 1
    assert len(info["chapters"]) == 3
    assert [float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] == subtitles[0]["index"]] == pytest.approx(
        _expected_embedded_times(selected, info["chapters"]), abs=0.006)
    for position, stream in enumerate(audio):
        expected = []
        for source in selected:
            original = _probe(source, "-select_streams", f"a:{position}", "-show_packets", "-show_data_hash", "sha256")
            expected.extend(packet["data_hash"] for packet in original["packets"])
        assert [packet["data_hash"] for packet in info["packets"] if packet["stream_index"] == stream["index"]] == expected
    frames = _probe(output, "-count_frames", "-select_streams", "v:0", "-show_streams")
    assert int(frames["streams"][0]["nb_read_frames"]) == (144 if case == "short-video" else 336 if case == "sparse-audio" else 192)
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a", "-f", "null", "-")
    assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["decoder-error", "empty"])
async def test_secondary_audio_playback_failure_blocks_publication(media, monkeypatch, failure):
    from bot.helper.ext_utils import merge_media as backend

    root, files = media
    selected = []
    for index, source in enumerate(files[:2]):
        target = root / f"secondary-failure-{failure}-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v", "-map", "0:a",
             "-map", "0:a", "-map", "0:s", "-c", "copy", str(target))
        selected.append(str(target))
    hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    original_run = backend._run

    async def fail_secondary_audio(arguments, listener, **kwargs):
        if "-ss" in arguments and "0:2" in arguments and "framemd5" in arguments:
            return (1, "Injected secondary audio decoder error") if failure == "decoder-error" else (0, "")
        return await original_run(arguments, listener, **kwargs)

    monkeypatch.setattr(backend, "_run", fail_secondary_audio)
    target = root / f"secondary-failure-{failure}-merged.mkv"
    output, error = await merge_copy(_listener(), selected, str(target),
                                    [_probe(path, "-show_streams", "-show_format") for path in selected])
    assert output is False
    assert "could not decode audio track 3 near" in error
    assert ("Injected secondary audio decoder error" if failure == "decoder-error" else "No frames were decoded") in error
    assert not target.exists()
    assert not list(root.glob("merge-*/"))
    assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["negative", "duplicate", "reversed", "outside"])
async def test_invalid_episode_boundaries_fail_early_with_actual_times(media, monkeypatch, invalid):
    from bot.helper.ext_utils import merge_media as backend
    root, files = media
    original = backend._json_command
    hashes = [hashlib.sha256(path.read_bytes()).digest() for path in files[:2]]

    async def inspect(arguments, listener):
        info = await original(arguments, listener)
        if Path(str(arguments[-1])).name == "timeline.mkv":
            chapters = info["chapters"]
            if invalid == "negative":
                chapters[0]["start_time"] = "-0.125"
            elif invalid == "duplicate":
                chapters[1]["start_time"] = chapters[0]["start_time"]
            elif invalid == "reversed":
                chapters[0]["start_time"] = "0.250"
                chapters[1]["start_time"] = "0.125"
            else:
                chapters[1]["start_time"] = str(float(info["format"]["duration"]) + 1)
        return info

    monkeypatch.setattr(backend, "_json_command", inspect)
    target = root / f"invalid-boundaries-{invalid}.mkv"
    output, error = await merge_copy(_listener(), list(map(str, files[:2])), str(target),
                                    [_probe(path, "-show_streams", "-show_format") for path in files[:2]])
    assert output is False
    assert {"negative": "-0.125s", "duplicate": "previous boundary", "reversed": "0.250s", "outside": "timeline ending"}[invalid] in error
    assert not target.exists()
    assert not list(root.glob("merge-*/"))
    assert hashes == [hashlib.sha256(path.read_bytes()).digest() for path in files[:2]]


@pytest.mark.asyncio
async def test_real_merge_failure_removes_temporary_files_and_preserves_sources(media, monkeypatch):
    from bot.helper.ext_utils import merge_media as backend
    root, files = media
    original = backend._run
    hashes = [hashlib.sha256(path.read_bytes()).digest() for path in files[:2]]

    async def fail_append(arguments, listener, **kwargs):
        if "--generate-chapters" in arguments or "concat" in arguments:
            return 2, "Injected append failure"
        return await original(arguments, listener, **kwargs)

    monkeypatch.setattr(backend, "_run", fail_append)
    target = root / "failed-mux.mkv"
    output, error = await merge_copy(_listener(), list(map(str, files[:2])), str(target),
        [_probe(path, "-show_streams", "-show_format") for path in files[:2]])
    assert output is False
    assert "Injected append failure" in error
    assert not target.exists()
    assert not list(root.glob("merge-*/"))
    assert hashes == [hashlib.sha256(path.read_bytes()).digest() for path in files[:2]]


@pytest.mark.asyncio
async def test_twenty_part_merge_decodes_all_frames_and_subtitles(media):
    root, files = media
    source = str(files[0])
    probe = _probe(source, "-show_streams", "-show_format")
    output, error = await merge_copy(_listener(), [source] * 20, str(root / "twenty-parts.mkv"), [probe] * 20)
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets")
    assert len(info["chapters"]) == 20
    subtitles = [s for s in info["streams"] if s["codec_type"] == "subtitle"]
    assert len(subtitles) == 1
    assert len([p for p in info["packets"] if p["stream_index"] == subtitles[0]["index"]]) == 20
    frames = _probe(output, "-count_frames", "-select_streams", "v:0", "-show_streams")
    assert int(frames["streams"][0]["nb_read_frames"]) == 36 * 20
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a", "-f", "null", "-")


@pytest.mark.asyncio
async def test_encode_preserves_delayed_audio_and_subtitle_origin(media):
    root, files = media
    delayed = root / "delayed-audio.mkv"
    _run("ffmpeg", "-v", "error", "-y", "-i", str(files[0]), "-itsoffset", "0.4", "-i", str(files[0]),
         "-map", "0:v", "-map", "1:a", "-map", "0:s", "-c", "copy", str(delayed))
    selected = [str(delayed), str(delayed)]
    output, error = await merge_encode(_listener(), selected, str(root / "delayed-encoded.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
        {"video_codec": "libx264", "audio_codec": "aac", "video_params": {"preset": "ultrafast"}})
    assert not error
    samples = subprocess.check_output(["ffmpeg", "-v", "error", "-i", output,
        "-t", "0.2", "-map", "0:a:0", "-f", "f32le", "pipe:1"])
    values = struct.unpack(f"<{len(samples) // 4}f", samples)
    assert max(map(abs, values)) < 0.002
    events = _probe(output, "-show_streams", "-show_packets")
    subtitle = next(s["index"] for s in events["streams"] if s["codec_type"] == "subtitle")
    assert [float(p["pts_time"]) for p in events["packets"] if p["stream_index"] == subtitle] == pytest.approx([0.2, 1.7], abs=0.04)


@pytest.mark.asyncio
async def test_encode_retains_dual_audio_languages_titles_and_defaults(media):
    root, files = media
    selected = []
    for index, source in enumerate(files[:2]):
        target = root / f"dual-{index}.mkv"
        _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v", "-map", "0:a", "-map", "0:a", "-map", "0:s", "-c", "copy",
             "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=English",
             "-metadata:s:a:1", "language=jpn", "-metadata:s:a:1", "title=Japanese",
             "-disposition:a:0", "default", "-disposition:a:1", "0", str(target))
        selected.append(str(target))
    output, error = await merge_encode(_listener(), selected, str(root / "dual-encoded.mkv"),
        [_probe(path, "-show_streams", "-show_format") for path in selected],
        {"video_codec": "libx264", "audio_codec": "aac", "video_params": {"preset": "ultrafast"}})
    assert not error
    audio = [s for s in _probe(output, "-show_streams")["streams"] if s["codec_type"] == "audio"]
    assert [(s["tags"]["language"], s["tags"]["title"], s["disposition"]["default"]) for s in audio] == [
        ("eng", "English", 1), ("jpn", "Japanese", 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("codec", ["hevc", "h264"])
@pytest.mark.parametrize("corrupt_verification", [False, True])
async def test_video_header_changes_preserve_dual_audio_and_multiple_subtitles(media, monkeypatch, codec, corrupt_verification):
    from bot.helper.ext_utils import merge_media as backend
    from tests.test_encoding_playback_safety import _load_media_helpers

    root, _ = media
    selected = []
    for index in range(3):
        subtitles = []
        for lane, label in enumerate(("English", "French", "Signs")):
            subtitle = root / f"{codec}-{index}-{lane}.ass"
            subtitle.write_text(_ass(f"{label} {index}", 22 + index, "&H00FFFFFF"), encoding="utf-8")
            subtitles.append(subtitle)
        target = root / f"{codec}-multitrack-{index}.mkv"
        video_options = ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-preset", "ultrafast",
                         "-x265-params", f"pools=1:frame-threads=1:log-level=error:repeat-headers=0:strong-intra-smoothing={int(index != 2)}"]
        if codec == "h264":
            video_options = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                             "-x264-params", f"repeat-headers=0:ref={1 if index != 2 else 2}:bframes=0:keyint=24"]
        _run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=1.5",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
             "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1.5",
             "-i", str(subtitles[0]), "-i", str(subtitles[1]), "-i", str(subtitles[2]),
             "-map", "0:v", "-map", "3:s", "-map", "1:a", "-map", "4:s", "-map", "2:a", "-map", "5:s",
             *video_options,
             "-c:a", "aac", "-c:s", "copy", "-metadata:s:a:0", "language=jpn",
             "-metadata:s:a:0", "title=Japanese", "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English",
             "-disposition:a:0", "default" if codec == "hevc" else "0", "-disposition:a:1", "0",
             "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English",
             "-metadata:s:s:1", "language=fra", "-metadata:s:s:1", "title=French",
             "-metadata:s:s:2", "language=eng", "-metadata:s:s:2", "title=Signs",
             "-disposition:s:0", "default", "-disposition:s:1", "0", "-disposition:s:2", "forced",
             "-output_ts_offset", ("0.12", "0.25", "0.8")[index], str(target))
        selected.append(str(target))
    probes = [_probe(path, "-show_streams", "-show_format", "-show_data_hash", "sha256") for path in selected]
    videos = [next(stream for stream in probe["streams"] if stream["codec_type"] == "video") for probe in probes]
    assert videos[0]["extradata_hash"] == videos[1]["extradata_hash"]
    assert videos[2]["extradata_hash"] != videos[0]["extradata_hash"]
    _, _, _, check = _load_media_helpers("_probe_duration", "_merge_stream_signature", "_merge_mismatch_reason", "check_merge_compatibility")

    async def probe(path):
        return probes[selected.index(path)], ""

    check.__globals__["_probe_media_file"] = probe
    compatible, error = await check(selected, av_only=True)
    assert compatible is not None, error
    hashes = [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    frame_reader = backend._video_frames
    verified_paths = []

    async def verify_frames(path, indexes, listener):
        verified_paths.append(path)
        frames = await frame_reader(path, indexes, listener)
        if corrupt_verification and path not in selected:
            frames[0][0] = (frames[0][0][0], "injected frame mismatch")
        return frames

    monkeypatch.setattr(backend, "_video_frames", verify_frames)
    target = root / f"{codec}-multitrack-merged-{corrupt_verification}.mkv"
    output, error = await merge_copy(_listener(), selected, str(target), probes)
    assert verified_paths[:3] == selected
    assert len(verified_paths) == 4
    if corrupt_verification:
        assert output is False
        assert "every source frame" in error
        assert not target.exists()
        assert not list(root.glob("merge-*/"))
        assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
        return
    assert not error
    info = _probe(output, "-show_streams", "-show_packets", "-show_chapters", "-show_data_hash", "sha256")
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(audio) == 2 and len(subtitles) == 3
    assert [(stream["tags"]["language"], stream["tags"]["title"], stream["disposition"]["default"]) for stream in audio] == [
        ("jpn", "Japanese", int(codec == "hevc")), ("eng", "English", 0)]
    assert sum(stream["disposition"]["default"] for stream in subtitles) == 1
    assert sum(stream["disposition"]["forced"] for stream in subtitles) == 1
    assert len(info["chapters"]) == 3
    subtitle_indexes = {stream["index"] for stream in subtitles}
    assert sorted(float(packet["pts_time"]) for packet in info["packets"]
                  if packet["stream_index"] in subtitle_indexes) == pytest.approx(
        _expected_embedded_times(selected, info["chapters"]), abs=0.006)
    for stream in subtitles:
        assert len([packet for packet in info["packets"] if packet["stream_index"] == stream["index"]]) == 3
    for position, stream in enumerate(audio):
        expected = []
        for source in selected:
            original = _probe(source, "-select_streams", f"a:{position}", "-show_packets", "-show_data_hash", "sha256")
            expected.extend(packet["data_hash"] for packet in original["packets"])
        assert [packet["data_hash"] for packet in info["packets"] if packet["stream_index"] == stream["index"]] == expected
    assert hashes == [hashlib.sha256(Path(path).read_bytes()).digest() for path in selected]
    _run("ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0:v", "-map", "0:a", "-f", "null", "-")


@pytest.mark.asyncio
async def test_task_cancellation_terminates_child_and_returns_clear_error(media, monkeypatch):
    from bot.helper.ext_utils import merge_media as backend
    root, files = media
    running = asyncio.Event()
    original = backend._run

    async def slow_run(arguments, listener, **kwargs):
        if "-J" in arguments:
            running.set()
            return await original([sys.executable, "-c", "import time; time.sleep(30)"], listener)
        return await original(arguments, listener, **kwargs)

    monkeypatch.setattr(backend, "_run", slow_run)
    listener = _listener()
    target = root / "task-cancelled.mkv"
    task = asyncio.create_task(merge_copy(listener, list(map(str, files[:2])), str(target),
        [_probe(path, "-show_streams", "-show_format") for path in files[:2]]))
    await running.wait()
    while listener.subproc is None:
        await asyncio.sleep(0.01)
    child = listener.subproc
    task.cancel()
    output, error = await task
    assert output is False
    assert "cancelled" in error.lower()
    assert listener.is_cancelled
    assert child.returncode is not None
    assert listener.subproc is None
    assert not target.exists()
