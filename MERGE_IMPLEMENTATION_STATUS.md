# MERGE_IMPLEMENTATION_STATUS.md

## Execution Ledger

### M0: Baseline and backend proof
- **Status**: Complete for the local merge scope; production runtime certification remains outside this host.
- **Files Changed**: This ledger only. Existing `Dockerfile.base` MKVToolNix addition was present before this run and was preserved.
- **Commands Run**: `git status --short`; `git diff --check`; focused `python -m pytest` on the five guide-listed modules (fresh `--basetemp` under `%TEMP%`); `ffmpeg -version`; `mkvmerge --version`; `mkvextract --version`; synthetic FFmpeg source generation, `mkvmerge` A/V append and subtitle-only mux, `ffprobe` stream/packet inspection.
- **Results**: HEAD `f0903cc`; 104 focused tests passed with a fresh Windows temp directory. FFmpeg 8.1.2 and MKVToolNix 100.0 are installed locally (the latter at `C:\Program Files\MKVToolNix`, outside `PATH`). Three 2-second synthetic H.264/AAC files with ASS, differently styled ASS, and SRT produced one A/V track pair plus three original subtitle tracks. Subtitle packet PTS moved from 0.5s to 0.5s, 2.5s, and 4.5s; final duration 6.079s. The two ASS extradata hashes remain distinct. The synthetic inputs are in `.runtime/merge-proof/`.
- **Unresolved Failures**: The first focused run using a workspace `.runtime` pytest base had 99 passes and five Windows temporary-directory cleanup errors; rerunning with a fresh `%TEMP%` base yielded 104 passes.
- **Validation Gaps**: Multiple audio tracks, packet-level A/V boundaries, Linux/runtime-image execution, and live bot behavior remain unproven. Docker is unavailable on this host; `mkvmerge` and `mkvextract` are absent from `PATH` but found at their fixed Windows install path.

### M1: Batch and order integrity
- **Status**: Local implementation and cross-process store tests pass; simultaneous live download callbacks and bot/web-process contention remain unverified.
- **Files Changed**: `web/merge_plan_store.py`, `bot/helper/common.py`, `bot/modules/ytdlp.py`, `bot/helper/listeners/task_listener.py`, `bot/helper/mirror_leech_utils/download_utils/qbit_download.py`, `bot/helper/ext_utils/merge_order.py`, `tests/test_hyperdl_routing.py`, `tests/test_merge_plan_integrity.py`.
- **Commands Run**: Focused pytest on merge-plan integrity and hyperdl routing (70 passed); Python compileall; git diff check.
- **Results**: Stable case-sensitive item IDs, explicit playlist position IDs, episode-aware torrent/folder ordering, progress-independent order revision, required revision on save, exact-ID payload checks, OS file locks without stale stealing, source-enumeration barrier, and atomic save/freeze. A store race test verifies an acknowledged save wins the freeze; readiness refresh retains interleaved order. Active plans survive age cleanup. The final flow now freezes order before A/V compatibility checks and refuses silent natural-order fallback.
- **Unresolved Failures**: None in the focused store tests.
- **Validation Gaps**: Full child registration/finalizer ownership under simultaneous real download callbacks and authenticated portal writes from a separate process are not yet exercised. Startup now marks unfinished plans interrupted and retains their files, but no resume command is implemented.

### M2: Independent preservation path
- **Status**: Complete for the tested Matroska copy path.
- **Files Changed**: `bot/helper/ext_utils/merge_media.py`, `bot/helper/ext_utils/media_utils.py`, `bot/helper/common.py`, `Dockerfile`, `tests/test_merge_media.py`, `tests/test_encoding_playback_safety.py`.
- **Commands Run**: `mkvmerge -J`, explicit A/V append, final subtitle-only assembly, `ffprobe` stream/chapter/packet hash inspection; `python -m pytest tests/test_merge_media.py` (7 passed across the final suite).
- **Results**: Copy-mode A/V compatibility ignores subtitle layout only; it still compares A/V codec configuration. Differing ASS headers are no longer treated as safe direct append. MKVToolNix appends compatible A/V tracks with explicit mappings, then adds original subtitle tracks at chapter-derived offsets, hashes subtitle packets and rendering headers, checks chapters/duration, and publishes atomically without replacing an existing path. Attachment extraction, deduplication, content hash checks, and basic internal font-name conflict detection are implemented. The actual Dockerfile now installs `mkvmerge` and `mkvextract` even when the published base image is old.
- **Unresolved Failures**: None in the latest synthetic ASS/ASS/SRT fixture.
- **Validation Gaps**: Bitmap subtitles, font rendering comparison, production Linux image, and real Telegram uploads are not yet verified.

### M3: Safe continuous subtitles
- **Status**: Original-track preservation and recognized sidecars pass local tests; continuous SRT/ASS track combining and renderer parity remain incomplete.
- **Files Changed**: `bot/helper/ext_utils/merge_media.py`, `bot/helper/common.py`, `README.md`, `bot/helper/ext_utils/help_messages.py`, `tests/test_merge_media.py`.
- **Commands Run**: Focused media tests and full merge subset; 7 media tests passed.
- **Results**: Subtitle tracks remain separate from A/V append, retain codec/header/event hashes, receive chapter-derived offsets, and support exact-stem language/role sidecars with explicit VobSub pair validation. Identical font attachments are content-deduplicated and conflicting names are rejected.
- **Unresolved Failures**: None in the local fixtures.
- **Validation Gaps**: Continuous SRT/ASS track combining, bitmap subtitle streams, and visual renderer comparison remain unverified. The implemented separate-track fallback requires the viewer to switch tracks at episode chapters.

### M4: One encode per timeline
- **Status**: Complete for the supported continuous profile contract.
- **Files Changed**: `bot/helper/ext_utils/merge_media.py`, `bot/helper/ext_utils/media_utils.py`, `bot/helper/listeners/task_listener.py`, `tests/test_merge_media.py`, `tests/test_encoding_playback_safety.py`.
- **Commands Run**: Mixed-resolution/codec continuous encode fixture; focused suite passed.
- **Results**: A single FFmpeg filter graph decodes, scales/pads, resamples, concatenates, and encodes the complete timeline. Profile validation rejects copy, burn-in, metadata/disposition, cover, rename, and extra-parameter modes that cannot be preserved safely. Audio track count/language/role and color/HDR changes are rejected instead of silently dropping or synthesizing tracks.
- **Unresolved Failures**: None in the local fixture.
- **Validation Gaps**: Hardware encoder parity, HDR output quality, and arbitrary production presets remain unverified.

### M5: Lifecycle and resources
- **Status**: Local lifecycle paths implemented; live failure injection and upload ownership remain unverified.
- **Files Changed**: `bot/helper/common.py`, `bot/helper/listeners/task_listener.py`, `bot/helper/ext_utils/merge_media.py`.
- **Commands Run**: Full focused suite; lifecycle/routing coverage included in 115 passing tests.
- **Results**: Merge processing, validation, upload, completion, cancellation, and failure states are explicit; only the first child failure reports the terminal message; source cleanup waits until successful upload; subprocess pipes are drained and cancellation/timeout terminate the process.
- **Unresolved Failures**: None in merge tests.
- **Validation Gaps**: Live Telegram cancellation, simultaneous final-child callbacks, upload failures, and restart recovery of media artifacts are not exercised here.

### M6: Portal and messaging
- **Status**: Browser script harness and store tests pass; a live authenticated web-server run remains unverified.
- **Files Changed**: `web/merge_plan_store.py`, `web/wserver.py`, `web/static/js/merge-planner.js`, `web/static/css/merge-planner.css`, `web/templates/merge_planner.html`, `bot/helper/ext_utils/bot_utils.py`.
- **Commands Run**: `node --check web/static/js/merge-planner.js`; planner source assertions in the routing suite.
- **Results**: PINs move to URL fragments and request headers, responses are no-store, plan paths never enter public payloads, saves require the current order revision, the UI preserves unsaved order during refresh conflicts, and polling backs off while hidden and stops at terminal states.
- **Unresolved Failures**: None in local source checks.
- **Validation Gaps**: The Playwright test uses the actual planner JavaScript with a mocked API. It does not replace a live authenticated FastAPI/browser run.

### M7: Release verification and docs
- **Status**: Repository checks completed; release certification remains pending the required runtime checks.
- **Files Changed**: `README.md`, `bot/helper/ext_utils/help_messages.py`, `Dockerfile`, plus the implementation and test files above.
- **Commands Run**: 115 merge-focused tests passed; full suite 605 passed and 2 unrelated Wzgram upgrade tests failed; Python compileall; Node syntax check; `git diff --check`.
- **Results**: Documentation covers copy/encode modes, ordering, sidecars, chapters, resource behavior, and unsupported combinations. The production Dockerfile installs and verifies `mkvmerge`/`mkvextract`.
- **Unresolved Failures**: Full suite remains red only because the host has Pyrogram 3.0.33 while `tests/test_wzgram_upgrade.py` requires 3.1.0, and that test reports stopped-loop unawaited coroutine warnings.
- **Validation Gaps**: Docker build, Linux runtime image, live Telegram upload, and cross-version media certification remain pending.

### 2026-09-13 recheck and performance pass
- **Files Changed**: `.gitignore`, `bot/__main__.py`, `bot/helper/common.py`, `bot/helper/ext_utils/merge_media.py`, `bot/helper/ext_utils/merge_order.py`, `bot/helper/ext_utils/media_utils.py`, `bot/helper/listeners/task_listener.py`, `bot/modules/ytdlp.py`, `web/merge_plan_store.py`, `web/static/js/merge-planner.js`, `README.md`, `bot/helper/ext_utils/help_messages.py`, and focused tests. The `.gitignore` exceptions ensure the new tests appear in the reviewable change.
- **Commands Run**: Real Playwright/Edge planner save-conflict-focus-lock test; FFmpeg/MKVToolNix media tests; restart/order and cross-process save/freeze tests; 125-test focused suite; final full `python -m pytest` suite; isolated Wzgram suite; Python compileall; Node syntax check; scoped Ruff; `git diff --check`; measured local synthetic merge.
- **Results**: Duplicate finalizer callbacks now claim one batch owner; unavailable selected playlist entries fail explicitly; restart marks unfinished plans interrupted. A cross-process store race confirms atomic save/freeze. Cancellation and pre-existing-output tests confirm no partial or replacement publication. Sidecar language and forced/SDH roles are carried into MKV tracks. Playback is decoded at bounded start/middle/end points before publication. Profile settings that cannot be honored are rejected before download; supported x264/x265 profile/level and Opus VBR options are applied. Season-folder episode order and case-distinct natural ties are deterministic. Planner refresh avoids moving unchanged DOM rows. The focused suite passed 125 tests. The final broad suite passed 615 of 617 tests; the same two Wzgram failures reproduced in isolation (installed Pyrogram 3.0.33 versus required 3.1.0, plus stopped-loop unawaited coroutine warnings).
- **Performance sample**: Three 2-second synthetic inputs totaling 65,428 bytes produced a 69,281-byte copy-mode MKV in 1.212 seconds on this Windows host. Peak sampled child RSS was 20,652,032 bytes; sampled temporary allocation peaked at 136,916 bytes. The backend invoked `mkvmerge` 6 times, `ffprobe` 6 times, and FFmpeg 3 times for decode validation. This tiny fixture is not a production throughput benchmark.
- **Unresolved Failures**: No merge-focused test failures. Full-suite Wzgram failures are outside the merge diff and reproduce in isolation. One full-suite attempt used a nested pytest base without creating its parent, causing 48 `tmp_path` setup errors; a corrected direct temp base completed with 615 passes and the two Wzgram failures.
- **Validation Gaps**: Docker is unavailable and WSL is not installed. Linux/runtime-image behavior, large media performance, actual multi-source Telegram delivery, live upload cancellation, continuous subtitle combining, bitmap subtitles, and rendered-font parity remain unverified. Do not treat this ledger as production certification.
