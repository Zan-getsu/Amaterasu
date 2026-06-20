# Changelog

All notable changes to Amaterasu are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.1] — 2026-06-20

### Major Upgrade — "Feature-Rich, Robust, Powerful, Fast"

This release focuses on making Amaterasu the most feature-rich, robust,
and fast mirror-leech Telegram bot available. Security hardening from
v1.5.0 is preserved, but now every hardening measure is configurable
so it never blocks functionality.

### Added — Config Relaxations (Phase 0)

- `BIND_TO_LOOPBACK` config (default `True`). When `False`, the web UI
  binds `0.0.0.0` for direct LAN access without a reverse proxy.
- `UPSTREAM_ALLOWLIST` config. Comma-separated regex patterns for
  allowed `UPSTREAM_REPO` URLs. Operators can add their own fork URL
  for auto-update without editing source code.
- `SKIP_SABNZBD_INI_CHECK` config (default `False`). Bypasses the
  SABnzbd.ini validation for operators who manage the ini manually.
- aria2.conf tuning: `retry-wait=5`, `connect-timeout=30`,
  `lowest-speed-limit=1K` for better download reliability.
- Documented `check-certificate=false` as a compatibility feature
  (FTP, self-signed HTTPS, cert-pinned CDNs) — not a security risk.

### Added — WZML-X Feature Ports (Phase 1)

- **Debrid multi-provider support**: Real-Debrid (`rd:`), AllDebrid
  (`ad:`), Premiumize (`pm:`), Debrid-Link (`dl:`) via
  `DEBRID_LINK_API` prefix.
- **4 new DDL hosters**: StreamWish, FileLion, InstaDL, Protected.link
  upload support. Each appears in the UI only when its API key is set.
- **Web UI login password** (`LOGIN_PASS`): optional HMAC-signed
  session cookie for admin routes. Separate from `WEB_ACCESS_PASSWORD`.
- **Force-subscribe** (`FORCE_SUB_IDS`): require users to join
  specified channels before using the bot.
- **Blacklist system with MongoDB TTL**: `blacklisted_users` collection
  with auto-expiring temporary bans. Dual-write (in-memory + MongoDB).
- **Interactive image search**: `/images <query>` searches
  wallpaperflare/peapix/wallhaven with paginated Mirror/Next/Close
  buttons.
- **Cloudflare tunnel URL persistence**: `tunnel_monitor.py` watches
  `/data/tunnel_url.txt` and propagates new URLs to Config, MongoDB,
  and owner DM.
- **Multi-instance docker-compose template**: commented `amaterasu2` +
  `tunnel2` blocks.
- **Gluetun VPN option**: commented gluetun service block.
- **MongoDB connection pooling**: `maxPoolSize=50`, `minPoolSize=5`,
  `serverSelectionTimeoutMS=5000`.

### Added — Robustness & Reliability (Phase 2)

- **Retry decorator** (`@retryable`): exponential backoff (1→2→4→8→16s)
  for transient failures.
- **Disk space pre-check**: fails fast with actionable error message
  before starting a download.
- **Telegram FloodWait manager**: per-chat state tracking, preemptive
  delay for recently-rate-limited chats.
- **Shared HTTP client** (`http_client.py`): singleton `httpx.AsyncClient`
  with HTTP/2, connection pooling, sensible timeouts.
- **Engine fallback chain** (`engine_selector.py`): smart URL-based
  engine selection with health-aware fallback.
- **Actionable error messages** (`error_messages.py`): `BotError` class
  with 8 factory functions (disk_full, network_timeout, etc.).
- **Engine health checks**: 5-minute interval, owner DM on
  HEALTHY→UNAVAILABLE and UNAVAILABLE→HEALTHY transitions. Integrated
  into `/healthz` endpoint.
- **Removed dead code**: deleted `error_handler.py` (224 LOC, never
  imported).
- **Deduplication**: `get_media`/`get_media_type`/`MEDIA_TYPES`
  consolidated into `tg_utils.py`.

### Added — Performance (Phase 3)

- **FFmpeg hardware acceleration**: auto-detects NVENC/QSV/VAAPI/
  VideoToolbox at startup. `FFMPEG_HW_ACCEL` config override.
- **Parallel multi-source download** (`--multi` flag): pass multiple
  URLs, aria2 downloads from all sources in parallel.
- **Download queue prioritization**: `priority` field on `TaskConfig`.
  Queue dispatcher sorts by priority DESC, FIFO for same priority.
- **Upload queue parallelism** (`UPLOAD_PARALLELISM`): semaphore-limited
  concurrent uploads (default 3).
- **yt-dlp playlist parallelism** (`PLAYLIST_PARALLELISM`): bumped
  `concurrent_fragments` for playlists.
- **Adaptive status update interval**: 5s for active tasks, 60s for
  idle — reduces Telegram API calls.
- **DB query optimization**: indexes on `user_stats.user_id`,
  `background=True` index creation.

### Added — New Features (Phase 4)

- **Sequential torrent streaming** (`--stream` flag): qBittorrent
  `sequential_download=true` + `first_last_piece_priority=true`;
  aria2 `bt-prioritize-piece=head,tail`. Stream while still downloading.
- **Cloud-to-cloud transfer** (`--c2c` flag): `rclone copy` directly
  between two remotes — no local download, server-side copy where
  supported.
- **Automatic subtitle download** (`AUTO_SUBTITLES`): OpenSubtitles API
  search by file hash, 7-day MongoDB cache, never fails the task.
- **Additional rclone upload remotes**: `RCLONE_SFTP_REMOTE`,
  `RCLONE_WEBDAV_REMOTE`, `RCLONE_B2_REMOTE`, `RCLONE_ONEDRIVE_REMOTE`,
  `RCLONE_DROPBOX_REMOTE` (config + README docs).
- **Telegram Premium auto-detect**: `IS_PREMIUM_BOT` auto-detected at
  startup, 4 GB upload limit when premium (vs 2 GB standard).

### Added — UX & Polish (Phase 5)

- **Multi-language expansion**: 2 → 10 languages (en, bn, es, fr, de,
  ar, hi, ja, ru, pt). Machine-translated with community-correction
  welcome comment.
- **Help fuzzy search**: `/help <query>` uses `rapidfuzz` (score > 60)
  with substring fallback.
- **Per-user quota system** (`USER_DAILY_QUOTA_GB`,
  `USER_MONTHLY_QUOTA_GB`): checked in `pre_task_check`, lazy reset
  (24h/30d), sudo bypass.
- **Smart notifications** (`notifications.py`): per-user prefs (all/
  compact/silent), milestone tracking (25/50/75%).
- **Interactive setup wizard** (`/setup`): 5-step owner-only wizard
  with inline keyboards (DOWNLOAD_DIR, GDrive, Rclone, OWNER_ID,
  Summary).

### Added — Quality Infrastructure (Phase 6)

- **29 smoke tests**: HMAC tokens, path traversal, PIN rate limiting,
  salt loader, config coercion, literal_eval safety, SABnzbd patcher,
  disk space, engine selector, retry decorator, flood wait manager.
- **CI workflow** (`.github/workflows/ci.yml`): ruff check + ruff
  format --check + pytest + pip-audit on every push/PR.
- **11 critical dependencies pinned** with `==` for reproducible builds.
- **Structured logging** (`LOG_FORMAT=json`): JSON log lines for log
  aggregation tools.
- **Dependabot** (`.github/dependabot.yml`): monthly, grouped
  minor+patch updates.

### Changed

- Version bumped from v1.5.0 to v1.6.1.
- `aria2.conf` now documents `check-certificate=false` as a
  compatibility feature (not a security risk).
- `docker-compose.yml` rewritten with tunnel service, multi-instance
  template, gluetun VPN option, configurable port binding.
- `requirements.txt` reorganized: unpinned deps first, pinned critical
  deps in a dedicated section, test deps at the end.
- `bot/__init__.py` logging now supports both text and JSON formats.

### Removed

- `bot/helper/ext_utils/error_handler.py` (224 LOC dead code —
  CircuitBreaker/ErrorMonitor defined but never imported).

### Deferred (not in v1.6.1)

- **Real-time transcoding** (Phase 4.2): requires a live transcoding
  server — deferred to v1.7.
- **Lazy module loading** (Phase 3.9): regression risk too high for
  36 modules — deferred to a future minor release.
- **Status UI redesign** (Phase 5.1/5.7): skipped per user instruction.

### Backward Compatibility

- All new config options have defaults that match v1.5.0 behavior.
- All new flags (`--multi`, `--stream`, `--c2c`) are opt-in.
- `/healthz` response is additive (new `engines` field, same 200/503
  status codes).
- MongoDB schema changes are additive (new collections, no existing
  field renames or type changes).
- Docker volume mount paths unchanged.

## [1.5.0] — 2026-06-19

Initial Amaterasu release. Fork of WZML-X with security hardening:
per-deployment HMAC salts, HMAC-signed URL tokens, non-root Docker,
loopback port binding, allowlist-gated self-update, FileToLink
streaming, HyperDL/HyperUP parallel transfer, auto-rename engine,
metadata injection, encode profile Web UI, /healthz + /metrics,
graceful SIGTERM shutdown.
