"""Reproducible tiny media fixtures for the real MKVToolNix copy backend."""

import json
import shutil
import struct
import subprocess
from types import SimpleNamespace

import pytest

from bot.helper.ext_utils.merge_media import (
    _check_selected_streams,
    _font_names,
    _mkvmerge_binary,
    associate_sidecars,
    merge_copy,
    merge_encode,
    validate_merge_encode_profile,
)


def _run(*args):
    subprocess.run(args, check=True, capture_output=True)


def _probe(path, *fields):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", *fields, "-of", "json", str(path)
    ]))


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


def _listener():
    return SimpleNamespace(is_cancelled=False, subproc=None)


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


@pytest.mark.asyncio
async def test_ass_ass_srt_remain_original_tracks_with_chapters(media):
    root, files = media
    probes = [_probe(path, "-show_streams", "-show_format") for path in files]
    output, error = await merge_copy(
        _listener(), list(map(str, files)), str(root / "merged.mkv"), probes
    )
    assert not error
    info = _probe(output, "-show_streams", "-show_chapters", "-show_packets", "-show_data_hash", "sha256")
    assert [stream["codec_name"] for stream in info["streams"] if stream["codec_type"] == "subtitle"] == [
        "ass", "ass", "subrip"
    ]
    assert len(info["chapters"]) == 3
    assert [chapter["tags"]["title"] for chapter in info["chapters"]] == ["1", "2", "3"]
    assert [float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] in {2, 3, 4}] == pytest.approx(
        [0.2, 1.7, 3.2], abs=0.08
    )
    assert probes[0]["streams"][2]["codec_name"] == "ass"


def test_font_name_parser_detects_internal_identity():
    assert ("family-style", "example", "regular") in _font_names(_font_bytes())
    assert ("postscript", "example-regular") in _font_names(_font_bytes())


def test_continuous_profile_rejects_settings_it_cannot_honor():
    assert "keyframe interval" in validate_merge_encode_profile({
        "video_codec": "libx264", "audio_codec": "aac",
        "video_params": {"keyint_seconds": 4},
    })
    assert "burn-in" in validate_merge_encode_profile({
        "video_codec": "libx264", "audio_codec": "aac",
        "subtitle_mode": "burn", "video_params": {},
    })


def test_unhandled_data_or_cover_art_is_an_explicit_error():
    with pytest.raises(ValueError, match="data stream"):
        _check_selected_streams([{"streams": [{"codec_type": "data"}]}])
    with pytest.raises(ValueError, match="cover art"):
        _check_selected_streams([{"streams": [{"codec_type": "video", "disposition": {"attached_pic": 1}}]}])


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
    info = _probe(output, "-show_streams", "-show_packets")
    subtitles = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert [stream["codec_name"] for stream in subtitles] == ["ass", "subrip"]
    starts = [float(packet["pts_time"]) for packet in info["packets"] if packet["stream_index"] in {stream["index"] for stream in subtitles}]
    assert starts == pytest.approx([0.2, 3.2], abs=0.08)


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
    assert [stream["codec_name"] for stream in info["streams"] if stream["codec_type"] == "subtitle"] == ["ass", "ass", "subrip"]
    assert len(info["chapters"]) == 3
