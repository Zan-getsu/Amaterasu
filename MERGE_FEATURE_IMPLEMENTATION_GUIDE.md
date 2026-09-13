# Amaterasu: reliable merge feature implementation guide

**Prepared:** 2026-09-13  
**Repository inspected:** `M:\Projects\Amaterasu-beta`  
**Inspected HEAD:** `f0903cc`  
**Purpose:** executable engineering instructions for an AI coding agent.  
**Status:** implementation specification; the work described below is not certified as implemented or production-tested.

## 1. Instructions to the implementing agent

Implement this specification in the existing Amaterasu repository. Read the current code and applicable `AGENTS.md` instructions before editing. Treat symbol names and paths below as verified starting points, not a guarantee that the checkout has not changed.

Work through the milestones in dependency order. Preserve unrelated changes, existing command routing, upload destinations, permissions, encode profiles, and Amaterasu's current visual identity. Make normal implementation decisions autonomously. Ask only when a missing product decision or access restriction actually prevents progress.

Do not stop after creating another plan. Implement, test, document, and provide a reviewable diff. Do not commit, push, deploy, send Telegram messages, or run jobs against private media unless separately authorized. Local synthetic media and mocked service integration are the default test inputs. Record external verification that is unavailable as blocked rather than claiming success.

Use the smallest shared implementation that satisfies the contract. Reuse existing subprocess, progress, cancellation, planner, and storage conventions. Do not introduce a job service, frontend framework migration, plugin backend registry, or generic transcoding framework.

Before starting, create an execution ledger, `MERGE_IMPLEMENTATION_STATUS.md`, containing each milestone's status, files changed, commands run, results, unresolved failures, and validation gaps. Update it after each milestone. This ledger is a handoff artifact, not runtime application state.

### Scope boundary

This work repairs and completes the existing merge feature across supported local-download workflows, including Telegram multi-input, bulk links, YouTube playlists, selected torrent series, and downloaded folders. It includes subtitle preservation, unattended ordering, one continuous encode when requested, failure handling, and verification. It does not authorize rewriting unrelated media players, download engines, or auto-update policy.

## 2. Required user experience

- Keep `--merge` as a switch on existing download commands. It must not consume the following source URL or become a separate command.
- `/l` is the user's first bot command; `/l1` is the second bot's configured suffix variant. Use `CMD_SUFFIX` and existing registration; never hardcode `l1` or strip arbitrary trailing digits.
- Preserve existing source forms: direct links, replies to files/links, bulk input, and existing multi-message discovery.
- For `/l1 -i 3 --merge`, resolve the intended three sources as a batch. Publish their known names and an ordering portal before starting media downloads for this command when names are already available from Telegram. Do not wait for child jobs to start sequentially.
- For playlist, torrent, archive, or folder sources whose inventory requires metadata retrieval, show one preparing/planner message promptly and populate the inventory as soon as discovered. Metadata retrieval is allowed before the inventory becomes complete.
- A planner link must be actionable as soon as it is announced. Do not announce a populated three-file plan containing only one known file if all three are already discoverable.
- Downloads continue automatically. There is no confirmation prompt after downloading, and no requirement to leave the portal open.
- Support drag ordering, touch ordering, accessible move-up/down controls, original order, natural filename sorting, season/episode sorting, and reverse order.
- Silence individual `MERGE PART READY` notifications. Staging a child is an internal success state, not an upload failure.
- One batch gets one final outcome. Do not report a three-source merge as three failed uploads or three independent successful uploads.
- If no edits are saved, use the documented default order. If edits are saved, honor the latest acknowledged order at timeline freeze.
- `-n` names the final merged artifact, not the source downloads. Preserve original episode names for chapters and the plan.
- Default output is MKV. Prefer `<playlist-or-folder-name> [Merged].mkv`; use a sensible collection fallback where no title exists.
- Provide one chapter per selected video, hard cuts, no transitions.
- Preserve the normal upload pipeline, including Telegram file-size splitting. A logical merged output may require several uploaded parts; describe this accurately.

### Default ordering

| Source | Default |
| --- | --- |
| Telegram `-i` | Resolved source-message order, independent of download completion |
| Bulk links | Supplied input order |
| YouTube playlist | Provider playlist position, including deliberate user selections |
| Torrent/folder | Recognized season/episode order where unambiguous; otherwise deterministic natural relative-path order |
| Manual portal order | Exact saved stable item-ID order |

Torrent file order is not guaranteed to be episode order. Do not treat info-hash file enumeration, filesystem enumeration, or completion order as authoritative viewing order. Episode parsing must not mistake `1080p`, codec names, release years, or checksum digits for episode numbers. Use explicit patterns first: `S04E14`, `4x14`, `Episode 14`, `EP14`. Keep unknown items stable and visibly identifiable.

For missing/private playlist entries, distinguish an intentional selection from a failed required input. An unavailable entry inside the requested selection fails the batch by default, with the affected entry named. Do not silently shorten the collection.

## 3. Quality contract and limitations

### Without `-en`

Preserve encoded video and audio content through stream copy/remux. Container timestamps, indexes, chapters, track IDs, and packet framing may legitimately change. Never claim that the complete output file is byte-identical to the inputs.

Incompatible video/audio still require explicit encoding. A successful FFmpeg exit, equal duration, or equal codec name does not by itself establish compatibility.

### With `-en <profile>`

Select one encode profile for the batch and encode one ordered timeline. Do not encode every episode separately and append those encodes. Do not require successful lossless A/V concatenation before entering the encode path: encoding must be able to normalize supported differences such as input resolution or video codec.

Video/audio stream-copy choices inside a profile still require compatibility for the streams being copied. Preserve existing SUDO and configuration restrictions on encoding.

### Subtitle preservation

Default to preserving the original subtitle format and appearance. Do not automatically convert ASS to SRT, burn subtitles into video, OCR bitmap subtitles, strip styles, or drop tracks to make a merge succeed.

ASS headers contain rendering information, including script resolution and style definitions. Keeping event text while discarding a later episode's header can change its appearance. Treating all text codecs as interchangeable is unsafe. Converting SRT upward to ASS also changes rendering choices and is not a universal preservation guarantee.

Preserving subtitle events, styles, headers, and fonts and providing one continuous selectable subtitle track are separate requirements. Prefer continuous tracks where preservation can be demonstrated. Otherwise retain separate original tracks with episode offsets.

Separate tracks mean the viewer may need to switch subtitle tracks between episodes. Do not promise automatic switching in ordinary players. Include a concise final-result note such as:

> Subtitles preserved in their original formats. Some tracks cover individual episodes; switch tracks at those chapter boundaries if needed.

No system can promise identical appearance on every player or repair fonts that were already missing from the source. State guarantees in terms of preserved content and the tested renderer/player matrix.

## 4. Current repository map and audit findings

Recheck these anchors before implementation. Line numbers are intentionally omitted because they drift.

| Existing path | Relevant responsibility / symbols |
| --- | --- |
| `bot/modules/mirror_leech.py` | Main download command parsing; `--merge`, multi-source discovery, shared folder setup, seeding/cloud-to-cloud restrictions |
| `bot/modules/ytdlp.py` | yt-dlp command parsing and playlist candidate publication |
| `bot/helper/ext_utils/bot_utils.py` | Switch parser; `merge_plan_url`, `merge_plan_buttons`; configured command suffix handling |
| `bot/helper/telegram_helper/bot_commands.py` | Existing command registration and aliases |
| `bot/helper/common.py` | `prepare_merge_plan`, `set_merge_plan_candidates`, `update_merge_plan_status`, `proceed_merge`, `proceed_encode`, multi-task scheduling |
| `bot/helper/listeners/task_listener.py` | `_stage_merge_source_files`, `on_download_complete`, `_handle_encode_pipeline`, staging/error cleanup and final upload |
| `bot/helper/ext_utils/media_utils.py` | `_probe_media_file`, `_merge_stream_signature`, `check_merge_compatibility`, `FFMpeg.merge_video_files`, encoding and validation helpers |
| `bot/helper/ext_utils/multi_leech_utils.py` | Multi-leech summary scope and aggregation |
| `bot/helper/mirror_leech_utils/download_utils/yt_dlp_download.py` | Playlist filename prefixes, error behavior, media output paths |
| `bot/helper/mirror_leech_utils/download_utils/qbit_download.py` | Torrent inventory publication |
| `web/merge_plan_store.py` | JSON plan store, cross-process locking, revisions, source registration, final ordering, stale cleanup |
| `web/wserver.py` | `_merge_plan_auth`, `/app/merge-plan`, `/api/merge-plan/{plan_id}` |
| `web/templates/merge_planner.html` | Existing portal markup |
| `web/static/js/merge-planner.js` | Sorting, drag/touch ordering, saving, polling |
| `web/static/css/merge-planner.css` | Existing portal styling |
| `bot/helper/ext_utils/help_messages.py`, `README.md` | Command help and merge user guide |
| `Dockerfile`, `Dockerfile.base`, `requirements.txt`, `pyproject.toml` | Runtime dependencies, image assembly, test/lint settings |

### Observed issues that the implementation must resolve

1. The inspected working tree contains an unfinished `media_utils.py` diff with `_merge_text_subtitle_normalization_tracks` and `_normalize_merge_text_subtitles`. It canonicalizes text subtitle codec names and converts mismatching tracks to SRT while remuxing whole inputs. Audit this exact diff before replacing it. Preserve unrelated edits; do not reset the file.
2. `_merge_stream_signature` also ignores text-subtitle extradata differences. A replacement must distinguish harmless metadata from rendering-critical ASS/WebVTT header differences, or route those tracks through the independent subtitle path. Do not retain this bypass as evidence of safe direct append.
3. `proceed_merge` currently checks compatibility before applying the final saved portal order. Error positions and reference-track selection can therefore refer to a different order. Inventory/probe first, freeze ordering, then construct and validate the ordered plan.
4. If final planner coverage fails, `proceed_merge` currently logs a warning and falls back to natural order. A saved order must never be silently abandoned. Reconcile by stable identity or fail clearly while retaining sources.
5. The listener currently calls `proceed_merge` before `_handle_encode_pipeline`; this makes `-en` depend on lossless compatibility first. Split copy and encode execution after shared planning.
6. `proceed_merge` currently marks the plan completed and removes the source directory before subsequent encoding and upload finish. Completion state and cleanup must move to the appropriate final lifecycle points.
7. `on_download_complete` aggregates through `same_dir` and stages children through `on_upload_error(..., merge_staged=True)`. Trace all side effects before changing it; a staging callback must not increment failed counts or remove another child's files.
8. `web/merge_plan_store.py` has one general revision, positional identity fallback, a stale lock age, and six-hour file-age cleanup. Audit these for late child registration, saved-order loss, active long jobs, and concurrent bot/web processes.
9. Planner item keys are currently case-folded before hashing. Case-distinct paths on Linux and duplicate playlist occurrences must remain distinct.
10. External subtitle files currently stop merging wholesale. Add safe association and processing as described below; retain a clear error for unresolved association instead of guessing.
11. The current browser polls every three seconds and rebuilds list rows. Saving/polling/list expansion must not lose unsaved user intent or keyboard focus.
12. Existing tests include assertions about exact source strings. Update obsolete assertions to meaningful behavior checks when execution flow changes; do not make the implementation preserve a bug just to satisfy a string assertion.

These are static findings. They do not establish that every reported production failure still occurs in the current deployment.

## 5. Runtime design

Use one batch owner and one immutable execution plan. Extend existing shared state and plan storage rather than creating a separate orchestration service. Small data classes or typed records are sufficient where they improve clarity.

### Minimum internal records

| Record | Required information |
| --- | --- |
| Batch | Opaque batch ID, owner/bot namespace, intended sources, enumeration-complete flag, source states, mode/profile snapshot, plan revision, lifecycle state, terminal outcome |
| Source | Stable occurrence ID, provider identity, original position, discovery/download state, candidate item IDs; occurrence ID distinguishes repeated use of the same URL/video |
| Media item | Stable ID, source ID, original display name, safe local path, original index, probe result, size/fingerprint, selected stream IDs |
| Timeline entry | Item ID, sequence position, source presentation origin, segment span, output start/end, A/V mapping, subtitle mapping |
| Subtitle decision | Source track identities, logical group, strategy, format, rendering-header compatibility, offsets, expected event coverage, attachment dependencies |
| Execution result | Final artifact path, warnings, validation evidence, failure category if any; never overload an error result to mean a successful staged child |

Keep internal paths, URLs, credentials, FFmpeg arguments and raw subprocess diagnostics out of public planner JSON. Public data should contain safe labels, IDs, counts, readiness, state, saved order revision, and user-actionable explanations.

### Suggested code boundaries

Keep batch admission, staging and upload ownership in the existing listener/common flow. Extend `web/merge_plan_store.py` for atomic freeze and revision handling. Extract the new pure timeline/subtitle decision logic into at most a small merge-specific module if keeping it in `media_utils.py` would obscure the existing helpers.

The implementation needs the following operations; these are proposed responsibilities, not functions already present in the repository:

```text
reconcile_and_freeze(batch_id, discovered_items, expected_inventory_revision)
    -> immutable ordered item records, or an explicit reconciliation error

build_execution_plan(ordered_items, probes, mode, profile)
    -> timeline entries, A/V mappings, subtitle decisions, attachment decisions

execute_merge(plan, listener)
    -> candidate artifact and expected-output manifest

validate_merge(candidate, expected_manifest)
    -> validation evidence or a specific failure
```

Keep planning pure where practical so tests can inspect strategies and offsets without starting the bot. Keep subprocess execution asynchronous under existing progress/cancellation ownership. Do not expose raw local paths through the plan-store API merely to reuse these internal records.

The expected-output manifest must identify each source contribution, output track, time interval, codec, subtitle strategy, chapter, and attachment. Output validation uses this manifest rather than assuming the final track count equals the first input's count.

### Lifecycle

```text
collecting -> downloading -> planning -> processing -> validating -> uploading -> completed
      \            \            \           \             \           \
       +------------+------------+-----------+-------------+-----------> failed / cancelled
```

The states are conceptual; adapt existing names where possible and document the mapping. An optional extraction step occurs before planning. `processing` can report preparing subtitles, merging, encoding, and assembling without creating independent jobs.

- Enumeration complete is separate from downloads complete. A fast first download must not trigger processing while two requested children have not registered.
- Admit one finalizer atomically. Duplicate callbacks and concurrent final children must not start two encodes/uploads.
- Freeze the accepted item order and selected file set atomically immediately before planning/processing. A concurrent save either wins and is included, or receives a conflict/locked response. Never acknowledge a save that processing does not use.
- Terminal states cannot be overwritten by a delayed child callback.
- A failed required child terminates the collection once, cancels remaining work where supported, and preserves accurate per-source reasons internally.
- Cancellation propagates to downloads, queued work, the active subprocess, and upload. Reap subprocesses before cleanup and do not hold global locks while waiting.

### Restart behavior

Persist enough state to mark interrupted jobs accurately and retain their artifacts for recovery. Do not blindly resume a previously uploading job and risk duplicate delivery. Automatic crash-resume of downloads is out of scope unless existing engine semantics support it; marking interrupted work and making its local data recoverable is required.

## 6. Inventory, staging and source identity

1. Resolve the intended input collection using existing command semantics. For implicit recent-message discovery, respect chat/thread and requester scope and bounded search; do not collect unrelated users' media.
2. Create a batch and register all immediately discoverable source occurrences before scheduling child downloads. Preserve duplicate filenames and repeated URLs as distinct occurrences.
3. Use source-specific directories under the batch's owned working directory. Binding a placeholder to a child job changes its metadata, not its position in a saved order.
4. Expand a folder/playlist placeholder into stable child IDs. If existing files remain the same, readiness/name updates must not reorder them. If a source expands, insert its newly discovered children at its reserved position and preserve existing manual relative order.
5. Identity must survive file moves and display-name changes. Do not infer identity solely from current filename, case-folded path, download completion order, or a coincidentally equal item count.
6. Probe selected readable media once and cache the result for the unchanged file. Use size/mtime or another verified fingerprint for invalidation. Thumbnail directories, attachments and sidecars must not become playable videos.
7. Run existing extraction/join behavior before final inventory reconciliation where it changes the selected media. Reconcile expanded files explicitly; do not silently remap old ordinal IDs onto different files.
8. Require at least two selected playable videos. Errors must reference the final ordered display name/position, not an anonymous stream hash alone.

## 7. Timeline mathematics and A/V compatibility

Use rational arithmetic or integer timestamps with explicit time bases. Do not repeatedly accumulate binary floating-point durations from rounded display values.

For input `i`, establish source presentation origin `O_i` and selected A/V presentation end `E_i` from trustworthy container/stream information, escalating to packet inspection when required. Define the segment span `D_i = E_i - O_i`, and output start `T_i = sum(D_j for j < i)`.

Map every preserved presentation timestamp through:

```text
output_pts = source_pts - O_i + T_i
```

Apply one common shift per input to preserve internal audio/video/subtitle offsets. Never reset each track independently to its own first packet. Subtitle-only cues must not independently determine where the next video's picture begins.

Account for codec delay, audio priming/discard padding, nonzero starts, VFR, B-frame presentation order, and timestamp quantization. Use a conservative segment-end policy based on the selected A/V span and test boundary audio gaps explicitly. If a subtitle cue extends past its segment end, diagnose the condition; do not silently clip text or allow unexplained cross-episode overlap.

For copy mode, retain checks on codec configuration, dimensions, pixel format, color/HDR properties, channel layout, sample rate, and decoding initialization data. Compare semantic values rather than raw formatting where justified. The reported `24000/1001` and `2997/125` values differ slightly; nominal-rate tolerance needs packet/cadence evidence and must not mask actual 24-vs-30 FPS incompatibility. Container time bases may be rescaled by a remuxer when demonstrated safe; they are not an unconditional reason to transcode.

Audio track matching must preserve language/purpose and every selected track. Missing or incompatible audio in copy mode produces a clear error; silently choosing one track or synthesizing audio is not copy mode. Do not broaden support to arbitrary video-codec changes inside one copied track.

## 8. Independent subtitle pipeline

### 8.1 Group tracks conservatively

Build candidate logical groups using normalized language tags, full-dialogue/signs/forced/SDH roles, track title, explicit source selections, and unambiguous correspondence. Do not identify an English signs track with English full dialogue because both have language `eng`. Avoid fuzzy matching that hides uncertainty.

If correspondence is ambiguous, preserve the tracks separately with meaningful episode and source-track labels. An episode with no subtitle in a logical group contributes an empty interval; it does not require fabricating dialogue or dropping other episodes' subtitles.

### 8.2 Strategies, in preference order

| Strategy | Eligibility | Required behavior |
| --- | --- | --- |
| Direct append | Same codec, compatible rendering headers and meaning | Preserve events and shift timestamps; collect dependencies |
| ASS style-aware combine | ASS inputs with compatible global rendering settings, even if styles differ | Merge style tables safely and remap references; preserve all event semantics |
| Separate original tracks | Mixed codecs, unsupported header differences, ambiguous grouping, unsupported safe append | Keep original codec/header/event content and shift each source track to its episode interval |

Do not normalize every subtitle to a common text codec. Mixed ASS/SRT uses separate originals by default. Exact-format preservation takes precedence over providing one continuous track.

### 8.3 ASS combining algorithm

Prefer retaining Matroska event timestamp precision and event payloads in a subtitle-only container. A `.ass` text round trip stores centisecond timestamps and can lose precision that existed in the container. If an export/import path is used, measure and document its rounding, and use separate originals whenever the preservation criterion is not met.

1. Parse the actual format declarations in header/style/event sections. Do not assume one fixed field layout, split dialogue text on every comma, or rebuild unsupported tags through a lossy generic subtitle library.
2. Compare rendering-relevant global settings, including `PlayResX/Y`, layout resolution when present, wrapping, collision behavior, scaled border/shadow, color matrix, and other renderer-affecting fields. An unknown differing global field is a reason for conservative fallback until understood.
3. Ignore demonstrably non-rendering descriptive differences such as a script title only after structured parsing. A different extradata hash alone neither proves nor disproves compatibility.
4. Allocate deterministic unique style identifiers per source where definitions conflict. Preserve all style values. Renaming `Default` to an episode-qualified name must change both the event's Style field and named reset references (`\rStyle`) inside valid override blocks.
5. Preserve bare `\r` semantics: it resets to that event's assigned style. Do not search-and-replace the word `Default` across arbitrary dialogue text.
6. Preserve layer, actor, margins, effect, text, drawings, clip/move/transform tags, karaoke timing and ordering. Shift event start/end together. Relative karaoke/animation times remain relative to the event; do not shift them again.
7. Preserve event ordering/read order deterministically, including overlapping signs and dialogue. Unknown constructs must round-trip untouched or trigger the separate-original strategy.
8. If events from adjacent sources overlap and combining changes collision behavior, use separate originals or diagnose the invalid boundary; do not claim identical rendering from style preservation alone.
9. Validate event count, timestamps, style references and representative rendered output before accepting this strategy.

Different script resolutions are not solved by renaming styles. Coordinate resampling changes more than font size and is not part of the default preservation path. SSA, WebVTT and other formats may use direct append only when tested; otherwise keep original tracks.

### 8.4 SRT and bitmap handling

Compatible SRT tracks can form one continuous track with shifted timestamps, preserving text, line breaks and supported markup. Do not route them through ASS just for convenience.

PGS, VobSub and DVB subtitles stay bitmap subtitles. Prefer tested packet-preserving remux/append, including initialization/palette/state data, otherwise separate original tracks. No OCR. Recognize VobSub `.idx`/`.sub` as a pair; a `.sub` extension alone is ambiguous and must be inspected.

### 8.5 External subtitles

Associate sidecars through provider metadata or exact normalized video basename plus language/role suffix, scoped to the source directory. Use one unambiguous match. Do not apply a subtitle to every episode because the language matches.

For ambiguous or unmatched sidecars, retain them and report the association problem; do not silently discard them. Selected associated sidecars enter the same subtitle timeline and validation pipeline as embedded tracks. Fonts shipped alongside a source require the same dependency checks as embedded fonts.

### 8.6 Original-track preservation and player behavior

Store an episode track with its original header and codec, and an offset `T_i - O_i`. Label it, for example, `English - Episode 03 - Original SRT`. Preserve forced/accessibility semantics where meaningful; avoid marking every episode track default. Select at most one default within a logical language/role policy.

Track offsets do not force a player to select a different subtitle track later. Show separate-track coverage in the planner and final result. Do not represent a sparse original track as a continuous full-series subtitle.

## 9. Attachments and fonts

- Collect dependencies from all selected sources. Deduplicate identical attachment bytes by a strong content hash, preserving meaningful metadata.
- Different files with the same attachment filename need safe unique container filenames where supported. Keep original associations internally.
- Font identity is also inside the font file. Two different font binaries with the same internal family/style or PostScript names may render ambiguously when both are attached. Renaming `.ttf` filenames does not fix that.
- Detect such internal-name conflicts using an existing capable dependency, or justify a narrowly scoped font parser dependency. Prefer failing an affected exact-preservation job clearly over silently substituting a font. A universal font-renaming/rewrite engine is out of scope.
- Separate subtitle tracks still share the MKV's font environment; they do not automatically solve font conflicts.
- Preserve existing source deficiencies honestly: warn if a referenced font is absent, but do not claim that bundling unrelated system fonts recreates the original.
- Font/attachment inspection must be bounded and remain inside the owned workspace. Treat font data, names and metadata as untrusted.

## 10. Processing backend and encode integration

### Recommended concrete backend boundary

Use the existing FFmpeg stack for A/V copy/encode and use MKVToolNix for final Matroska assembly where its packet/header handling passes the required fixtures. Add only the command-line tools, `mkvmerge` and `mkvextract`; a desktop GUI dependency is unnecessary.

Before integrating the backend, run a bounded synthetic proof for subtitle header/payload preservation, offsets, missing subtitle intervals, attachments, and repeated track types. Record the tested versions and identification output. `mkvmerge` does not fix incompatible codecs by itself. Explicitly map identified tracks; never assume ffprobe stream indexes equal mkvmerge track IDs.

If the MKVToolNix proof fails for a format, retain a verified FFmpeg preservation path if available, otherwise report the unsupported format explicitly. Do not force conversion. If the required binary is missing on a host, diagnose it before downloading where possible. Never silently change subtitle strategy because a dependency is unavailable.

Adding a package only to `Dockerfile.base` does not update already published `nbots/amaterasu:v1` images. Ensure the image actually used by `Dockerfile` contains the tools, using the project's supported image build/release mechanism. Verify Python 3.11 and existing pinned FFmpeg/AV1/WZGram dependencies; do not upgrade the multimedia stack as a side effect.

### Copy path

```text
frozen ordered sources
  -> A/V compatibility and subtitle plan
  -> concatenate selected compatible A/V into a temporary timeline
  -> prepare small subtitle-only artifacts when needed
  -> mux A/V + subtitle outputs + all attachments + chapters
  -> validate final MKV -> atomic publish -> upload
```

An initial implementation may use one A/V intermediate plus final assembly. Measure that I/O explicitly. Optimize to fewer passes only when preservation tests remain valid; do not remux every full episode solely to convert a subtitle stream.

Do not feed incompatible full multitrack inputs into FFmpeg's concat demuxer and assume `-map` excluding subtitles fixes its input-level stream matching. Mapping controls the output selection; it is not proof that the concat demuxer can correctly match the source streams. In M0, first prove selected-track A/V appending with mkvmerge using explicit track selection and append mappings, excluding subtitles and attachments from the A/V intermediate. If that passes, use it for this intermediate. Otherwise use verified A/V-only intermediates where necessary and include their extra I/O/disk cost in the estimate. Correctness takes precedence over a one-pass claim.

During final assembly, add subtitle tracks with their calculated offsets; do not append the entire source video again. Explicitly select only intended tracks, metadata and attachments from each input. The assembler must not duplicate A/V, inject a source's chapters unintentionally, or normalize away the offset of a sparse subtitle track. Prove this using packet timestamps from a subtitle that begins in Episode 03.

### Encode path

```text
frozen ordered sources + one authorized profile
  -> decode and normalize selected A/V inputs as required
  -> concatenate normalized frames/samples into one timeline
  -> one continuous encode
  -> mux preserved subtitles, attachments and chapters
  -> validate final MKV -> atomic publish -> upload
```

- Bypass lossless video compatibility requirements for video that will be encoded. Determine common output dimensions, aspect handling, pixel format and frame-rate policy from the existing profile machinery.
- Preserve aspect ratio using a documented scale/pad policy. Do not silently stretch, crop, flatten HDR or drop audio tracks. Unsupported HDR/color conversions require a clear profile-specific error.
- Normalize audio layout/rate only when the profile encodes that audio. Missing audio intervals may be filled with correctly timed silence only in an explicitly defined encoded output track; state the policy in the profile/result.
- Multiple audio languages require independent logical output mappings. Do not let FFmpeg's default stream selection keep only the first audio stream.
- For profile-requested subtitle exclusion or burn-in, preserve existing explicit semantics and display the selected policy before processing. In an unattended merge, do not discover a new encode-profile choice after downloading.
- If burn-in is supported, apply each source's subtitles/fonts in its original timing and coordinate context before the joined frames enter the encoder. Retaining a separate original subtitle track does not by itself make burn-in safe. Reject unsupported combinations before encoding rather than silently ignoring the profile.
- For ordinary subtitle-preserving profiles, mux the independently prepared subtitles after A/V encoding so the encoder cannot strip or flatten them.
- Keep MKV as the merge output container; profile output-codec settings still apply. Container conflicts with an existing profile must be detected explicitly.
- Prevent the listener from running `_handle_encode_pipeline` a second time after the new merge execution path already encoded the timeline. Non-merge encoding must retain its current behavior.

### Subprocess requirements

Use argument arrays and trusted executable configuration. No shell interpolation of names, URLs, metadata, or subtitle text. Support Unicode, quotes, spaces and leading hyphens through correct tool argument handling and option files where appropriate. Use a Windows-capable test invocation; production's Linux `taskset` wrapper must not be assumed present locally.

Drain stderr while monitoring progress so a full pipe cannot deadlock processing. Bound diagnostic storage and redact source credentials/absolute private paths from user-facing errors. Apply cancellation/timeouts to subprocess trees and wait for exit before deleting artifacts.

For `mkvmerge`, exit 1 indicates warnings rather than an unconditional fatal failure. Inspect/classify warnings and run output validation; do not ignore all warnings or mark every warning as success. Exit 2 is an error.

## 11. Planner correctness, security and UI improvements

Reuse the existing HTML/CSS/JS portal and signed-token/PIN behavior. No redesign is required.

### Ordering and save semantics

- Maintain stable item IDs. A status change must not make a save stale unnecessarily; separate order/inventory revisions from progress revisions, or implement equivalent conflict checks.
- Require an order revision on mutations and validate that the payload contains every current selected ID exactly once. Reject duplicate, unknown, cross-plan and missing IDs.
- Keep client-local unsaved order separate from the last acknowledged server order. Only show `Saved` after the server accepts that order.
- For HTTP 409, fetch the latest list and preserve/reconcile the user's intent when possible; never overwrite a newer remote order blindly. Show a concise conflict notice if reconciliation is ambiguous.
- Lock immediately before planning, not at first download completion and not after execution has started. Reject late saves with the frozen order visible.
- Keep the last saved order if the tab closes or network disconnects. Pending unsaved edits must be labeled as such; do not promise browser-close delivery.
- List expansion must preserve existing interleaved user order, not pull every item belonging to a source back into one block.
- Use deterministic sort keys consistent with backend behavior. Do not allow browser locale to change the actual default timeline.

### Presentation

Show known versus unresolved counts, readiness, current order, eventual duration, copy/encode mode, and a short subtitle strategy summary once probing is complete. Duration and subtitle compatibility may legitimately be unknown before download; display that honestly.

Keep one Telegram planner/status message per collection. Portal failure with no saved custom order may fall back to an explicit known default and continue; once a custom order was accepted, inability to recover it must not silently switch order. Missing public web configuration should produce one clear notice, not a dead link or endless wait.

Preserve focus during polling, avoid rebuilding unchanged rows, and support keyboard and touch interaction. Pause/back off polling when hidden, reconnect safely, and stop polling terminal plans. Add autoscroll during long drags if necessary, using existing primitives. Keep all names rendered as text, never HTML.

### Authorization and storage

The current portal uses a plan-scoped signed bearer token/PIN. Preserve its scope and existing owner checks for Telegram callbacks. Possession of a forwarded bearer link is not the same as an authenticated owner login; do not describe it as owner-only unless that identity is actually verified.

Keep no-store responses, token-attempt limits, safe ID validation, and path-free public JSON. Avoid token leakage through access logs, referers and third-party resources; use an appropriate referrer policy. Never add a filesystem path field to the reorder API. Planner mutation cannot access another bot's batch when deployments share a volume; namespace state and secrets appropriately.

Use atomic persistence and short cross-process critical sections. No media work, network waits, or long blocking disk scans inside plan locks. A stale lock must not be stolen solely because a legitimate operation exceeded an arbitrary age; use a supported process/lease strategy with ownership-aware release. A releasing process must not delete a lock now owned by another process.

Age-based cleanup must exclude active jobs and live locks. Refresh active leases as needed, expire terminal plans under a bounded retention policy, and handle interrupted jobs explicitly. A six-hour download must not disappear because a new plan triggers cleanup.

## 12. Disk space, cleanup and output ownership

Every source and temporary artifact has a batch owner. Resolve and verify paths remain inside the intended working directory before recursive cleanup. Do not follow symlinks into another job or delete source files still used for seeding.

Estimate peak additional space for the chosen execution path, including downloaded inputs still arriving, A/V intermediates, subtitle files, encoded output, final mux, and upload split parts. Already downloaded bytes occupy disk; do not incorrectly count them again as future allocation. Add a measured reserve and recheck at major allocation boundaries. Encoded size is an estimate, not a guarantee from the sum of source sizes.

- Keep source downloads until the final artifact has passed all required merge/encode validation.
- Preserve a validated artifact through upload retries. Cleanup sources after validation when ownership permits; keep them longer if the job's recovery policy requires rebuilding.
- On processing failure, retain sources for a documented bounded recovery period and remove partial outputs only after subprocesses exit. Do not retain failed jobs indefinitely.
- Write the candidate final file to a unique task-owned temporary path on the destination filesystem, validate it, then rename atomically to its allocated final path.
- Allocate collision-safe internal output paths. A user-visible name such as `Combined.mkv` must not overwrite an unrelated existing file or another concurrent job's output.
- Track completed processing separately from completed upload. Final success is emitted only after the upload destination reports success.
- Keep all runtime thumbnails, manifests, subtitles, fonts and temporary media under designated runtime/download directories. Do not solve repository pollution by ignoring every `.jpg` or every untracked file globally. Audit merge-touched download output options, including yt-dlp thumbnails, and leave unrelated auto-update behavior alone.

## 13. Verification and acceptance evidence

Start with baseline results from the actual checkout. Historical test counts and earlier WZGram/Windows failures are not exemptions: reproduce and classify failures in the current environment.

### Synthetic media fixtures

Create tiny deterministic media locally, with visible episode labels, known frame cadence, audio tones and known subtitle timestamps. Use task-owned temporary directories. Keep fixture generation and tool versions reproducible; avoid committing large binary fixtures when a generator suffices.

| Test case | Required evidence |
| --- | --- |
| Three compatible A/V inputs | Final ordered picture/audio, three chapters, expected duration, no A/V encoding in copy mode |
| ASS + ASS + SRT | Merge succeeds where A/V is compatible; original formats/styles retained; separate-track coverage reported |
| Same ASS settings, conflicting `Default` styles | Combined track preserves each episode's font/color/position and named/bare resets |
| Different ASS script resolution/global settings | Separate-original strategy chosen; no coordinate resampling or header loss |
| Karaoke, signs, drawings, overlapping events | Event content/order preserved and rendered samples agree at corresponding times |
| Missing episode subtitle and differing track counts | All existing selected subtitles retained with correct gaps; no fabricated text |
| Two English tracks with different roles | Signs/full dialogue remain distinct |
| SRT markup, Unicode, non-Latin dialogue | Text/markup/timestamps survive; no encoding corruption |
| PGS/VobSub or mixed text/bitmap | Supported original formats retained; unsupported handling explicitly diagnosed |
| Identical attachments and conflicting font names | Identical bytes deduplicated; unresolved internal font-name conflict detected |
| Nonzero starts, VFR, AAC delay, B-frames | Per-source A/V/subtitle sync and boundary timing verified |
| `--merge -en` with differing video codecs/resolutions | One continuous encode through supported profile normalization; no copy-precheck rejection or second encode |
| Copy audio requested in an encode profile | Copied tracks still checked; no silent re-encoding |
| Cancellation, disk exhaustion, invalid final output | No upload of partial/invalid media; owned cleanup and retained recoverable inputs |

For payload preservation, compare demuxed data or normalized codec representations, not whole-file hashes. Packet hashes are appropriate only where the container/bitstream mapping leaves packet representation unchanged. Necessary framing conversions must be documented and validated with decoded-content checks. Never dismiss an unexplained mismatch as normal remux behavior.

For subtitles, compare event count and content per source track, transformed timestamps with tolerance bounded by the source/destination time-base precision, headers/styles, language/role metadata, and font attachment hashes. A few video decode samples do not validate subtitle preservation.

Render representative ASS events with the same libass build, fonts, output dimensions, and rendering settings before/after, including signs, style resets and karaoke transitions. Compare at matching source/output times and inspect differences. Use separate-original output when a supported combine operation cannot meet the preservation criterion.

Check A/V continuity at every source boundary on small fixtures, including decoded samples on both sides. In production, use inexpensive probes plus bounded boundary checks appropriate to size. Duration approximately equal to the input sum remains necessary but insufficient.

### Workflow and concurrency matrix

- `/l -i 3 --merge` and `/l1 -i 3 --merge` through configured command registration.
- Reply-based source selection and the existing no-reply recent-source form; unrelated messages do not enter the batch.
- `--merge` before and after a URL; `-n`, `-i`, and `-en` parse independently.
- Delayed child registration; first file finishes before all children start.
- Duplicate filenames, repeated playlist items, and case-distinct Linux paths.
- Last two downloads finish together: one finalizer and one logical upload.
- Child failure, selected unavailable playlist item, cancelled collection, expired plan.
- Save order while metadata expands, while download readiness updates, and at freeze time.
- Cross-source interleaving survives readiness and final reconciliation.
- Long-running active plan survives stale cleanup and server workers see consistent state.
- Portal never opened; portal closed; network failure during save; invalid PIN; stale revision; locked order.
- Desktop drag, touch drag, keyboard move, focus retention and reduced-motion behavior.
- Non-merge multi-leech, mirror, yt-dlp, torrent selection, and ordinary encoding remain intact.
- Seeding and cloud-to-cloud merge restrictions remain explicit unless separately implemented and tested.
- Final upload failure is distinct from download/merge failure; split uploads still count as one logical merge.

### Existing test entry points

- `tests/test_encoding_playback_safety.py`
- `tests/test_hyperdl_routing.py`
- `tests/test_multi_leech_summary.py`
- `tests/test_multimedia_stack.py`
- `tests/test_ytdlp_thumbnail_recovery.py`
- `tests/test_update_safety.py` if runtime artifact placement changes touch update-related assumptions

Add focused behavioral tests in existing modules or small dedicated merge/subtitle test modules. Do not replace runtime verification with assertions that a function name appears in source. Browser tests must exercise actual save/conflict/freeze behavior, not only static HTML selectors.

### Commands and execution environment

Run from the repository root with its configured environment. These are initial commands for currently existing files; add the new test paths after creating them.

```powershell
git status --short
git diff --check
python -m pytest tests/test_encoding_playback_safety.py tests/test_hyperdl_routing.py tests/test_multi_leech_summary.py tests/test_multimedia_stack.py tests/test_ytdlp_thumbnail_recovery.py -q -p no:cacheprovider --basetemp .runtime/merge-guide-focused-run-01
python -m compileall -q bot/helper/ext_utils/media_utils.py bot/helper/common.py bot/helper/listeners/task_listener.py web/merge_plan_store.py web/wserver.py
node --check web/static/js/merge-planner.js
python -m pytest -q -p no:cacheprovider --basetemp .runtime/merge-guide-full-run-01
```

Use a fresh task-owned `--basetemp` per run; pytest may clear a reused base directory. If temporary-directory permissions fail, select a writable directory inside the workspace; do not change broad system permissions. Run scoped Ruff checks for changed Python files using the repository's available lint tooling; distinguish introduced findings from unrelated pre-existing ones. Do not format the entire repository to clean up a targeted fix.

Run real-media tests against the Linux runtime image with its pinned FFmpeg build and added MKVToolNix version. Windows tests alone do not validate Linux affinity wrappers, process cancellation, file locking, image dependencies, or live Telegram delivery. If Docker or service credentials are unavailable, complete all independent local work and record those exact remaining checks as blocked.

## 14. Milestones and completion gates

| Milestone | Work | Gate before marking complete |
| --- | --- | --- |
| M0: Baseline and backend proof | Inspect dirty diff/callers; baseline tests; tiny remux/offset/header proof; dependency availability | Reproducible evidence and clear supported backend path |
| M1: Batch and order integrity | Stable identities, discovery-complete barrier, one finalizer, atomic order freeze | Delayed/duplicate callback and save-race tests pass |
| M2: Independent preservation path | Separate A/V checks; preserve original subtitles with offsets; attachments; eliminate blanket conversion | ASS/ASS/SRT and differing subtitle counts succeed with validated originals |
| M3: Safe continuous subtitles | SRT combination; bounded ASS style/header merge; safe fallback; external subtitle association | Semantic and rendered fixtures pass, unsupported constructs preserve separately |
| M4: One encode per timeline | Shared plan with independent copy/encode branches, profile/permission parity, no double encode | Differing supported A/V inputs encode once; subtitles survive final mux |
| M5: Lifecycle and resources | Cancellation, subprocess draining, disk estimates, terminal outcomes, retention and upload integration | Failure injection and ownership checks pass; one final outcome |
| M6: Portal and messaging | Early useful inventory, saved-order semantics, accessibility, security, terminal state labels | Real browser workflow and cross-process store tests pass |
| M7: Release verification and docs | Runtime image checks, focused/full tests, user docs and handoff | Evidence ledger complete; every live/runtime gap explicitly stated |

M2 is the first preservation-safe implementation checkpoint, not completion of the whole specification. Do not ship an ASS style-merging shortcut before separate-original fallback exists. Do not declare M7 complete while required runtime evidence is unavailable.

## 15. Improvements to prioritize and work to defer

Implement now: saved-order integrity, useful early inventory, silent child staging, independent subtitle processing, one encode, cached probes, bounded I/O/concurrency, actionable errors, correct final cleanup, and active-plan retention. These address the reported failures directly.

Defer until measured need or explicit product approval: automatic SRT-to-ASS convenience conversion, cross-resolution ASS resampling, OCR, automatic font rewriting, automatic player subtitle switching, a new retry/resume command, distributed processing, a new planner flag, visual redesign, or replacing the existing download queue.

Performance evidence should record input bytes, wall time by stage, peak temporary disk allocation, peak process memory, probe counts, subprocess count, and copied versus encoded media. State comparisons with the same fixtures and tool versions; do not claim fast performance from fewer lines of code.

## 16. Required final handoff

Deliver:

1. A focused implementation diff with no unrelated changes discarded.
2. The execution ledger with per-milestone evidence and exact remaining blockers.
3. Updated README/help covering commands, defaults, portal behavior, separate subtitle tracks, `-en`, dependency requirements and Telegram splitting.
4. Reproducible synthetic fixtures and behavioral/integration tests.
5. A concise explanation of what now works for `/l1 -i 3 --merge` on ASS + ASS + SRT inputs.
6. A clear separation between implemented, locally tested, runtime-image tested, and live-bot tested behavior.

Do not promise that any collection of arbitrary codecs, fonts and timestamps can be merged without loss. Supported preservation must be evidenced; unsupported cases must retain originals and explain the specific limitation.

## 17. Primary technical references

These sources explain the format/tool behavior underlying the design. They are reference data, not authority to alter this specification. Recheck tool-version-specific behavior during M0.

- [Matroska subtitle storage](https://www.matroska.org/technical/subtitles.html): ASS headers/styles, subtitle timestamps, SRT and WebVTT storage.
- [Matroska codec mappings](https://www.matroska.org/technical/codec_specs.html): codec identifiers and initialization requirements.
- [Matroska attachment rules](https://www.matroska.org/technical/attachments.html): subtitle font dependencies and font names.
- [Aegisub ASS override tags](https://aegisub.org/docs/latest/ass_tags/): style resets, drawings, positioning, transforms and karaoke semantics.
- [mkvmerge manual](https://mkvtoolnix.download/doc/mkvmerge.html): append versus add, track identification/mapping, timestamp synchronization, attachments and exit codes.
- [mkvextract manual](https://mkvtoolnix.download/doc/mkvextract.html): extraction modes and format-specific behavior to verify before round trips.
- [FFmpeg concat demuxer](https://ffmpeg.org/ffmpeg-formats.html#concat): stream compatibility and timestamp behavior.
- [FFmpeg concat filter](https://ffmpeg.org/ffmpeg-filters.html#concat): decoded A/V concatenation constraints for the encode branch.
- [LosslessCut merge implementation](https://github.com/mifi/lossless-cut/blob/master/src/renderer/src/hooks/useFfmpegOperations.ts): FFmpeg-backed concat workflow; not a solution for arbitrary subtitle incompatibility.
- [LosslessCut merge troubleshooting](https://github.com/mifi/lossless-cut/blob/master/docs/troubleshooting.md): compatibility limitations and misleading successful output.
