import ast
import os.path as ospath
import re
from contextlib import suppress
from fractions import Fraction
from math import isfinite
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA_UTILS_PATH = ROOT / "bot" / "helper" / "ext_utils" / "media_utils.py"


def _load_media_helpers(*names):
    tree = ast.parse(MEDIA_UTILS_PATH.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)

    def time_to_seconds(value):
        hours, minutes, seconds = str(value).split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    namespace = {
        "_MATROSKA_EXTENSIONS": {".mkv", ".mka"},
        "_MP4_EXTENSIONS": {".mp4", ".m4v", ".mov"},
        "_MP4_VIDEO_CODECS": {"copy", "libx264", "libx265"},
        "_MP4_AUDIO_CODECS": {"copy", "aac", "ac3", "eac3", "libmp3lame"},
        "_SUPPORTED_VIDEO_CODECS": {
            "copy", "libsvtav1", "libx264", "libx265", "libvpx-vp9", "mpeg4"
        },
        "_SUPPORTED_AUDIO_CODECS": {
            "copy", "aac", "ac3", "eac3", "flac", "libmp3lame", "libopus"
        },
        "_X26X_PRESETS": {
            "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
            "slow", "slower", "veryslow"
        },
        "_PIXEL_FORMATS": {
            "libsvtav1": {"yuv420p", "yuv420p10le"},
            "libx264": {"yuv420p", "yuv420p10le", "yuv422p", "yuv444p"},
            "libx265": {"yuv420p", "yuv420p10le", "yuv422p", "yuv444p"},
            "libvpx-vp9": {"yuv420p", "yuv420p10le", "yuv422p", "yuv444p"},
            "mpeg4": {"yuv420p"},
        },
        "isfinite": isfinite,
        "Fraction": Fraction,
        "re": re,
        "suppress": suppress,
        "ospath": ospath,
        "time_to_seconds": time_to_seconds,
    }
    exec(compile(module, str(MEDIA_UTILS_PATH), "exec"), namespace)
    return tuple(namespace[name] for name in names)


def _literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} was not found in {path}")


def _load_ffmpeg_method(name, namespace):
    tree = ast.parse(MEDIA_UTILS_PATH.read_text(encoding="utf-8"))
    ffmpeg_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FFMpeg"
    )
    method = next(
        node
        for node in ffmpeg_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(MEDIA_UTILS_PATH), "exec"), namespace)
    return namespace[name]


def test_encode_container_is_selected_for_codec_compatibility():
    (get_output_path,) = _load_media_helpers("get_encode_output_path")

    assert get_output_path("movie.mp4", "libx264", "aac") == "movie_encoded.mp4"
    assert get_output_path("movie.mp4", "libx265", "aac") == "movie_encoded.mp4"
    assert get_output_path("movie.mp4", "libsvtav1", "libopus") == "movie_encoded.mkv"
    assert get_output_path("movie.mp4", "libx264", "flac") == "movie_encoded.mkv"
    assert get_output_path("movie.avi", "libx264", "aac") == "movie_encoded.mkv"
    assert get_output_path("movie.mkv", "libsvtav1", "libopus") == "movie_encoded.mkv"


def test_copied_audio_matroska_uses_seek_safe_automatic_timestamps():
    (timestamp_policy,) = _load_media_helpers("_encode_timestamp_policy")

    copy_vfr = timestamp_policy("episode.mkv", "copy", "vfr")
    assert copy_vfr == {
        "automatic_timestamps": True,
        "generate_pts": False,
        "fps_mode": None,
        "shift_negative_ts": False,
    }

    copy_auto = timestamp_policy("episode.mka", "copy", "auto")
    assert copy_auto["automatic_timestamps"] is True
    assert copy_auto["fps_mode"] is None


def test_explicit_cfr_and_noncopy_audio_keep_requested_timestamp_controls():
    (timestamp_policy,) = _load_media_helpers("_encode_timestamp_policy")

    copy_cfr = timestamp_policy("episode.mkv", "copy", "cfr")
    assert copy_cfr["automatic_timestamps"] is True
    assert copy_cfr["generate_pts"] is False
    assert copy_cfr["fps_mode"] == "cfr"
    assert copy_cfr["shift_negative_ts"] is False

    encoded_audio = timestamp_policy("episode.mkv", "aac", "vfr")
    assert encoded_audio == {
        "automatic_timestamps": False,
        "generate_pts": True,
        "fps_mode": "vfr",
        "shift_negative_ts": True,
    }

    copied_mp4 = timestamp_policy("episode.mp4", "copy", "vfr")
    assert copied_mp4["automatic_timestamps"] is False
    assert copied_mp4["generate_pts"] is True
    assert copied_mp4["fps_mode"] == "vfr"
    assert copied_mp4["shift_negative_ts"] is True


def test_subtitle_filter_path_is_safe_for_ffmpeg_filter_syntax():
    (filter_path,) = _load_media_helpers("_subtitle_filter_path")

    assert filter_path(r"C:\Media Files\show's episode.mkv") == (
        r"C\:/Media Files/show\'s episode.mkv"
    )


def test_existing_av1_profile_is_preserved_and_compiled_efficiently():
    bounded_int, as_bool, parse_params, normalize, build_svt = _load_media_helpers(
        "_bounded_int",
        "_as_bool",
        "_parse_codec_params",
        "normalize_encode_profile",
        "_build_svtav1_params",
    )
    del bounded_int, as_bool, parse_params
    legacy = {
        "name": "Existing AV1 Anime",
        "video_codec": "libsvtav1",
        "audio_codec": "libopus",
        "subtitle_mode": "copy",
        "video_params": {
            "crf": 34,
            "preset": 6,
            "pix_fmt": "yuv420p10le",
            "profile": "0",
            "level": "5.1",
            "extra_params": (
                "tune=0:film-grain=4:film-grain-denoise=0:"
                "enable-overlays=1:scm=2:keyint=240:irefresh-type=2"
            ),
        },
        "audio_params": {"bitrate": "128k", "channels": 2, "vbr": True},
        "metadata": {"a_track": "1,0", "s_track": "1,2"},
        "rename": "{title} - {episode}.mkv",
    }

    profile, warnings = normalize(legacy)
    params = build_svt(profile["video_params"], worker_count=4, frame_rate=24)

    assert warnings == []
    assert profile["name"] == legacy["name"]
    assert profile["metadata"] == legacy["metadata"]
    assert profile["rename"] == legacy["rename"]
    assert profile["video_params"]["crf"] == 34
    assert profile["video_params"]["preset"] == 6
    assert profile["audio_params"]["vbr"] is True
    assert "film-grain=4" in params
    assert "keyint=240" in params
    assert "lp=4" in params
    assert "fast-decode=0" in params
    assert "preset=" not in params
    assert "crf=" not in params


def test_copied_audio_av1_uses_pre_upgrade_svt_parameter_semantics():
    _, _, _, normalize, build_svt = _load_media_helpers(
        "_bounded_int",
        "_as_bool",
        "_parse_codec_params",
        "normalize_encode_profile",
        "_build_svtav1_params",
    )
    profile, warnings = normalize(
        {
            "video_codec": "libsvtav1",
            "audio_codec": "copy",
            "video_params": {
                "crf": 26,
                "preset": 5,
                "fast_decode": False,
                "keyint_seconds": 10,
                "profile": "0",
                "level": "5.1",
                "extra_params": (
                    "tune=0:film-grain=0:enable-overlays=1:scm=2:"
                    "irefresh-type=2"
                ),
            },
        }
    )
    params = build_svt(
        profile["video_params"],
        worker_count=4,
        frame_rate=24,
        compatibility_mode=True,
    )

    assert warnings == []
    assert "keyint=240" in params
    assert "profile=0" in params
    assert "level=51" in params
    assert "lp=" not in params
    assert "fast-decode=" not in params

    profile_without_decoder_override, _ = normalize(
        {
            "video_codec": "libsvtav1",
            "audio_codec": "copy",
            "video_params": {"extra_params": "tune=0"},
        }
    )
    params_without_override = build_svt(
        profile_without_decoder_override["video_params"],
        worker_count=4,
        frame_rate=24,
        compatibility_mode=True,
    )
    assert "fast-decode=" not in params_without_override
    assert "keyint=" not in params_without_override


def test_minimal_av1_profile_gets_balanced_defaults_without_overriding_legacy_params():
    _, _, _, normalize, build_svt = _load_media_helpers(
        "_bounded_int",
        "_as_bool",
        "_parse_codec_params",
        "normalize_encode_profile",
        "_build_svtav1_params",
    )
    profile, warnings = normalize(
        {
            "video_codec": "libsvtav1",
            "audio_codec": "libopus",
            "video_params": {"extra_params": "lp=99:keyint=120:fast-decode=0"},
        }
    )
    params = build_svt(profile["video_params"], worker_count=4, frame_rate=60)

    assert warnings == []
    assert profile["video_params"]["preset"] == 6
    assert profile["video_params"]["crf"] == 30
    assert profile["video_params"]["pix_fmt"] == "yuv420p10le"
    assert "lp=4" in params
    assert "keyint=120" in params
    assert "fast-decode=0" in params


def test_legacy_av1_level_and_named_codec_params_are_normalized_without_loss():
    _, _, _, normalize, build_svt = _load_media_helpers(
        "_bounded_int",
        "_as_bool",
        "_parse_codec_params",
        "normalize_encode_profile",
        "_build_svtav1_params",
    )
    profile, warnings = normalize(
        {
            "video_codec": "libsvtav1",
            "audio_codec": "libopus",
            "video_params": {
                "extra_params": "preset=7:crf=32:profile=0:level=51:tune=1"
            },
        }
    )
    params = build_svt(profile["video_params"], worker_count=8, frame_rate=30)

    assert warnings == []
    assert profile["video_params"]["preset"] == 7
    assert profile["video_params"]["crf"] == 32
    assert profile["video_params"]["profile"] == 0
    assert profile["video_params"]["level"] == "5.1"
    assert "profile=0" in params
    assert "level=51" in params
    assert "tune=1" in params
    assert "keyint=300" in params


def test_invalid_legacy_av1_controls_and_audio_bitrate_fall_back_safely():
    _, _, _, normalize, build_svt = _load_media_helpers(
        "_bounded_int",
        "_as_bool",
        "_parse_codec_params",
        "normalize_encode_profile",
        "_build_svtav1_params",
    )
    profile, warnings = normalize(
        {
            "video_codec": "libsvtav1",
            "audio_codec": "libopus",
            "video_params": {
                "extra_params": "lp=0:keyint=broken:fast-decode=broken:tune=1"
            },
            "audio_params": {"bitrate": "0k"},
        }
    )
    params = build_svt(profile["video_params"], worker_count=4, frame_rate=30)

    assert profile["audio_params"]["bitrate"] == "128k"
    assert any("invalid audio bitrate" in item for item in warnings)
    assert "lp=1" in params
    assert "keyint=300" in params
    assert "fast-decode=1" in params


def test_existing_hevc_profile_keeps_codec_specific_tuning():
    _, _, _, normalize = _load_media_helpers(
        "_bounded_int", "_as_bool", "_parse_codec_params", "normalize_encode_profile"
    )
    profile, warnings = normalize(
        {
            "name": "Anime Encode",
            "video_codec": "libx265",
            "audio_codec": "libopus",
            "video_params": {
                "crf": 20,
                "preset": "slow",
                "pix_fmt": "yuv420p10le",
                "profile": "main10",
                "extra_params": "tune=animation",
            },
            "audio_params": {"bitrate": "192k", "vbr": True},
        }
    )

    assert warnings == []
    assert profile["video_codec"] == "libx265"
    assert profile["video_params"]["preset"] == "slow"
    assert profile["video_params"]["extra_params"] == "tune=animation"
    assert profile["audio_params"]["vbr"] is True


def test_named_h264_and_hevc_profiles_get_compatible_pixel_formats():
    _, _, _, normalize = _load_media_helpers(
        "_bounded_int", "_as_bool", "_parse_codec_params", "normalize_encode_profile"
    )

    h264, h264_warnings = normalize(
        {
            "video_codec": "libx264",
            "video_params": {"profile": "high", "pix_fmt": "yuv444p"},
        }
    )
    hevc, hevc_warnings = normalize(
        {
            "video_codec": "libx265",
            "video_params": {"profile": "main", "pix_fmt": "yuv420p10le"},
        }
    )

    assert h264["video_params"]["pix_fmt"] == "yuv420p"
    assert hevc["video_params"]["pix_fmt"] == "yuv420p"
    assert any("H.264 high requires yuv420p" in item for item in h264_warnings)
    assert any("HEVC main requires yuv420p" in item for item in hevc_warnings)


def test_probe_duration_ignores_cover_art_and_nonfinite_values():
    probe_duration, count_streams = _load_media_helpers(
        "_probe_duration", "_count_media_streams"
    )
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "duration": "9999",
                "disposition": {"attached_pic": 1},
            },
            {"codec_type": "video", "duration": "120.25", "disposition": {}},
            {"codec_type": "audio", "duration": "120.20", "disposition": {}},
        ],
        "format": {"duration": "Infinity"},
    }

    assert probe_duration(probe) == 120.25
    assert count_streams(probe, "video") == 1
    assert count_streams(probe, "audio") == 1


def test_frame_count_uses_declared_frames_then_falls_back_to_frame_rate():
    probe_duration, parse_frame_rate, frame_count = _load_media_helpers(
        "_probe_duration", "_parse_frame_rate", "_probe_video_frame_count"
    )
    del probe_duration, parse_frame_rate
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "nb_frames": "240",
                "avg_frame_rate": "24/1",
                "disposition": {},
            }
        ],
        "format": {"duration": "10"},
    }

    assert frame_count(probe, 10) == 240
    probe["streams"][0]["nb_frames"] = "N/A"
    assert frame_count(probe, 10) == 240


async def test_validation_rejects_missing_audio_and_checks_seek_points():
    probe_duration, count_streams = _load_media_helpers(
        "_probe_duration", "_count_media_streams"
    )
    probes = {
        "source": {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "120"},
        },
        "output": {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "120.1"},
        },
    }

    async def probe_file(path):
        return probes[path], ""

    validate = _load_ffmpeg_method(
        "_validate_encoded_media",
        {
            "_probe_media_file": probe_file,
            "_probe_duration": probe_duration,
            "_count_media_streams": count_streams,
        },
    )

    class Validator:
        _listener = type("Listener", (), {"is_cancelled": False})()

        def __init__(self):
            self.samples = []

        async def _decode_encode_sample(self, path, position, stream_type):
            self.samples.append((path, position, stream_type))
            return True, ""

    validator = Validator()
    valid, reason = await validate(validator, "source", "output", True)

    assert valid is True
    assert reason == ""
    assert [sample[2] for sample in validator.samples].count("video") == 3
    assert [sample[2] for sample in validator.samples].count("audio") == 1

    probes["output"]["streams"] = [{"codec_type": "video"}]
    valid, reason = await validate(validator, "source", "output", True)
    assert valid is False
    assert "no audio stream" in reason


async def test_audio_decode_check_requires_a_real_decoded_frame():
    calls = []
    result = {
        "stdout": "\n".join(
            [
                "#format: frame checksums",
                "#stream#, dts, pts, duration, size, hash",
                "0, 0, 0, 1024, 4096, abc123",
            ]
        ),
        "stderr": "",
        "code": 0,
    }

    async def cmd_exec(cmd):
        calls.append(cmd)
        return result["stdout"], result["stderr"], result["code"]

    async def wait_for(awaitable, timeout):
        assert timeout == 60
        return await awaitable

    decode = _load_ffmpeg_method(
        "_decode_encode_sample",
        {
            "BinConfig": type("BinConfig", (), {"FFMPEG_NAME": "ffmpeg"}),
            "cmd_exec": cmd_exec,
            "wait_for": wait_for,
        },
    )

    valid, reason = await decode(object(), "encoded.mkv", 870.015, "audio")

    assert valid is True
    assert reason == ""
    assert "framehash" in calls[0]
    assert "pcm_s16le" in calls[0]
    assert calls[0][calls[0].index("-frames:a") + 1] == "1"

    result["stdout"] = "out_time_us=1000000\nprogress=end"
    valid, reason = await decode(object(), "encoded.mkv", 870.015, "audio")

    assert valid is False
    assert reason == "no audio data decoded near 870.015s"

    result["stderr"] = "invalid AAC packet"
    result["code"] = 1
    valid, reason = await decode(object(), "encoded.mkv", 870.015, "audio")

    assert valid is False
    assert reason == "audio decode check failed: invalid AAC packet"


async def test_audio_validation_retries_empty_midpoint_without_masking_decode_errors():
    probe_duration, count_streams = _load_media_helpers(
        "_probe_duration", "_count_media_streams"
    )
    probe = {
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
        "format": {"duration": "120"},
    }

    async def probe_file(path):
        return probe, ""

    validate = _load_ffmpeg_method(
        "_validate_encoded_media",
        {
            "_probe_media_file": probe_file,
            "_probe_duration": probe_duration,
            "_count_media_streams": count_streams,
        },
    )

    class Validator:
        _listener = type("Listener", (), {"is_cancelled": False})()

        def __init__(self, hard_error=False, always_empty=False):
            self.audio_positions = []
            self.hard_error = hard_error
            self.always_empty = always_empty

        async def _decode_encode_sample(self, path, position, stream_type):
            if stream_type == "video":
                return True, ""
            self.audio_positions.append(position)
            if self.hard_error:
                return False, "invalid audio packet"
            if self.always_empty or len(self.audio_positions) == 1:
                return False, f"no audio data decoded near {position:.3f}s"
            return True, ""

    validator = Validator()
    valid, reason = await validate(
        validator, "source", "output", True, source_probe=probe
    )

    assert valid is True
    assert reason == ""
    assert validator.audio_positions == [60.0, 30.0]

    validator = Validator(hard_error=True)
    valid, reason = await validate(
        validator, "source", "output", True, source_probe=probe
    )

    assert valid is False
    assert reason == "invalid audio packet"
    assert validator.audio_positions == [60.0]

    validator = Validator(always_empty=True)
    valid, reason = await validate(
        validator, "source", "output", True, source_probe=probe
    )

    assert valid is False
    assert "no audio frames decoded" in reason
    assert validator.audio_positions == [60.0, 30.0, 90.0]


async def test_empty_copied_audio_is_rebuilt_without_reencoding_video():
    commands = []
    replacements = []
    removals = []
    (timestamp_policy,) = _load_media_helpers("_encode_timestamp_policy")

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def create_subprocess_exec(*cmd, stdout, stderr):
        commands.append(list(cmd))
        return Process()

    async def wait_for(awaitable, timeout):
        assert timeout == 900
        return await awaitable

    async def replace(source, destination):
        replacements.append((source, destination))

    async def remove(path):
        removals.append(path)

    class Logger:
        @staticmethod
        def info(message):
            pass

        @staticmethod
        def warning(message):
            pass

    repair = _load_ffmpeg_method(
        "_repair_copied_audio",
        {
            "ospath": ospath,
            "cores": "0-3",
            "BinConfig": type("BinConfig", (), {"FFMPEG_NAME": "ffmpeg"}),
            "create_subprocess_exec": create_subprocess_exec,
            "PIPE": object(),
            "wait_for": wait_for,
            "suppress": suppress,
            "remove": remove,
            "replace": replace,
            "LOGGER": Logger,
            "_encode_timestamp_policy": timestamp_policy,
        },
    )

    class Repairer:
        _listener = type(
            "Listener", (), {"is_cancelled": False, "subproc": None}
        )()

        def __init__(self):
            self.validation_count = 0

        async def _validate_encoded_media(
            self, input_file, output_file, expect_audio, source_probe
        ):
            assert input_file == "source.mkv"
            assert output_file == "encoded.audio-repair.mkv"
            assert expect_audio is True
            assert source_probe == {"format": {"duration": "120"}}
            self.validation_count += 1
            if self.validation_count == 1:
                return False, "no audio frames decoded after stream copy"
            return True, ""

    valid, reason = await repair(
        Repairer(),
        "source.mkv",
        "encoded.mkv",
        "0",
        {"bitrate": "128k", "channels": 2},
        {"s:a:0": "title=Japanese"},
        {"a:0": "default"},
        {"format": {"duration": "120"}},
    )

    assert valid is True
    assert reason == ""
    assert len(commands) == 2
    copy_command, command = commands
    assert "-c:a" not in copy_command
    assert "-fflags" not in copy_command
    assert "-avoid_negative_ts" not in copy_command
    assert "0:v?" in command
    assert "1:a:0?" in command
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-fflags") + 1] == "+genpts"
    assert command[command.index("-avoid_negative_ts") + 1] == "make_zero"
    assert command[command.index("-af") + 1] == "aresample=async=1:first_pts=0"
    assert command[command.index("-b:a") + 1] == "128k"
    assert command[command.index("-ac") + 1] == "2"
    assert "-metadata:s:a:0" in command
    assert "-disposition:a:0" in command
    assert removals == ["encoded.audio-repair.mkv"]
    assert replacements == [("encoded.audio-repair.mkv", "encoded.mkv")]

    cancelled = Repairer()
    cancelled._listener = type(
        "Listener", (), {"is_cancelled": True, "subproc": None}
    )()
    command_count = len(commands)
    valid, reason = await repair(
        cancelled,
        "source.mkv",
        "encoded.mkv",
        "0",
        {},
        {},
        {},
        {"format": {"duration": "120"}},
    )

    assert valid is False
    assert reason == "audio repair was cancelled"
    assert len(commands) == command_count


def test_default_profiles_are_playback_compatible_and_consistent():
    sample = _literal_assignment(ROOT / "config_sample.py", "DEFAULT_ENCODE_PRESET")
    defaults_tree = ast.parse(
        (ROOT / "bot" / "modules" / "bot_settings.py").read_text(encoding="utf-8")
    )
    defaults_node = next(
        node.value
        for node in defaults_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_VALUES"
            for target in node.targets
        )
    )
    defaults = next(
        ast.literal_eval(value)
        for key, value in zip(defaults_node.keys, defaults_node.values, strict=True)
        if ast.literal_eval(key) == "DEFAULT_ENCODE_PRESET"
    )

    assert defaults == sample
    assert defaults["video_codec"] == "libx264"
    assert defaults["audio_codec"] == "aac"
    assert defaults["video_params"]["pix_fmt"] == "yuv420p"
    assert defaults["audio_params"]["vbr"] is False


def test_encode_pipeline_selects_copy_safe_timestamps_and_validates_before_success():
    source = MEDIA_UTILS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    ffmpeg_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FFMpeg"
    )
    encode_method = next(
        node
        for node in ffmpeg_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "encode_video"
    )
    method_source = ast.get_source_segment(source, encode_method)

    assert "_encode_timestamp_policy(" in method_source
    assert 'if timestamp_policy["generate_pts"]:' in method_source
    assert '"-fflags", "+genpts"' in method_source
    assert '"-y", "-nostdin"' in method_source
    assert '"-preset"' in method_source
    assert '"-crf"' in method_source
    assert "_build_svtav1_params(" in method_source
    assert '"-fps_mode:v:0"' in method_source
    assert 'timestamp_policy["fps_mode"]' in method_source
    assert "legacy_av1_copy" in method_source
    assert "compatibility_mode=legacy_av1_copy" in method_source
    assert 'svt_params = f"preset={preset}:crf={crf}:{svt_params}"' in method_source
    assert '"-avoid_negative_ts"' in method_source
    assert 'if timestamp_policy["shift_negative_ts"]:' in method_source
    assert '"-max_muxing_queue_size"' in method_source
    assert '"-cluster_time_limit", "5000"' in method_source
    assert '"-movflags", "+faststart"' in method_source
    assert 'sub_mode == "burn"' in method_source
    assert '"subtitles="' in method_source
    assert "await self._validate_encoded_media(" in method_source
    assert "await self._repair_copied_audio(" in method_source
    assert 'a_codec == "copy"' in method_source
    assert "encoded file has no audio stream" in method_source
    assert '"audio decode check failed:"' in method_source
    assert "source_probe" in method_source
    assert "if not valid:" in method_source
    assert "await remove(output_file)" in method_source

    repair_method = next(
        node
        for node in ffmpeg_class.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_repair_copied_audio"
    )
    repair_source = ast.get_source_segment(source, repair_method)
    assert "_encode_timestamp_policy(" in repair_source
    assert 'if timestamp_policy["generate_pts"]:' in repair_source
    assert 'if timestamp_policy["shift_negative_ts"]:' in repair_source

    common_source = (ROOT / "bot" / "helper" / "common.py").read_text(
        encoding="utf-8"
    )
    common_tree = ast.parse(common_source)
    common_class = next(
        node
        for node in common_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TaskConfig"
    )
    proceed_encode = next(
        node
        for node in common_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "proceed_encode"
    )
    proceed_source = ast.get_source_segment(common_source, proceed_encode)
    assert "await self.on_download_error(" in proceed_source
    assert "The original file was" in proceed_source
    assert "not uploaded as an encoded result" in proceed_source


def test_profile_entry_points_normalize_saved_data_and_default_label_is_dynamic():
    users_settings = (ROOT / "bot" / "modules" / "users_settings.py").read_text(
        encoding="utf-8"
    )
    web_server = (ROOT / "web" / "wserver.py").read_text(encoding="utf-8")
    task_listener = (
        ROOT / "bot" / "helper" / "listeners" / "task_listener.py"
    ).read_text(encoding="utf-8")
    encode_js = (ROOT / "web" / "static" / "js" / "encode.js").read_text(
        encoding="utf-8"
    )
    encode_html = (
        ROOT / "web" / "templates" / "encode_profiles.html"
    ).read_text(encoding="utf-8")

    assert "normalize_encode_profile(pdata)" in users_settings
    assert "normalize_encode_profile(data)" in web_server
    assert '"DEFAULT: SVT-AV1"' not in task_listener
    assert "VIDEO_PROFILE_OPTIONS" in encode_js
    assert "PIXEL_FORMAT_OPTIONS" in encode_js
    assert "throw await responseError" in encode_js
    assert "-fps_mode:v:0" in encode_js
    assert "useAutomaticTimestamps" in encode_js
    assert "svtParts.push(`preset=${profile.video_params.preset}`)" in encode_js
    assert "if (!useAutomaticTimestamps) cmd += `  -cluster_time_limit 5000 `" in encode_js
    assert '<option value="yuv420p" selected>' in encode_html
    assert ".profile-card { flex: 0 0 auto;" in encode_html
