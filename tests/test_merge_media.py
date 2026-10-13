"""Reproducible tiny media fixtures for the real MKVToolNix copy backend."""

import asyncio
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

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
from bot.helper.ext_utils.merge_subtitles import join_documents, read_document


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
        [0.2, 1.7, 3.2], abs=0.08
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
    info = _probe(output, "-show_streams", "-show_packets")
    tracks = [stream for stream in info["streams"] if stream["codec_type"] == "subtitle"]
    assert len(tracks) == 2
    assert {stream["tags"]["language"] for stream in tracks} == {"eng", "jpn"}
    for stream in tracks:
        events = [packet for packet in info["packets"] if packet["stream_index"] == stream["index"]]
        assert [float(packet["pts_time"]) for packet in events] == pytest.approx([0.2, 3.2], abs=0.08)
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
    assert [float(p["pts_time"]) for p in events] == pytest.approx([0.2, 1.7, 3.2], abs=0.08)


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
async def test_real_merge_failure_removes_temporary_files_and_preserves_sources(media, monkeypatch):
    from bot.helper.ext_utils import merge_media as backend
    root, files = media
    original = backend._run
    hashes = [hashlib.sha256(path.read_bytes()).digest() for path in files[:2]]

    async def fail_append(arguments, listener, **kwargs):
        if "--generate-chapters" in arguments:
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
