document.addEventListener("DOMContentLoaded", () => {
  try {
    const config = window.AMATERASU_PLAYER || {};
    const FILE_URL = config.fileUrl || "";
    const FILE_TYPE = config.fileType || "unknown";
    const FILE_NAME = config.fileName || "";
    const FILE_SIZE = config.fileSize || "";
    const MIME_TYPE = config.mimeType || "application/octet-stream";
    const SUBTITLES = Array.isArray(config.subtitles) ? config.subtitles : [];
    const LOG_PREFIX = "[Amaterasu Player]";

    const absoluteStreamUrl = new URL(FILE_URL, window.location.origin).href;
    const absoluteDownloadUrl = new URL(config.downloadUrl || FILE_URL, window.location.origin).href;
    const mainDownload = document.getElementById("main-download-btn");
    if (mainDownload) mainDownload.href = absoluteDownloadUrl;

    function showToast(message, icon = "info", duration = 2500) {
      const stack = document.getElementById("player-toasts") || document.getElementById("bs-toast-container");
      if (!stack) return;
      const toast = document.createElement("div");
      toast.className = stack.id === "player-toasts" ? "am-toast" : "bs-toast bs-toast--info";
      toast.innerHTML = `<i data-lucide="${icon}"></i><span></span>`;
      toast.querySelector("span").textContent = message;
      stack.appendChild(toast);
      if (window.lucide) window.lucide.createIcons();
      window.setTimeout(() => {
        toast.classList.add("is-leaving");
        window.setTimeout(() => toast.remove(), 220);
      }, duration);
    }
    window.showToast = showToast;

    function copyDownloadUrl() {
      const text = absoluteDownloadUrl;
      if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text).then(() => showToast("Download URL copied", "copy"));
      }
      const input = document.createElement("textarea");
      input.value = text;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      try {
        document.execCommand("copy");
        showToast("Download URL copied", "copy");
      } catch (error) {
        console.error(LOG_PREFIX, "Clipboard fallback failed", error);
        window.prompt("Copy the link below:", text);
      } finally {
        input.remove();
      }
      return Promise.resolve();
    }

    function buildActions() {
      const actions = [
        {
          text: "Copy Download",
          desc: "Copy direct download address",
          click: copyDownloadUrl,
          icon: "copy",
        },
      ];

      if (FILE_TYPE === "video" || FILE_TYPE === "audio") {
        actions.push(
          {
            text: "VLC Player",
            desc: "Stream to VLC on Android",
            url: `intent:${absoluteStreamUrl}#Intent;action=android.intent.action.VIEW;type=${FILE_TYPE}/*;package=org.videolan.vlc;end`,
            icon: "monitor-play",
          },
          {
            text: "MX Player",
            desc: "Stream to MX Player",
            url: `intent:${absoluteStreamUrl}#Intent;action=android.intent.action.VIEW;type=${FILE_TYPE}/*;package=com.mxtech.videoplayer.ad;end`,
            icon: "play-circle",
          },
          {
            text: "iOS VLC",
            desc: "Open stream in VLC",
            url: `vlc-x-callback://x-callback-url/stream?url=${encodeURIComponent(absoluteStreamUrl)}`,
            icon: "smartphone",
          },
          {
            text: "nPlayer",
            desc: "Open stream in nPlayer",
            url: `nplayer-${absoluteStreamUrl}`,
            icon: "play",
          }
        );
      }

      const container = document.getElementById("action-buttons");
      if (!container) return;
      container.textContent = "";
      actions.forEach((action) => {
        const element = document.createElement(action.click ? "button" : "a");
        element.className = "action-card";
        if (action.click) {
          element.type = "button";
          element.setAttribute("aria-label", action.text);
          element.addEventListener("click", action.click);
        } else {
          element.href = action.url;
        }
        element.innerHTML = `
          <div class="action-icon"><i data-lucide="${action.icon}"></i></div>
          <div>
            <span class="action-text"></span>
            <span class="action-desc"></span>
          </div>
        `;
        element.querySelector(".action-text").textContent = action.text;
        element.querySelector(".action-desc").textContent = action.desc;
        container.appendChild(element);
      });
    }

    buildActions();

    if (FILE_TYPE !== "video") {
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    const shell = document.getElementById("am-player");
    const video = document.getElementById("player");
    if (!shell || !video) return;

    const isTouch = window.matchMedia("(pointer: coarse)").matches;
    const playBtn = document.getElementById("play-btn");
    const backwardBtn = document.getElementById("backward-btn");
    const forwardBtn = document.getElementById("forward-btn");
    const muteBtn = document.getElementById("mute-btn");
    const fullscreenBtn = document.getElementById("fullscreen-btn");
    const theaterBtn = document.getElementById("theater-btn");
    const settingsBtn = document.getElementById("settings-btn");
    const audioBtn = document.getElementById("audio-btn");
    const subtitleBtn = document.getElementById("subtitle-btn");
    const progress = document.getElementById("progress");
    const progressFill = document.getElementById("progress-fill");
    const bufferedBar = document.getElementById("buffered-bar");
    const progressThumb = document.getElementById("progress-thumb");
    const progressTooltip = document.getElementById("progress-tooltip");
    const currentTimeEl = document.getElementById("current-time");
    const durationTimeEl = document.getElementById("duration-time");
    const seekIndicator = document.getElementById("seek-indicator");
    const settingsPanel = document.getElementById("settings-panel");
    const audioPanel = document.getElementById("audio-panel");
    const subtitlePanel = document.getElementById("subtitle-panel");
    const audioList = document.getElementById("audio-track-list");
    const subtitleList = document.getElementById("subtitle-track-list");
    const speedGrid = document.getElementById("speed-grid");
    const loopBtn = document.getElementById("loop-btn");
    const pipBtn = document.getElementById("pip-btn");
    const autoplayNextBtn = document.getElementById("autoplay-next-btn");
    const infoResolution = document.getElementById("info-resolution");
    const helpModal = document.getElementById("help-modal");
    const helpBtn = document.getElementById("help-btn");
    const helpCloseBtn = document.getElementById("help-close-btn");
    const errorCard = document.getElementById("error-card");
    const errorMessage = document.getElementById("error-message");
    const retryBtn = document.getElementById("retry-btn");
    const errorDownload = document.getElementById("error-download");
    const statsPanel = document.getElementById("stats-panel");
    const gestureLeft = document.getElementById("gesture-left");
    const gestureRight = document.getElementById("gesture-right");
    const panels = [settingsPanel, audioPanel, subtitlePanel];

    let rafId = 0;
    let idleTimer = 0;
    let draggingProgress = false;
    let lastTapTime = 0;
    let touchState = null;
    let brightness = 1;
    let hideGestureTimer = 0;
    let helpPreviousFocus = null;
    let statsVisible = false;
    let hlsInstance = null;

    function clamp(value, min, max, fallback = min) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return fallback;
      return Math.min(max, Math.max(min, numeric));
    }

    function formatTime(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
      const total = Math.floor(seconds);
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const secs = total % 60;
      if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
      }
      return `${minutes}:${String(secs).padStart(2, "0")}`;
    }

    function setIcon(button, name) {
      if (!button) return;
      button.innerHTML = `<i data-lucide="${name}"></i>`;
      if (window.lucide) window.lucide.createIcons();
    }

    function closePanels(exceptPanel = null) {
      panels.forEach((panel) => {
        if (panel && panel !== exceptPanel) panel.hidden = true;
      });
    }

    function togglePanel(panel) {
      if (!panel) return;
      const shouldOpen = panel.hidden;
      closePanels(panel);
      panel.hidden = !shouldOpen;
      showControls();
    }

    function updatePlayState() {
      const paused = video.paused;
      shell.classList.toggle("is-paused", paused);
      if (playBtn) playBtn.setAttribute("aria-label", paused ? "Play" : "Pause");
      setIcon(playBtn, paused ? "play" : "pause");
      showControls();
    }

    function updateMuteState() {
      const muted = video.muted || video.volume === 0;
      if (muteBtn) muteBtn.setAttribute("aria-label", muted ? "Unmute" : "Mute");
      setIcon(muteBtn, muted ? "volume-x" : video.volume < 0.5 ? "volume-1" : "volume-2");
      try {
        localStorage.setItem("amaterasu_volume", String(video.volume));
        localStorage.setItem("amaterasu_muted", String(video.muted));
      } catch (error) {
        console.warn(LOG_PREFIX, "Could not persist volume", error);
      }
    }

    function seekBy(delta) {
      if (!Number.isFinite(video.duration)) return;
      video.currentTime = clamp(video.currentTime + delta, 0, video.duration);
      const text = delta < 0 ? "-10s" : "+10s";
      seekIndicator.textContent = text;
      seekIndicator.classList.remove("is-visible");
      void seekIndicator.offsetWidth;
      seekIndicator.classList.add("is-visible");
      showToast(delta < 0 ? "Back 10 seconds" : "Forward 10 seconds", delta < 0 ? "rotate-ccw" : "rotate-cw", 1200);
      showControls();
    }

    function togglePlay() {
      if (video.paused) {
        video.play().catch((error) => console.warn(LOG_PREFIX, "Play failed", error));
      } else {
        video.pause();
      }
    }

    function showControls() {
      shell.classList.remove("is-idle");
      window.clearTimeout(idleTimer);
      const delay = isTouch ? 4000 : 3000;
      idleTimer = window.setTimeout(() => {
        if (!video.paused && !draggingProgress) shell.classList.add("is-idle");
      }, delay);
    }

    function setProgressFromClientX(clientX) {
      if (!progress || !Number.isFinite(video.duration) || video.duration <= 0) return;
      const rect = progress.getBoundingClientRect();
      const pct = clamp((clientX - rect.left) / rect.width, 0, 1);
      video.currentTime = pct * video.duration;
      progress.setAttribute("aria-valuenow", String(Math.round(video.currentTime)));
      showControls();
    }

    function updateBuffered() {
      if (!Number.isFinite(video.duration) || video.duration <= 0 || !video.buffered.length) {
        bufferedBar.style.width = "0%";
        return;
      }
      let bufferedEnd = 0;
      for (let index = 0; index < video.buffered.length; index += 1) {
        bufferedEnd = Math.max(bufferedEnd, video.buffered.end(index));
      }
      bufferedBar.style.width = `${clamp((bufferedEnd / video.duration) * 100, 0, 100)}%`;
    }

    function updateProgress() {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const current = Number.isFinite(video.currentTime) ? video.currentTime : 0;
      const pct = duration > 0 ? clamp((current / duration) * 100, 0, 100) : 0;
      progressFill.style.width = `${pct}%`;
      progressThumb.style.left = `${pct}%`;
      currentTimeEl.textContent = formatTime(current);
      durationTimeEl.textContent = formatTime(duration);
      progress.setAttribute("aria-valuemax", String(Math.round(duration)));
      progress.setAttribute("aria-valuenow", String(Math.round(current)));
      progress.setAttribute("aria-valuetext", `${formatTime(current)} of ${formatTime(duration)}`);
      if (statsVisible) updateStats();
      rafId = window.requestAnimationFrame(updateProgress);
    }

    function updateInfo() {
      if (infoResolution) {
        infoResolution.textContent = video.videoWidth && video.videoHeight ? `${video.videoWidth}x${video.videoHeight}` : "Unknown";
      }
    }

    function createRadioOption(name, label, checked, onChange) {
      const option = document.createElement("label");
      option.className = "am-track-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = name;
      input.checked = checked;
      input.addEventListener("change", onChange);
      const span = document.createElement("span");
      span.textContent = label;
      option.append(input, span);
      return option;
    }

    function buildAudioTracks() {
      const tracks = video.audioTracks;
      if (!tracks || tracks.length <= 1) {
        if (!tracks && (FILE_NAME || "").toLowerCase().endsWith(".mkv")) {
          audioBtn.hidden = false;
          audioList.innerHTML = "";
          const note = document.createElement("div");
          note.className = "am-track-option";
          note.textContent = "This browser does not expose MKV audio tracks for switching.";
          audioList.appendChild(note);
        }
        return;
      }
      audioBtn.hidden = false;
      audioList.innerHTML = "";
      Array.from(tracks).forEach((track, index) => {
        const label = track.label || track.language || `Track ${index + 1}`;
        audioList.appendChild(createRadioOption("audio-track", label, track.enabled, () => {
          Array.from(tracks).forEach((candidate, candidateIndex) => {
            candidate.enabled = candidateIndex === index;
          });
          showToast(`Audio: ${label}`, "languages");
        }));
      });
    }

    function buildSubtitleTracks() {
      const tracks = Array.from(video.textTracks || []);
      if (!tracks.length && !SUBTITLES.length) return;
      subtitleBtn.hidden = false;
      subtitleList.innerHTML = "";
      subtitleList.appendChild(createRadioOption("subtitle-track", "Off", true, () => {
        tracks.forEach((track) => {
          track.mode = "disabled";
        });
        showToast("Subtitles off", "captions");
      }));
      tracks.forEach((track, index) => {
        const label = track.label || track.language || `Subtitle ${index + 1}`;
        track.mode = "disabled";
        subtitleList.appendChild(createRadioOption("subtitle-track", label, false, () => {
          tracks.forEach((candidate, candidateIndex) => {
            candidate.mode = candidateIndex === index ? "showing" : "disabled";
          });
          showToast(`Subtitles: ${label}`, "captions");
        }));
      });
    }

    function buildSpeeds() {
      const speeds = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
      speedGrid.innerHTML = "";
      speeds.forEach((speed) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "am-chip";
        chip.textContent = `${speed}x`;
        chip.setAttribute("aria-label", `Set speed to ${speed}x`);
        chip.addEventListener("click", () => {
          video.playbackRate = speed;
          try {
            localStorage.setItem("amaterasu_rate", String(speed));
          } catch (error) {
            console.warn(LOG_PREFIX, "Could not persist playback rate", error);
          }
          Array.from(speedGrid.children).forEach((child) => child.classList.toggle("is-active", child === chip));
          showToast(`Speed ${speed}x`, "gauge");
        });
        speedGrid.appendChild(chip);
      });
    }

    async function toggleFullscreen() {
      try {
        const fsElement = document.fullscreenElement
          || document.webkitFullscreenElement
          || document.mozFullScreenElement
          || document.msFullscreenElement;

        if (fsElement) {
          if (document.exitFullscreen) {
            await document.exitFullscreen();
          } else if (document.webkitExitFullscreen) {
            document.webkitExitFullscreen();
          } else if (document.mozCancelFullScreen) {
            document.mozCancelFullScreen();
          } else if (document.msExitFullscreen) {
            document.msExitFullscreen();
          }
          return;
        }

        if (shell.requestFullscreen) {
          await shell.requestFullscreen();
        } else if (shell.webkitRequestFullscreen) {
          shell.webkitRequestFullscreen();
        } else if (shell.mozRequestFullScreen) {
          shell.mozRequestFullScreen();
        } else if (shell.msRequestFullscreen) {
          shell.msRequestFullscreen();
        } else if (video.webkitEnterFullscreen) {
          video.webkitEnterFullscreen();
        } else if (video.webkitSupportsFullscreen) {
          video.webkitEnterFullscreen();
        } else {
          showToast("Fullscreen is not supported on this device", "info");
        }
      } catch (error) {
        console.warn(LOG_PREFIX, "Fullscreen failed", error);
        if (video.webkitEnterFullscreen) {
          try {
            video.webkitEnterFullscreen();
          } catch (fallbackError) {
            console.warn(LOG_PREFIX, "Fallback fullscreen also failed", fallbackError);
            showToast("Fullscreen is not available", "triangle-alert");
          }
        }
      }
    }

    function updateFullscreenIcon() {
      const fsElement = document.fullscreenElement
        || document.webkitFullscreenElement
        || document.mozFullScreenElement
        || document.msFullscreenElement;
      setIcon(fullscreenBtn, fsElement ? "minimize" : "maximize");
    }

    async function togglePip() {
      try {
        if (document.pictureInPictureElement) {
          await document.exitPictureInPicture();
        } else if (document.pictureInPictureEnabled && video.requestPictureInPicture) {
          await video.requestPictureInPicture();
        } else if (video.webkitSupportsPresentationMode && video.webkitSetPresentationMode) {
          const mode = video.webkitPresentationMode === "picture-in-picture" ? "inline" : "picture-in-picture";
          video.webkitSetPresentationMode(mode);
        } else {
          showToast("Picture in Picture is not available here", "info");
        }
      } catch (error) {
        console.warn(LOG_PREFIX, "Picture in Picture failed", error);
        showToast("Picture in Picture failed", "triangle-alert");
      }
    }

    function updateLoopButton() {
      loopBtn.textContent = video.loop ? "On" : "Off";
      loopBtn.setAttribute("aria-pressed", String(video.loop));
    }

    function setGestureIndicator(side, value) {
      const element = side === "left" ? gestureLeft : gestureRight;
      const fill = element.querySelector(".am-gesture-fill");
      fill.style.height = `${clamp(value * 100, 0, 100)}%`;
      element.classList.add("is-visible");
      window.clearTimeout(hideGestureTimer);
      hideGestureTimer = window.setTimeout(() => {
        gestureLeft.classList.remove("is-visible");
        gestureRight.classList.remove("is-visible");
      }, 1500);
    }

    function addRipple(clientX, clientY) {
      const rect = shell.getBoundingClientRect();
      const ripple = document.createElement("span");
      ripple.className = "am-ripple";
      ripple.style.left = `${clientX - rect.left}px`;
      ripple.style.top = `${clientY - rect.top}px`;
      shell.appendChild(ripple);
      ripple.addEventListener("animationend", () => ripple.remove(), { once: true });
    }

    function toggleHelp(open) {
      helpModal.hidden = !open;
      if (open) {
        helpPreviousFocus = document.activeElement;
        helpCloseBtn.focus();
      } else if (helpPreviousFocus && helpPreviousFocus.focus) {
        helpPreviousFocus.focus();
      }
    }

    function trapHelpFocus(event) {
      if (helpModal.hidden || event.key !== "Tab") return;
      const focusable = Array.from(helpModal.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        last.focus();
        event.preventDefault();
      } else if (!event.shiftKey && document.activeElement === last) {
        first.focus();
        event.preventDefault();
      }
    }

    function readyStateLabel() {
      return ["HAVE_NOTHING", "HAVE_METADATA", "HAVE_CURRENT_DATA", "HAVE_FUTURE_DATA", "HAVE_ENOUGH_DATA"][video.readyState] || "UNKNOWN";
    }

    function updateStats() {
      let dropped = "n/a";
      let total = "n/a";
      if (video.getVideoPlaybackQuality) {
        const quality = video.getVideoPlaybackQuality();
        dropped = quality.droppedVideoFrames;
        total = quality.totalVideoFrames;
      }
      let ahead = 0;
      for (let index = 0; index < video.buffered.length; index += 1) {
        if (video.buffered.start(index) <= video.currentTime && video.buffered.end(index) >= video.currentTime) {
          ahead = video.buffered.end(index) - video.currentTime;
          break;
        }
      }
      statsPanel.textContent = `Buffered ahead: ${ahead.toFixed(1)}s\nDropped frames: ${dropped}/${total}\nReady state: ${readyStateLabel()}`;
    }

    function toggleStats() {
      statsVisible = !statsVisible;
      statsPanel.hidden = !statsVisible;
      if (statsVisible) updateStats();
    }

    function showError() {
      const code = video.error ? video.error.code : "unknown";
      errorMessage.textContent = `Error code: ${code}`;
      errorDownload.href = absoluteDownloadUrl;
      errorCard.hidden = false;
      showToast("Playback error", "triangle-alert");
    }

    function loadHlsIfNeeded() {
      const isHls = /mpegurl|x-mpegurl|vnd\.apple\.mpegurl/i.test(MIME_TYPE) || /\.m3u8($|\?)/i.test(absoluteStreamUrl);
      if (!isHls) return Promise.resolve();
      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = absoluteStreamUrl;
        return Promise.resolve();
      }
      return new Promise((resolve, reject) => {
        if (window.Hls) {
          resolve();
          return;
        }
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/hls.js@latest";
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      }).then(() => {
        if (window.Hls && window.Hls.isSupported()) {
          hlsInstance = new window.Hls();
          hlsInstance.loadSource(absoluteStreamUrl);
          hlsInstance.attachMedia(video);
        } else {
          showToast("HLS playback is not supported in this browser.", "info", 4200);
        }
      }).catch((error) => console.warn(LOG_PREFIX, "HLS setup failed", error));
    }

    function applyStoredPrefs() {
      try {
        const storedVolume = localStorage.getItem("amaterasu_volume");
        const storedMuted = localStorage.getItem("amaterasu_muted");
        const storedRate = localStorage.getItem("amaterasu_rate");
        const storedLoop = localStorage.getItem("amaterasu_loop");
        if (storedVolume !== null) video.volume = clamp(storedVolume, 0, 1, video.volume);
        if (storedMuted !== null) video.muted = storedMuted === "true";
        if (storedRate !== null) video.playbackRate = clamp(storedRate, 0.25, 2, 1);
        if (storedLoop !== null) video.loop = storedLoop === "true";
        if (sessionStorage.getItem("amaterasu_theater") === "true") {
          document.body.classList.add("theater-mode");
        }
      } catch (error) {
        console.warn(LOG_PREFIX, "Could not load player preferences", error);
      }
      updateLoopButton();
      updateMuteState();
    }

    playBtn.addEventListener("click", togglePlay);
    backwardBtn.addEventListener("click", () => seekBy(-10));
    forwardBtn.addEventListener("click", () => seekBy(10));
    muteBtn.addEventListener("click", () => {
      video.muted = !video.muted;
      updateMuteState();
      showToast(video.muted ? "Muted" : "Unmuted", video.muted ? "volume-x" : "volume-2");
    });
    fullscreenBtn.addEventListener("click", () => toggleFullscreen().catch((error) => console.warn(LOG_PREFIX, "Fullscreen failed", error)));
    theaterBtn.addEventListener("click", () => {
      document.body.classList.toggle("theater-mode");
      try {
        sessionStorage.setItem("amaterasu_theater", String(document.body.classList.contains("theater-mode")));
      } catch (error) {
        console.warn(LOG_PREFIX, "Could not persist theater mode", error);
      }
      showToast(document.body.classList.contains("theater-mode") ? "Theater mode on" : "Theater mode off", "rectangle-horizontal");
    });
    settingsBtn.addEventListener("click", () => togglePanel(settingsPanel));
    audioBtn.addEventListener("click", () => togglePanel(audioPanel));
    subtitleBtn.addEventListener("click", () => togglePanel(subtitlePanel));
    pipBtn.addEventListener("click", togglePip);
    loopBtn.addEventListener("click", () => {
      video.loop = !video.loop;
      try {
        localStorage.setItem("amaterasu_loop", String(video.loop));
      } catch (error) {
        console.warn(LOG_PREFIX, "Could not persist loop", error);
      }
      updateLoopButton();
      showToast(video.loop ? "Loop on" : "Loop off", "repeat");
    });
    autoplayNextBtn.addEventListener("click", () => {
      showToast("Send files as a Telegram batch, then open the next generated watch link.", "list-video", 4200);
    });
    helpBtn.addEventListener("click", () => toggleHelp(true));
    helpCloseBtn.addEventListener("click", () => toggleHelp(false));
    helpModal.addEventListener("click", (event) => {
      if (event.target === helpModal) toggleHelp(false);
    });
    retryBtn.addEventListener("click", () => {
      errorCard.hidden = true;
      video.load();
      video.play().catch((error) => console.warn(LOG_PREFIX, "Retry play failed", error));
    });

    progress.addEventListener("pointerdown", (event) => {
      draggingProgress = true;
      progress.setPointerCapture(event.pointerId);
      setProgressFromClientX(event.clientX);
    });
    progress.addEventListener("pointermove", (event) => {
      const rect = progress.getBoundingClientRect();
      const pct = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const preview = pct * (Number.isFinite(video.duration) ? video.duration : 0);
      progressTooltip.textContent = formatTime(preview);
      progressTooltip.style.left = `${pct * 100}%`;
      if (draggingProgress) setProgressFromClientX(event.clientX);
    });
    progress.addEventListener("pointerup", (event) => {
      draggingProgress = false;
      if (progress.hasPointerCapture(event.pointerId)) {
        progress.releasePointerCapture(event.pointerId);
      }
    });
    progress.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        seekBy(-10);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        seekBy(10);
      }
    });

    shell.addEventListener("mousemove", showControls);
    shell.addEventListener("mouseleave", () => {
      if (!video.paused && !draggingProgress) {
        window.clearTimeout(idleTimer);
        idleTimer = window.setTimeout(() => {
          shell.classList.add("is-idle");
        }, 600);
      }
    });
    shell.addEventListener("click", (event) => {
      if (event.target === video || event.target.id === "tap-layer") {
        if (!isTouch) {
          togglePlay();
          showControls();
        }
      }
    });
    shell.addEventListener("touchstart", (event) => {
      const touch = event.touches[0];
      const shellRect = shell.getBoundingClientRect();
      touchState = {
        startX: touch.clientX,
        startY: touch.clientY,
        lastY: touch.clientY,
        side: touch.clientX < shellRect.left + shellRect.width / 2 ? "left" : "right",
        swiping: false,
        moved: false,
        startVolume: video.volume,
        startBrightness: brightness,
      };
    }, { passive: true });
    shell.addEventListener("touchmove", (event) => {
      if (!touchState || event.touches.length !== 1) return;
      const touch = event.touches[0];
      const dx = touch.clientX - touchState.startX;
      const dy = touch.clientY - touchState.startY;
      if (!touchState.swiping && Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx) * 1.2) {
        touchState.swiping = true;
      }
      if (touchState.swiping) {
        event.preventDefault();
        touchState.moved = true;
        const delta = (touchState.startY - touch.clientY) * 0.0025;
        if (touchState.side === "left") {
          brightness = clamp(touchState.startBrightness + delta, 0.2, 2);
          video.style.filter = `brightness(${brightness})`;
          setGestureIndicator("left", (brightness - 0.2) / 1.8);
        } else {
          video.volume = clamp(touchState.startVolume + delta, 0, 1);
          video.muted = video.volume === 0;
          updateMuteState();
          setGestureIndicator("right", video.volume);
        }
      }
    }, { passive: false });
    shell.addEventListener("touchend", (event) => {
      const touch = event.changedTouches[0];
      if (!touchState || touchState.moved) {
        touchState = null;
        return;
      }
      const now = Date.now();
      if (now - lastTapTime <= 300) {
        const rect = shell.getBoundingClientRect();
        const x = touch.clientX - rect.left;
        addRipple(touch.clientX, touch.clientY);
        if (x < rect.width * 0.3) {
          seekBy(-10);
        } else if (x > rect.width * 0.7) {
          seekBy(10);
        } else {
          togglePlay();
        }
        lastTapTime = 0;
      } else {
        lastTapTime = now;
        if (shell.classList.contains("is-idle")) {
          showControls();
        } else if (!video.paused) {
          shell.classList.add("is-idle");
        }
      }
      touchState = null;
    });

    document.addEventListener("keydown", (event) => {
      const target = event.target;
      const typing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (typing) return;
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "d") {
        event.preventDefault();
        toggleStats();
        return;
      }
      if (!helpModal.hidden) {
        if (event.key === "Escape") {
          event.preventDefault();
          toggleHelp(false);
        }
        trapHelpFocus(event);
        return;
      }
      switch (event.key.toLowerCase()) {
        case " ":
        case "k":
          event.preventDefault();
          togglePlay();
          break;
        case "arrowleft":
          event.preventDefault();
          seekBy(-10);
          break;
        case "arrowright":
          event.preventDefault();
          seekBy(10);
          break;
        case "arrowup":
          event.preventDefault();
          video.volume = clamp(video.volume + 0.05, 0, 1);
          video.muted = false;
          updateMuteState();
          break;
        case "arrowdown":
          event.preventDefault();
          video.volume = clamp(video.volume - 0.05, 0, 1);
          video.muted = video.volume === 0;
          updateMuteState();
          break;
        case "m":
          video.muted = !video.muted;
          updateMuteState();
          break;
        case "f":
          event.preventDefault();
          toggleFullscreen().catch((error) => console.warn(LOG_PREFIX, "Fullscreen failed", error));
          break;
        case "escape":
          closePanels();
          break;
      }
    });

    video.addEventListener("play", updatePlayState);
    video.addEventListener("pause", updatePlayState);
    video.addEventListener("volumechange", updateMuteState);
    video.addEventListener("progress", updateBuffered);
    video.addEventListener("loadedmetadata", () => {
      updateInfo();
      buildAudioTracks();
      buildSubtitleTracks();
      showControls();
    });
    video.addEventListener("error", showError);

    buildSpeeds();
    applyStoredPrefs();
    Array.from(speedGrid.children).forEach((child) => {
      child.classList.toggle("is-active", child.textContent === `${video.playbackRate}x`);
    });

    document.addEventListener("fullscreenchange", updateFullscreenIcon);
    document.addEventListener("webkitfullscreenchange", updateFullscreenIcon);
    document.addEventListener("mozfullscreenchange", updateFullscreenIcon);
    document.addEventListener("MSFullscreenChange", updateFullscreenIcon);

    loadHlsIfNeeded().finally(() => {
      shell.classList.add("is-ready");
      video.removeAttribute("controls");
      updatePlayState();
      updateProgress();
      showControls();
      if (window.lucide) window.lucide.createIcons();
    });

    window.addEventListener("pagehide", () => {
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(idleTimer);
      window.clearTimeout(hideGestureTimer);
      if (hlsInstance) hlsInstance.destroy();
    });
  } catch (error) {
    console.error("[Amaterasu Player]", error);
  }
});
