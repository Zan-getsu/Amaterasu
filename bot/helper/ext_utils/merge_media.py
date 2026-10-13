"""Validated Matroska A/V append with continuous, original-format subtitles."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from collections import Counter
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path
from secrets import token_hex

from .merge_subtitles import join_documents, read_document


def _mkvmerge_binary():
    found = shutil.which("mkvmerge")
    if found:
        return found
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MKVToolNix" / "mkvmerge.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _mkvextract_binary(mkvmerge):
    sibling = Path(mkvmerge).with_name("mkvextract.exe" if os.name == "nt" else "mkvextract")
    return str(sibling) if sibling.is_file() else shutil.which("mkvextract")


def _font_names(data, *, offset=0):
    """Read only the SFNT name table needed to detect conflicting font identity."""
    if data[:4] == b"ttcf" and offset == 0:
        if len(data) < 12:
            raise ValueError("A font attachment has an invalid TTC header.")
        count = struct.unpack_from(">I", data, 8)[0]
        directory_end = 12 + count * 4
        if not 1 <= count <= 256 or directory_end > len(data):
            raise ValueError("A font attachment has an invalid TTC face directory.")
        names = set()
        for index in range(count):
            face = struct.unpack_from(">I", data, 12 + index * 4)[0]
            if face < directory_end:
                raise ValueError("A font attachment has an invalid TTC face offset.")
            names.update(_font_names(data, offset=face))
        return names
    if offset + 12 > len(data):
        raise ValueError("A font attachment has an invalid SFNT header.")
    table_count = struct.unpack_from(">H", data, offset + 4)[0]
    if table_count > 256:
        raise ValueError("A font attachment has too many tables.")
    name_offset = None
    for index in range(table_count):
        record = offset + 12 + 16 * index
        if record + 16 > len(data):
            raise ValueError("A font attachment has a truncated table directory.")
        tag, _, table_offset, table_length = struct.unpack_from(">4sIII", data, record)
        if tag == b"name":
            if table_offset + table_length > len(data):
                raise ValueError("A font attachment has an invalid name table.")
            name_offset = table_offset
            break
    if name_offset is None or name_offset + 6 > len(data):
        raise ValueError("A font attachment has no readable name table.")
    _, count, string_offset = struct.unpack_from(">HHH", data, name_offset)
    if count > 2048:
        raise ValueError("A font attachment has too many name records.")
    names = {1: set(), 2: set(), 6: set(), 16: set(), 17: set()}
    for index in range(count):
        record = name_offset + 6 + 12 * index
        if record + 12 > len(data):
            raise ValueError("A font attachment has truncated name records.")
        platform, _, _, name_id, length, relative = struct.unpack_from(">HHHHHH", data, record)
        if name_id not in names or length > 4096:
            continue
        start = name_offset + string_offset + relative
        if start + length > len(data):
            raise ValueError("A font attachment has an invalid name string.")
        encoding = "utf-16-be" if platform in {0, 3} else "mac-roman"
        value = data[start:start + length].decode(encoding, errors="replace").strip().casefold()
        if value:
            names[name_id].add(value)
    family = names[16] or names[1]
    style = names[17] or names[2] or {"regular"}
    if not family and not names[6]:
        raise ValueError("A font attachment has no usable family or PostScript name.")
    return {("family-style", f, s) for f in family for s in style} | {
        ("postscript", value) for value in names[6]
    }


async def _run(arguments, listener, *, timeout=12 * 60 * 60):
    if listener.is_cancelled:
        return -1, "Merge was cancelled."
    process = await asyncio.create_subprocess_exec(
        *map(str, arguments),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    listener.subproc = process
    communication = asyncio.create_task(process.communicate())
    elapsed = 0
    try:
        while not communication.done():
            if listener.is_cancelled:
                process.terminate()
                try:
                    await asyncio.wait_for(asyncio.shield(communication), 5)
                except TimeoutError:
                    process.kill()
                    await communication
                return -1, "Merge was cancelled."
            if elapsed >= timeout:
                process.kill()
                await communication
                return -1, "Merge processing timed out."
            try:
                await asyncio.wait_for(asyncio.shield(communication), 1)
            except TimeoutError:
                elapsed += 1
        stdout, stderr = await communication
        # Inspection commands write their machine-readable payload to stdout.
        # Tools may also emit harmless warnings on stderr while succeeding;
        # returning that warning or truncating a large payload would corrupt
        # otherwise valid JSON or framemd5 output. Bound only error diagnostics.
        # MKVToolNix exits 1 on warnings (e.g. regenerated duplicate track UIDs).
        # The finished artifact still has to pass every preservation check.
        warning = process.returncode == 1 and Path(str(arguments[0])).stem.casefold() in {"mkvmerge", "mkvextract"}
        if process.returncode == 0 or warning:
            return 0, stdout.decode(errors="replace").strip()
        diagnostic = (stderr or stdout).decode(errors="replace")[-16000:].strip()
        return process.returncode, diagnostic
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        if not communication.done():
            await communication
        if listener.subproc is process:
            listener.subproc = None


async def _json_command(arguments, listener):
    code, output = await _run(arguments, listener, timeout=120)
    if code:
        raise ValueError(output or f"Media inspection failed (exit {code}).")
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError("Media inspection returned invalid JSON.") from error


def _tracks(identity, kind):
    return [track for track in identity.get("tracks", []) if track.get("type") == kind]


def _av_identity(layout):
    fields = (
        "codec_id", "codec_private_data", "pixel_dimensions",
        "display_dimensions", "audio_sampling_frequency", "audio_channels",
    )
    return [
        (track.get("type"), tuple((track.get("properties") or {}).get(field) for field in fields))
        for track in layout
    ]


def _chapter_timestamp(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("The A/V timeline has a non-finite timestamp.")
        return result
    except (InvalidOperation, TypeError) as error:
        raise ValueError("The A/V timeline has an invalid chapter timestamp.") from error


def _origin(probe):
    starts = []
    for stream in probe.get("streams") or []:
        if stream.get("codec_type") not in {"video", "audio"}:
            continue
        if (stream.get("disposition") or {}).get("attached_pic"):
            continue
        if stream.get("start_time") is not None:
            starts.append(_chapter_timestamp(stream["start_time"]))
    return min(starts) if starts else Decimal(0)


def _video_span(probe):
    video = next(
        (stream for stream in probe.get("streams") or []
         if stream.get("codec_type") == "video"
         and not (stream.get("disposition") or {}).get("attached_pic")),
        None,
    )
    if video is None:
        raise ValueError("A selected item has no playable video stream.")
    value = video.get("duration")
    absolute_end = value is None
    if value is None and (video.get("tags") or {}).get("DURATION"):
        clock = str(video["tags"]["DURATION"]).split(":")
        if len(clock) == 3:
            value = sum(_chapter_timestamp(part) * scale for part, scale in zip(clock, (3600, 60, 1), strict=True))
    if value is None:
        value = (probe.get("format") or {}).get("duration")
    duration = _chapter_timestamp(value)
    if absolute_end:
        duration -= _video_origin(probe)
    if duration <= 0:
        raise ValueError("A selected item has no finite video duration.")
    return duration


def _video_origin(probe):
    video = next((stream for stream in probe.get("streams") or []
                  if stream.get("codec_type") == "video"
                  and not (stream.get("disposition") or {}).get("attached_pic")), {})
    return _chapter_timestamp(video.get("start_time") or 0)


def _check_selected_streams(probes):
    for item_number, probe in enumerate(probes, 1):
        for stream in probe.get("streams") or []:
            if stream.get("codec_type") == "data":
                raise ValueError(f"Item {item_number} has a data stream this merge cannot preserve safely.")


def _chapter_name(path):
    name = Path(path).stem
    return re.sub(r"^\d{1,8}\s+-\s+", "", name).replace("\r", " ").replace("\n", " ")[:200]


def associate_sidecars(videos, sidecars):
    """Associate only exact video stems plus recognized language/role suffixes."""
    selected = {}
    sidecar_set = set(sidecars)
    for sidecar in sidecars:
        suffix = Path(sidecar).suffix.casefold()
        if suffix == ".sub" and str(Path(sidecar).with_suffix(".idx")) in sidecar_set:
            continue
        if suffix == ".idx" and str(Path(sidecar).with_suffix(".sub")) not in sidecar_set:
            raise ValueError(f"VobSub index has no matching .sub file: {Path(sidecar).name}")
        if suffix == ".sub":
            raise ValueError(f"Standalone .sub subtitle format is ambiguous: {Path(sidecar).name}")
        same_dir = [video for video in videos if Path(video).parent == Path(sidecar).parent]
        side_stem = Path(sidecar).stem.casefold()
        matches = []
        for video in same_dir:
            video_stem = Path(video).stem.casefold()
            if side_stem == video_stem:
                matches.append(video)
                continue
            if side_stem.startswith((video_stem + ".", video_stem + "_", video_stem + "-")):
                label = side_stem[len(video_stem) + 1:]
                if re.fullmatch(r"(?:[a-z]{2,3}(?:-[a-z]{2,4})?|forced|signs|sdh|cc|hi)(?:[._-](?:forced|signs|sdh|cc|hi))?", label):
                    matches.append(video)
        if len(matches) != 1:
            raise ValueError(f"Subtitle association is {'ambiguous' if matches else 'missing'}: {Path(sidecar).name}")
        selected.setdefault(matches[0], []).append(sidecar)
    return selected


def _sidecar_tags(video, sidecar):
    suffix = Path(sidecar).stem[len(Path(video).stem) + 1:].casefold()
    language = re.match(r"([a-z]{2,3}(?:-[a-z]{2,4})?)(?:[._-]|$)", suffix)
    roles = set(re.split(r"[._-]", suffix))
    return (language.group(1) if language and language.group(1) not in {"sdh", "cc", "hi"}
            else None), "forced" in roles, bool(roles & {"sdh", "cc", "hi"})


def validate_merge_encode_profile(profile):
    """Reject profile features the single-timeline command cannot honor."""
    if not isinstance(profile, dict):
        return "A merge encode profile is required."
    video = profile.get("video_params") or {}
    if (
        profile.get("subtitle_mode", "copy") != "copy"
        or profile.get("video_codec") == "copy"
        or profile.get("audio_codec") == "copy"
        or any(profile.get(key) for key in ("cover_image", "rename", "metadata", "disposition"))
        or video.get("extra_params")
    ):
        return (
            "This merge encode profile requests copy, burn-in, subtitle exclusion, "
            "metadata, or extra processing that cannot be preserved safely."
        )
    if any(video.get(key) is not None for key in ("fast_decode", "keyint_seconds")):
        return "Fast-decode and keyframe interval profile settings are not supported for one continuous merge."
    if video.get("fps_mode", "vfr") not in {"vfr", "auto"}:
        return "This merge encode profile requests an unsupported frame-rate mode."
    if profile.get("video_codec") not in {"libx264", "libx265"} and (
        video.get("level") or video.get("profile") not in (None, 0, "0")
    ):
        return "This merge encode profile requests a codec level or profile this timeline encoder cannot honor."
    return ""


def _write_chapters(path, starts, files):
    lines = []
    for index, (start, file_) in enumerate(zip(starts, files, strict=True), 1):
        milliseconds = int((start * 1000).to_integral_value())
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        lines.append(f"CHAPTER{index:02d}={hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}")
        lines.append(f"CHAPTER{index:02d}NAME={_chapter_name(file_)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _attachment_records(extractor, file_, attachments, working, listener):
    records = []
    for index, attachment in enumerate(attachments):
        if int(attachment.get("size") or 0) > 64 * 1024 * 1024:
            raise ValueError("A source attachment exceeds the 64 MiB inspection limit.")
        target = os.path.join(working, f"attachment-{token_hex(8)}-{index}")
        code, diagnostic = await _run(
            [extractor, file_, "attachments", f"{attachment['id']}:{target}"],
            listener,
            timeout=120,
        )
        if code:
            raise ValueError(f"Could not inspect a source attachment: {diagnostic or code}")
        content = Path(target).read_bytes()
        if len(content) > 64 * 1024 * 1024:
            raise ValueError("A source attachment exceeds the inspection limit.")
        name = str(attachment.get("file_name") or "")
        mime = str(attachment.get("content_type") or "")
        digest = hashlib.sha256(content).hexdigest()
        font = name.casefold().endswith((".ttf", ".otf", ".ttc")) or mime.casefold().startswith("font/")
        records.append({
            "id": attachment["id"], "name": name, "mime": mime,
            "hash": digest, "font_names": _font_names(content) if font else set(),
        })
        os.remove(target)
    return records


async def _select_attachments(executable, files, identities, working, listener):
    # MKVToolNix presents MP4 attached pictures as image attachments. Keep
    # subtitle dependencies, but omit source artwork from the merged artifact.
    kept_attachments = [
        [
            attachment for attachment in info.get("attachments") or []
            if not str(attachment.get("content_type") or "").casefold().startswith("image/")
            and not str(attachment.get("file_name") or "").casefold().endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp")
            )
        ]
        for info in identities
    ]
    if not any(kept_attachments):
        return [[] for _ in files], []
    extractor = _mkvextract_binary(executable)
    if not extractor:
        raise ValueError("MKVToolNix (mkvextract) is required to verify subtitle font attachments.")
    selected = []
    expected = []
    seen_hashes = set()
    names = {}
    font_names = {}
    for file_, attachments in zip(files, kept_attachments, strict=True):
        records = await _attachment_records(
            extractor, file_, attachments, working, listener
        )
        ids = []
        for record in records:
            if record["hash"] in seen_hashes:
                continue
            folded_name = record["name"].casefold()
            if folded_name in names and names[folded_name] != record["hash"]:
                raise ValueError(f"Different attachments share the filename {record['name']!r}.")
            for font_name in record["font_names"]:
                if font_name in font_names and font_names[font_name] != record["hash"]:
                    raise ValueError("Different embedded fonts have the same internal family/style or PostScript name.")
                font_names[font_name] = record["hash"]
            names[folded_name] = record["hash"]
            seen_hashes.add(record["hash"])
            expected.append(record)
            ids.append(record["id"])
        selected.append(ids)
    return selected, expected


async def _validate_attachments(executable, candidate, expected, working, listener):
    identity = await _json_command([executable, "-J", candidate], listener)
    actual = identity.get("attachments") or []
    if len(actual) != len(expected):
        raise ValueError(f"Merged output has {len(actual)} attachments; expected {len(expected)}.")
    if not expected:
        return
    extractor = _mkvextract_binary(executable)
    records = await _attachment_records(extractor, candidate, actual, working, listener)
    def signature(record):
        return record["name"], record["mime"], record["hash"]
    if Counter(map(signature, records)) != Counter(map(signature, expected)):
        raise ValueError("Merged output changed an attachment or font dependency.")


async def _subtitle_evidence(path, listener):
    return await _json_command(
        [
            "ffprobe", "-v", "error", "-select_streams", "s",
            "-show_streams", "-show_packets", "-show_data_hash", "sha256",
            "-show_entries", "stream=index,codec_name,extradata_hash:packet=stream_index,pts_time,duration_time,data_hash",
            "-of", "json", path,
        ],
        listener,
    )


async def _prepare_sidecar(sidecar, working, listener):
    target = os.path.join(working, f"sidecar-{token_hex(8)}.mkv")
    code, diagnostic = await _run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", sidecar, "-map", "0:s", "-c:s", "copy", target],
        listener,
        timeout=120,
    )
    if code:
        raise ValueError(f"Could not preserve external subtitle {Path(sidecar).name}: {diagnostic or code}")
    before = await _subtitle_evidence(sidecar, listener)
    after = await _subtitle_evidence(target, listener)
    if len(before.get("streams") or []) != len(after.get("streams") or []):
        raise ValueError(f"External subtitle track count changed: {Path(sidecar).name}")
    for original, remuxed in zip(before.get("streams") or [], after.get("streams") or [], strict=True):
        if (original.get("codec_name"), original.get("extradata_hash")) != (
            remuxed.get("codec_name"), remuxed.get("extradata_hash")
        ):
            raise ValueError(f"External subtitle header changed: {Path(sidecar).name}")
    if [
        (packet.get("data_hash"), packet.get("pts_time"))
        for packet in before.get("packets") or []
    ] != [
        (packet.get("data_hash"), packet.get("pts_time"))
        for packet in after.get("packets") or []
    ]:
        raise ValueError(f"External subtitle events changed: {Path(sidecar).name}")
    return target


def _packets_by_stream(evidence):
    packets = {}
    for packet in evidence.get("packets") or []:
        packets.setdefault(packet.get("stream_index"), []).append(packet)
    return packets


async def _validate_subtitles(inputs, candidate, listener):
    # inputs are (subtitle-bearing path, timeline offset, original item number)
    sources = [await _subtitle_evidence(path, listener) for path, _, _ in inputs]
    result = await _subtitle_evidence(candidate, listener)
    expected = [
        (item_number, stream, offset, source_index)
        for source_index, (source, (_, offset, item_number)) in enumerate(zip(sources, inputs, strict=True))
        for stream in source.get("streams") or []
    ]
    actual = result.get("streams") or []
    if len(actual) != len(expected):
        raise ValueError(f"Merged output has {len(actual)} subtitle tracks; expected {len(expected)}.")
    source_packets = [_packets_by_stream(source) for source in sources]
    output_packets = _packets_by_stream(result)
    for (item_number, original, offset, source_index), merged in zip(expected, actual, strict=True):
        if (original.get("codec_name"), original.get("extradata_hash")) != (
            merged.get("codec_name"), merged.get("extradata_hash")
        ):
            raise ValueError(f"Subtitle format or rendering header changed for item {item_number}.")
        before = source_packets[source_index].get(original.get("index"), [])
        after = output_packets.get(merged.get("index"), [])
        if len(before) != len(after):
            raise ValueError(f"Subtitle event count changed for item {item_number}.")
        for source_packet, result_packet in zip(before, after, strict=True):
            if source_packet.get("data_hash") != result_packet.get("data_hash"):
                raise ValueError(f"Subtitle event content changed for item {item_number}.")
            source_pts = _chapter_timestamp(source_packet.get("pts_time"))
            result_pts = _chapter_timestamp(result_packet.get("pts_time"))
            if abs(result_pts - source_pts - offset) > Decimal("0.003"):
                raise ValueError(f"Subtitle event timing changed for item {item_number}.")
            if source_packet.get("duration_time") is not None:
                before_duration = _chapter_timestamp(source_packet["duration_time"])
                after_duration = _chapter_timestamp(result_packet.get("duration_time"))
                if abs(before_duration - after_duration) > Decimal("0.003"):
                    raise ValueError(f"Subtitle event duration changed for item {item_number}.")


async def _validate_playback(candidate, duration, has_audio, listener):
    """Decode bounded start/middle/end samples before publishing the artifact."""
    points = {Decimal(0), duration / 2, max(Decimal(0), duration - Decimal("0.6"))}
    for point in sorted(points):
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin",
            "-ss", format(point, "f"), "-i", candidate, "-t", "0.4", "-map", "0:v:0",
        ]
        if has_audio:
            command += ["-map", "0:a:0"]
        command += ["-f", "framemd5", "pipe:1"]
        code, output = await _run(command, listener, timeout=90)
        frames = [line.split(",", 1)[0].strip() for line in output.splitlines()
                  if line and not line.startswith("#") and "," in line]
        if code or "0" not in frames or (has_audio and "1" not in frames):
            raise ValueError(
                f"The merged output could not decode video/audio near {point:.2f}s."
            )


async def _join_subtitle_tracks(executable, candidate, working, listener):
    """Combine text lanes; reject incompatible text and preserve bitmap tracks."""
    identity = await _json_command([executable, "-J", candidate], listener)
    evidence = await _subtitle_evidence(candidate, listener)
    tracks = _tracks(identity, "subtitles")
    groups = []
    lane_positions = Counter()
    packets = _packets_by_stream(evidence)
    extraction = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts", "-i", candidate]
    text_paths = {}
    for index, stream in enumerate(evidence.get("streams") or []):
        codec = stream.get("codec_name")
        if codec in {"ass", "subrip"}:
            text_paths[index] = os.path.join(working, f"text-{index}.{'ass' if codec == 'ass' else 'srt'}")
            extraction += ["-map", f"0:{stream['index']}", "-c:s", "copy", text_paths[index]]
    if text_paths:
        code, diagnostic = await _run(extraction, listener)
        if code:
            raise ValueError(f"Subtitle extraction failed: {diagnostic or code}")
    indexed_tracks = list(enumerate(zip(tracks, evidence.get("streams") or [], strict=True)))
    # Match each episode's default dialogue before alternate same-language tracks.
    indexed_tracks.sort(key=lambda item: not (item[1][0].get("properties") or {}).get("default_track"))
    for index, (track, stream) in indexed_tracks:
        properties = track.get("properties") or {}
        title = re.sub(r"^Episode \d+ - ", "", properties.get("track_name") or "")
        item_number = re.match(r"Episode (\d+)", properties.get("track_name") or "")
        item_number = int(item_number[1]) if item_number else index
        codec = stream.get("codec_name")
        document = None
        if index in text_paths:
            try:
                document = read_document(Path(text_paths[index]).read_text(encoding="utf-8-sig"), codec)
                if codec == "ass":
                    join_documents([document])
            except ValueError:
                # Preserve unusual ASS sections/layouts as their original track.
                document = None
            if document is not None and len(document["events"]) != len(packets.get(stream["index"], [])):
                raise ValueError("Subtitle extraction changed the number of events.")
        role = (properties.get("language") or "und",) + tuple(bool(properties.get(key)) for key in (
            "forced_track", "hearing_impaired", "visual_impaired", "text_descriptions", "commentary",
        ))
        position_key = (item_number, codec, role)
        lane = (codec, role, lane_positions[position_key])
        lane_positions[position_key] += 1
        key = (*lane, document["key"] if document else index)
        matches = [group for group in groups if group["key"] == key
                   and item_number not in group["items"]] if document else []
        group = next((group for group in matches if group["title"] == title), None)
        group = group or next(iter(matches), None)
        if group is None:
            group = {"key": key, "tracks": [], "documents": [], "items": set(),
                     "properties": properties, "title": title, "codec": codec}
            groups.append(group)
        group["tracks"].append((track, stream))
        group["items"].add(item_number)
        if document:
            group["documents"].append(document)
    lanes = Counter(group["key"][:3] for group in groups if group["codec"] in {"ass", "subrip"})
    for lane, count in lanes.items():
        if count <= 1:
            continue
        related = [group for group in groups if group["key"][:3] == lane]
        settings = [dict(group["documents"][0]["key"][0]) for group in related if group["documents"] and group["codec"] == "ass"]
        differences = sorted(key for key in set().union(*(set(item) for item in settings))
                             if len({item.get(key) for item in settings}) > 1) if settings else []
        reason = ", ".join(differences) or "unsupported subtitle header, styles, or event format"
        raise ValueError(
            f"Cannot create one continuous {lane[1][0]} dialogue subtitle track: {reason}. "
            "The merge stopped instead of publishing separate episode subtitle tracks."
        )
    if not any(len(group["tracks"]) > 1 for group in groups):
        return candidate, len(tracks), len(tracks)

    if shutil.disk_usage(working).free < os.path.getsize(candidate) + 64 * 1024**2:
        raise ValueError("Not enough free disk space to assemble continuous subtitle tracks.")

    result = os.path.join(working, "continuous-subtitles.mkv")
    command = [executable, "--quiet", "-o", result, "--no-subtitles", candidate]
    validation_inputs = []
    independent = 0
    default_index = next((i for i, group in enumerate(groups)
                          if group["properties"].get("default_track") and not group["properties"].get("forced_track")),
                         next((i for i, group in enumerate(groups) if not group["properties"].get("forced_track")), 0))
    for index, group in enumerate(groups):
        target = os.path.join(working, f"lane-{index}.mkv")
        if len(group["tracks"]) > 1:
            text = join_documents(group["documents"])
            text_path = os.path.join(working, f"lane-{index}.{'ass' if group['codec'] == 'ass' else 'srt'}")
            Path(text_path).write_text(text, encoding="utf-8")
            code, diagnostic = await _run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", text_path, "-map", "0:s", "-c:s", "copy", target], listener,
            )
            if code:
                raise ValueError(f"Continuous subtitle mux failed: {diagnostic or code}")
            checked = os.path.join(working, f"checked-{index}.{Path(text_path).suffix.lstrip('.')}")
            code, diagnostic = await _run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts",
                 "-i", target, "-map", "0:s", "-c:s", "copy", checked], listener,
            )
            if code or read_document(Path(checked).read_text(encoding="utf-8-sig"), group["codec"]) != read_document(text, group["codec"]):
                raise ValueError("Continuous subtitle mux changed events, timing or ASS styles.")
        else:
            independent += 1
            track, stream = group["tracks"][0]
            code, diagnostic = await _run(
                [executable, "--quiet", "-o", target, "--no-video", "--no-audio",
                 "--no-attachments", "--no-chapters", "--no-global-tags",
                 "--subtitle-tracks", str(track["id"]), candidate], listener,
            )
            if code:
                raise ValueError(f"Independent subtitle mux failed: {diagnostic or code}")
            before = dict(evidence, streams=[stream], packets=packets.get(stream["index"], []))
            after = await _subtitle_evidence(target, listener)
            original = before["packets"]
            remuxed = after.get("packets") or []
            if [(p.get("data_hash"), p.get("pts_time"), p.get("duration_time")) for p in original] != [
                (p.get("data_hash"), p.get("pts_time"), p.get("duration_time")) for p in remuxed
            ] or stream.get("extradata_hash") != after["streams"][0].get("extradata_hash"):
                raise ValueError("An independent subtitle track changed during muxing.")
        prepared = await _json_command([executable, "-J", target], listener)
        track_id = _tracks(prepared, "subtitles")[0]["id"]
        command += ["--no-video", "--no-audio", "--no-attachments", "--no-chapters", "--no-global-tags"]
        properties = group["properties"]
        command += ["--language", f"{track_id}:{properties.get('language_ietf') or properties.get('language') or 'und'}",
                    "--track-name", f"{track_id}:{group['title']}" if len(group["tracks"]) > 1 else f"{track_id}:{properties.get('track_name') or group['title']}",
                    "--default-track-flag", f"{track_id}:{'yes' if index == default_index else 'no'}"]
        for property_, option in (("forced_track", "--forced-display-flag"),
                                  ("hearing_impaired", "--hearing-impaired-flag"),
                                  ("visual_impaired", "--visual-impaired-flag"),
                                  ("text_descriptions", "--text-descriptions-flag"),
                                  ("original", "--original-flag"), ("commentary", "--commentary-flag")):
            if properties.get(property_) is not None:
                command += [option, f"{track_id}:{'yes' if properties[property_] else 'no'}"]
        command.append(target)
        validation_inputs.append((target, Decimal(0), index + 1))
    code, diagnostic = await _run(command, listener)
    if code:
        raise ValueError(f"Continuous subtitle assembly failed: {diagnostic or code}")
    await _validate_subtitles(validation_inputs, result, listener)
    return result, len(groups), independent


async def merge_copy(
    listener, files, output_file, probes, *, sidecars=None,
    av_override=None, starts_override=None,
):
    """Return (published artifact, error) after copy, independent subtitle mux and validation."""
    executable = _mkvmerge_binary()
    if not executable:
        return False, "MKVToolNix (mkvmerge) is required for preservation-safe merge."
    if os.path.exists(output_file):
        return False, "The requested merge output already exists; choose another name."
    if len(files) < 2 or len(probes) != len(files):
        return False, "Merge requires at least two inputs with one probe per input."
    sidecars = sidecars or {}
    try:
        _check_selected_streams(probes)
        identities = [
            await _json_command([executable, "-J", file_], listener)
            for file_ in files
        ]
        av_layout = [
            [track for track in info.get("tracks", [])
             if track.get("type") in {"video", "audio"}]
            for info in identities
        ]
        if not av_layout or not av_layout[0]:
            raise ValueError("The selected inputs have no playable A/V tracks.")
        kinds = [track["type"] for track in av_layout[0]]
        if not av_override and ("video" not in kinds or any(
            [track["type"] for track in layout] != kinds
            or _av_identity(layout) != _av_identity(av_layout[0])
            for layout in av_layout[1:]
        )):
            raise ValueError("The selected A/V track layouts cannot be appended without loss.")
        with tempfile.TemporaryDirectory(prefix="merge-", dir=os.path.dirname(output_file)) as working:
            av_file = av_override or os.path.join(working, "timeline.mkv")
            chapters_file = os.path.join(working, "chapters.txt")
            candidate = os.path.join(working, f"candidate-{token_hex(6)}.mkv")
            attachment_ids, expected_attachments = await _select_attachments(
                executable, files, identities, working, listener
            )
            if not av_override:
                mapping = [
                    f"{index}:{track['id']}:{index - 1}:{av_layout[index - 1][track_position]['id']}"
                    for index, layout in enumerate(av_layout) if index
                    for track_position, track in enumerate(layout)
                ]
                command = [executable, "--quiet", "--generate-chapters", "when-appending"]
                if mapping:
                    command += ["--append-to", ",".join(mapping)]
                command += ["-o", av_file]
                for index, file_ in enumerate(files):
                    if index:
                        command.append("+")
                    command += ["--no-subtitles", "--no-attachments", "--no-chapters", "--no-global-tags", file_]
                code, diagnostic = await _run(command, listener)
                if code:
                    raise ValueError(f"A/V append failed: {diagnostic or f'exit {code}'}")
            av_probe = await _json_command(
                ["ffprobe", "-v", "error", "-show_streams", "-show_chapters", "-show_format", "-show_data_hash", "sha256", "-of", "json", av_file],
                listener,
            )
            if av_override:
                if starts_override is None or len(starts_override) != len(files):
                    raise ValueError("The encoded timeline has no complete source boundaries.")
                starts = list(starts_override)
            else:
                chapters = av_probe.get("chapters") or []
                if len(chapters) != len(files):
                    raise ValueError("The A/V intermediate did not retain one boundary per selected video.")
                starts = [_chapter_timestamp(chapter["start_time"]) for chapter in chapters]
            kinds = [stream["codec_type"] for stream in av_probe.get("streams") or []
                     if stream.get("codec_type") in {"video", "audio"}]
            _write_chapters(chapters_file, starts, files)

            command = [executable, "--quiet", "-o", candidate, "--chapters", chapters_file,
                       "--no-subtitles", "--no-attachments", "--no-chapters", "--no-global-tags", av_file]
            subtitle_count = 0
            subtitle_inputs = []
            for index, (file_, info, probe) in enumerate(zip(files, identities, probes, strict=True)):
                subtitles = _tracks(info, "subtitles")
                if subtitles or attachment_ids[index]:
                    command += ["--no-video", "--no-audio", "--no-chapters", "--no-global-tags"]
                    if attachment_ids[index]:
                        command += ["--attachments", ",".join(map(str, attachment_ids[index]))]
                    else:
                        command.append("--no-attachments")
                    if subtitles:
                        command += ["--subtitle-tracks", ",".join(str(track["id"]) for track in subtitles)]
                        origin = _video_origin(probe) if av_override else _origin(probe)
                        subtitle_inputs.append((file_, starts[index] - origin, index + 1))
                    else:
                        command.append("--no-subtitles")
                    for track in subtitles:
                        track_id = track["id"]
                        offset_ms = int(((starts[index] - origin) * 1000).to_integral_value())
                        command += ["--sync", f"{track_id}:{offset_ms}"]
                        original_title = (track.get("properties") or {}).get("track_name")
                        label = f"Episode {index + 1:02d} - {original_title or track.get('codec', 'subtitle')}"
                        command += ["--track-name", f"{track_id}:{label}"]
                        has_default = any((item.get("properties") or {}).get("default_track") for item in subtitles)
                        source_default = (track.get("properties") or {}).get("default_track") or (not has_default and subtitle_count == 0)
                        command += ["--default-track-flag", f"{track_id}:{'yes' if source_default else 'no'}"]
                        subtitle_count += 1
                    command.append(file_)
                for sidecar in sidecars.get(file_, []):
                    prepared = await _prepare_sidecar(sidecar, working, listener)
                    side_info = await _json_command([executable, "-J", prepared], listener)
                    side_tracks = _tracks(side_info, "subtitles")
                    if not side_tracks:
                        raise ValueError(f"External file contains no subtitle track: {Path(sidecar).name}")
                    language, forced, hearing_impaired = _sidecar_tags(file_, sidecar)
                    command += ["--no-video", "--no-audio", "--no-attachments", "--no-chapters", "--no-global-tags",
                                 "--subtitle-tracks", ",".join(str(track["id"]) for track in side_tracks)]
                    for track in side_tracks:
                        track_id = track["id"]
                        offset_ms = int((starts[index] * 1000).to_integral_value())
                        command += ["--sync", f"{track_id}:{offset_ms}"]
                        if language:
                            command += ["--language", f"{track_id}:{language}"]
                        if forced:
                            command += ["--forced-display-flag", f"{track_id}:yes"]
                        if hearing_impaired:
                            command += ["--hearing-impaired-flag", f"{track_id}:yes"]
                        signs = 'signs' in re.split(r"[._-]", Path(sidecar).stem[len(Path(file_).stem):].casefold())
                        label = f"{track.get('codec', 'subtitles')}{' signs' if signs else ''}"
                        command += ["--track-name", f"{track_id}:Episode {index + 1:02d} - {label}"]
                        command += ["--default-track-flag", f"{track_id}:{'yes' if subtitle_count == 0 else 'no'}"]
                        subtitle_count += 1
                    command.append(prepared)
                    subtitle_inputs.append((prepared, starts[index], index + 1))
            code, diagnostic = await _run(command, listener)
            if code:
                raise ValueError(f"Final Matroska assembly failed: {diagnostic or f'exit {code}'}")
            await _validate_subtitles(subtitle_inputs, candidate, listener)
            if not av_override:
                os.remove(av_file)
            candidate, subtitle_count, independent_count = await _join_subtitle_tracks(
                executable, candidate, working, listener
            )
            final_probe = await _json_command(
                ["ffprobe", "-v", "error", "-show_streams", "-show_chapters", "-show_format", "-show_data_hash", "sha256", "-of", "json", candidate],
                listener,
            )
            if len(final_probe.get("chapters") or []) != len(files):
                raise ValueError("The merged output did not retain every chapter.")
            if [stream.get("codec_type") for stream in final_probe.get("streams") or [] if stream.get("codec_type") in {"video", "audio"}] != kinds:
                raise ValueError("The merged output changed the selected A/V track layout.")
            expected_duration = _chapter_timestamp((av_probe.get("format") or {}).get("duration"))
            actual_duration = _chapter_timestamp((final_probe.get("format") or {}).get("duration"))
            if abs(actual_duration - expected_duration) > Decimal("0.05"):
                raise ValueError("Final mux duration differs from the validated A/V timeline.")
            # MP4/AAC priming can make MKVToolNix place the first boundary a
            # few milliseconds after zero even though no episode is missing.
            if not 0 <= starts[0] <= Decimal("0.05") or any(
                right <= left for left, right in zip(starts, starts[1:], strict=False)
            ):
                raise ValueError("The A/V timeline has missing or non-monotonic chapter boundaries.")
            actual_av = [
                stream for stream in final_probe.get("streams") or []
                if stream.get("codec_type") in {"video", "audio"}
            ]
            original_av = [
                stream for stream in av_probe.get("streams") or []
                if stream.get("codec_type") in {"video", "audio"}
            ]
            for original, merged in zip(original_av, actual_av, strict=True):
                for field in ("codec_name", "width", "height", "sample_rate", "channels", "extradata_hash"):
                    if original.get(field) is not None and original.get(field) != merged.get(field):
                        raise ValueError(f"The merged A/V track changed {field}.")
            await _validate_attachments(
                executable, candidate, expected_attachments, working, listener
            )
            await _validate_playback(
                candidate, actual_duration, "audio" in kinds, listener
            )
            if listener.is_cancelled:
                raise ValueError("Merge was cancelled before publication.")
            # The candidate and published artifact are on one filesystem. A
            # hard link atomically refuses to replace an unrelated output.
            os.link(candidate, output_file)
            listener.merge_subtitle_count = subtitle_count
            listener.merge_subtitle_summary = (
                f"{subtitle_count} selectable subtitle tracks. Compatible tracks continue across episodes. "
                f"{independent_count} tracks cover individual parts or use separate formats/settings."
                if subtitle_count else "No subtitle tracks found."
            )
            return output_file, ""
    except asyncio.CancelledError:
        listener.is_cancelled = True
        return False, "Merge was cancelled."
    except (OSError, ValueError, InvalidOperation) as error:
        return False, str(error)


async def merge_encode(listener, files, output_file, probes, profile, *, sidecars=None):
    """Decode an ordered A/V timeline once, then mux untouched subtitles."""
    if len(files) < 2 or len(probes) != len(files):
        return False, "Merge requires at least two inputs with one probe per input."
    problem = validate_merge_encode_profile(profile)
    if problem:
        return False, problem
    video_codec = profile.get("video_codec", "libx264")
    audio_codec = profile.get("audio_codec", "aac")
    video_params = profile.get("video_params") or {}
    audio_params = profile.get("audio_params") or {}
    video_tracks = []
    audio_tracks = []
    try:
        _check_selected_streams(probes)
        for probe in probes:
            videos = [stream for stream in probe.get("streams") or []
                      if stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")]
            audios = [stream for stream in probe.get("streams") or [] if stream.get("codec_type") == "audio"]
            if len(videos) != 1:
                raise ValueError("Continuous merge encoding requires one video stream per item.")
            video_tracks.append(videos[0])
            audio_tracks.append(audios)
        audio_count = len(audio_tracks[0])
        if any(len(tracks) != audio_count for tracks in audio_tracks):
            raise ValueError("The source audio track counts differ; no track will be silently dropped or synthesized.")
        for position in range(audio_count):
            identity = [
                ((tracks[position].get("tags") or {}).get("language"),
                 tuple((tracks[position].get("disposition") or {}).get(key) for key in ("forced", "hearing_impaired")))
                for tracks in audio_tracks
            ]
            if any(item != identity[0] for item in identity[1:]):
                raise ValueError(f"Audio track {position + 1} changes language or role between items.")
        color_fields = ("color_range", "color_space", "color_transfer", "color_primaries")
        if any(tuple(track.get(field) for field in color_fields) !=
               tuple(video_tracks[0].get(field) for field in color_fields)
               for track in video_tracks[1:]):
            raise ValueError("Input color or HDR properties differ; this profile does not define a safe conversion.")
        pixel_format = str(video_params.get("pix_fmt") or "yuv420p")
        if video_tracks[0].get("color_transfer") in {"smpte2084", "arib-std-b67"} and "10" not in pixel_format:
            raise ValueError("HDR input cannot be flattened into this profile's pixel format.")
        width = int(video_params.get("width") or video_tracks[0].get("width") or 0)
        height = int(video_params.get("height") or video_tracks[0].get("height") or 0)
        if not (16 <= width <= 7680 and 16 <= height <= 4320 and width % 2 == height % 2 == 0):
            raise ValueError("The merge encode profile has invalid output dimensions.")
        channels = audio_params.get("channels")
        if channels is None and audio_count:
            channel_counts = {int(track.get("channels") or 0) for tracks in audio_tracks for track in tracks}
            if len(channel_counts) != 1:
                raise ValueError("Audio channel layouts differ; select an explicit encoded channel count.")
            channels = channel_counts.pop()
        channels = int(channels or 2)
        layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(channels)
        if layout is None:
            raise ValueError("The selected encoded channel layout is unsupported for a continuous merge.")
        sample_rate = int(audio_params.get("sample_rate") or (audio_tracks[0][0].get("sample_rate") if audio_count else 48000) or 0)
        if not 8000 <= sample_rate <= 192000:
            raise ValueError("The selected encoded audio sample rate is invalid.")
        spans = [_video_span(probe) for probe in probes]
        starts = [Decimal(0)]
        for span in spans[:-1]:
            starts.append(starts[-1] + span)
        with tempfile.TemporaryDirectory(prefix="merge-encode-", dir=os.path.dirname(output_file)) as working:
            av_file = os.path.join(working, "encoded-timeline.mkv")
            filters = []
            joined = []
            for index, (span, tracks) in enumerate(zip(spans, audio_tracks, strict=True)):
                duration = format(span, "f")
                origin = format(_video_origin(probes[index]), "f")
                video_chain = (
                    f"[{index}:{video_tracks[index]['index']}]trim=duration={duration},setpts=PTS-STARTPTS,"
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format={pixel_format}[v{index}]"
                )
                filters.append(video_chain)
                joined.append(f"[v{index}]")
                for audio_index, _ in enumerate(tracks):
                    filters.append(
                        f"[{index}:a:{audio_index}]asetpts=PTS-({origin})/TB,"
                        f"aresample={sample_rate}:async=1:first_pts=0,"
                        f"aformat=channel_layouts={layout},apad=pad_dur={duration},"
                        f"atrim=duration={duration}[a{index}_{audio_index}]"
                    )
                    joined.append(f"[a{index}_{audio_index}]")
            outputs = "[v]" + "".join(f"[a{index}]" for index in range(audio_count))
            filters.append("".join(joined) + f"concat=n={len(files)}:v=1:a={audio_count}{outputs}")
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts"]
            for file_ in files:
                command += ["-i", file_]
            command += ["-filter_complex", ";".join(filters), "-map", "[v]"]
            for index in range(audio_count):
                command += ["-map", f"[a{index}]"]
            command += ["-map_metadata", "-1", "-map_chapters", "-1",
                        "-c:v", video_codec, "-pix_fmt", pixel_format,
                        "-c:a", audio_codec]
            for index, stream in enumerate(audio_tracks[0]):
                for key in ("language", "title"):
                    value = (stream.get("tags") or {}).get(key)
                    if value:
                        command += [f"-metadata:s:a:{index}", f"{key}={value}"]
                flags = "+".join(key for key, value in (stream.get("disposition") or {}).items() if value)
                command += [f"-disposition:a:{index}", flags or "0"]
            if video_codec == "mpeg4":
                command += ["-q:v", str(max(1, min(31, round(float(video_params.get("crf", 24)) / 6))))]
            else:
                command += ["-crf", str(video_params.get("crf", 23))]
            if video_codec in {"libx264", "libx265", "libsvtav1"}:
                command += ["-preset", str(video_params.get("preset", "medium"))]
            if video_codec in {"libx264", "libx265"}:
                if video_params.get("profile"):
                    command += ["-profile:v", str(video_params["profile"])]
                if video_params.get("level"):
                    command += ["-level:v", str(video_params["level"])]
            if video_codec == "libvpx-vp9":
                command += ["-b:v", "0"]
            if audio_params.get("bitrate"):
                command += ["-b:a", str(audio_params["bitrate"])]
            if audio_codec == "libopus" and audio_params.get("vbr") is False:
                command += ["-vbr", "off"]
            command += ["-ar", str(sample_rate), "-ac", str(channels), av_file]
            code, diagnostic = await _run(command, listener)
            if code:
                raise ValueError(f"Continuous merge encoding failed: {diagnostic or code}")
            result, error = await merge_copy(
                listener, files, output_file, probes, sidecars=sidecars,
                av_override=av_file, starts_override=starts,
            )
            return result, error
    except asyncio.CancelledError:
        listener.is_cancelled = True
        return False, "Merge was cancelled."
    except (OSError, ValueError, InvalidOperation) as error:
        return False, str(error)
