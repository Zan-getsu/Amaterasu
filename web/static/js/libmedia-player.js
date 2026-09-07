(function () {
  "use strict";

  const AVPLAYER_SRC =
    "https://cdn.jsdelivr.net/npm/@libmedia/avplayer@1.3.1/dist/umd/avplayer.js";
  let avPlayerLoading = null;

  function loadAVPlayer() {
    if (window.AVPlayer) return Promise.resolve(window.AVPlayer);
    if (avPlayerLoading) return avPlayerLoading;
    avPlayerLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = AVPLAYER_SRC;
      script.crossOrigin = "anonymous";
      script.onload = () => {
        if (window.AVPlayer) resolve(window.AVPlayer);
        else reject(new Error("Advanced decoder did not expose AVPlayer"));
      };
      script.onerror = () => reject(new Error("Advanced decoder could not be loaded"));
      document.head.appendChild(script);
    }).catch((error) => {
      avPlayerLoading = null;
      throw error;
    });
    return avPlayerLoading;
  }

  class AmaterasuLibmediaPlayer extends HTMLElement {
    constructor() {
      super();
      this._host = document.createElement("div");
      this._host.className = "am-libmedia-host";
      const shadow = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = `
        :host { display:block; position:absolute; inset:0; width:100%; height:100%; background:#000; }
        .am-libmedia-host { position:absolute; inset:0; width:100%; height:100%; }
        canvas, video { width:100% !important; height:100% !important; object-fit:contain; background:#000; }
      `;
      shadow.append(style, this._host);
      this._player = null;
      this._streams = [];
      this._duration = NaN;
      this._currentTime = 0;
      this._paused = true;
      this._ended = false;
      this._readyState = 0;
      this._volume = 1;
      this._muted = false;
      this._playbackRate = 1;
      this._loop = false;
      this._started = false;
      this._loaded = false;
      this._subtitleEnabled = false;
      this._audioIndex = null;
      this._subtitleIndex = null;
      this._subtitleDelay = 0;
      this._error = null;
      this._seeking = false;
      this._generation = 0;
      this._pendingSeek = null;
      this._seekTarget = null;
      this._seekQueued = false;
      this._queue = Promise.resolve();
      this._source = "";
      this._resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(() => this._resize()) : null;
    }

    connectedCallback() { this._resizeObserver?.observe(this._host); }

    _resize() {
      if (this._started && this._player && this.clientWidth > 0 && this.clientHeight > 0) {
        this._player.resize?.(this.clientWidth, this.clientHeight);
      }
    }

    static preload() {
      return loadAVPlayer().catch(() => null);
    }

    _emit(type, detail) {
      this.dispatchEvent(detail === undefined ? new Event(type) : new CustomEvent(type, { detail }));
    }

    _seconds(value) {
      const numeric = Number(value);
      return Number.isFinite(numeric) && numeric >= 0 ? numeric / 1000 : 0;
    }

    _durationFrom(streams) {
      let best = 0;
      streams.forEach((stream) => {
        if (!stream || stream.duration === undefined || stream.duration === null) return;
        const duration = Number(stream.duration);
        if (!Number.isFinite(duration) || duration <= 0) return;
        const timeBase = stream.timeBase;
        const seconds = timeBase && Number(timeBase.den) > 0
          ? duration * (Number(timeBase.num) || 1) / Number(timeBase.den)
          : duration / 1000;
        if (seconds > best) best = seconds;
      });
      return best || NaN;
    }

    _run(operation) {
      const generation = this._generation;
      const next = this._queue.then(() => {
        if (generation !== this._generation) throw new DOMException("Playback was closed", "AbortError");
        return operation();
      });
      this._queue = next.then(() => undefined, () => undefined);
      return next;
    }

    _isPlayable(status) {
      return status === 4 || status === 7 || status === 8;
    }

    _isActive(status) {
      return status === 5 || status === 6;
    }

    _isTransient(status) {
      return status === 1 || status === 3 || status === 9 || status === 10;
    }

    _status() {
      return this._player?.getStatus?.() ?? this._player?.status;
    }

    async _settle() {
      const player = this._player;
      for (let attempt = 0; player === this._player && this._isTransient(this._status()) && attempt < 80; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 25));
      }
      if (!player || player !== this._player) throw new DOMException("Playback was closed", "AbortError");
      if (this._isTransient(this._status())) throw new Error("Player is still busy. Please try again.");
    }

    open(url, options = {}) {
      return this._run(() => this._open(url, options));
    }

    async _open(url, options) {
      const generation = this._generation;
      this._source = url;
      this._emit("loadstart");
      const AVPlayer = await loadAVPlayer();
      if (generation !== this._generation) throw new DOMException("Playback was closed", "AbortError");
      if (this._player) {
        try {
          await this._player.destroy();
        } catch (error) {
          console.warn("[Amaterasu Player] Could not reset advanced decoder", error);
        }
      }
      if (generation !== this._generation) throw new DOMException("Playback was closed", "AbortError");

      this._loaded = this._started = this._ended = this._seeking = false;
      this._paused = true;
      this._error = null;
      this._readyState = 0;
      this._currentTime = Number(options.currentTime) || 0;
      this._pendingSeek = this._currentTime > 0 ? this._currentTime : null;
      this._seekTarget = null;
      this._audioIndex = Number.isInteger(options.audioIndex) ? options.audioIndex : null;
      this._subtitleIndex = Number.isInteger(options.subtitleIndex) ? options.subtitleIndex : null;
      this._subtitleEnabled = this._subtitleIndex !== null;

      // AVPlayer 1.3.1 worker proxies lose subtitle packet time bases without
      // shared memory. Keep native/WebCodecs decoding, but avoid that proxy path.
      const player = new AVPlayer({ container: this._host, isLive: false, enableWorker: false });
      this._player = player;
      const on = (type, callback) => player.on(type, (...args) => {
        if (this._player === player) callback(...args);
      });
      on("time", (pts) => {
        if (!this.seeking && this._pendingSeek === null) this._currentTime = this._seconds(pts);
        this._emit("timeupdate");
      });
      on("played", () => {
        this._paused = false;
        this._ended = false;
        this._started = true;
        this._emit("play");
      });
      on("playing", () => {
        this._paused = false;
        this._emit("playing");
      });
      on("paused", () => {
        this._paused = true;
        this._emit("pause");
      });
      on("ended", () => {
        if (this._loop) {
          this.currentTime = 0;
          this.play().catch(() => undefined);
          return;
        }
        this._paused = true;
        this._ended = true;
        this._emit("ended");
      });
      on("error", (error) => {
        this._error = error || new Error("Advanced playback failed");
        this._emit("error", this._error);
      });

      await player.load(url);
      if (this._player !== player) throw new DOMException("Playback was closed", "AbortError");
      this._streams = player.getStreams ? player.getStreams() : [];
      if (typeof player.setSubtitleEnable === "function") player.setSubtitleEnable(false);
      this._duration = this._seconds(player.getDuration?.()) || this._durationFrom(this._streams);
      this._readyState = 4;
      this._loaded = true;
      this._emit("durationchange");
      this._emit("loadedmetadata");
      this._emit("canplay");
      this._emit("advancedstreams", this._streams);

      this.volume = options.volume === undefined ? this._volume : options.volume;
      this.muted = options.muted === undefined ? this._muted : options.muted;
      this.playbackRate = options.playbackRate || this._playbackRate;
      if (options.autoplay) await this._play();
      return this;
    }

    async _play() {
      if (!this._player || !this._loaded) return;
      await this._settle();
      const player = this._player;
      const firstPlay = !this._started;
      // AVPlayer creates track renderers on play, not load. Apply selections only then.
      if (firstPlay) player.setVolume(0);
      try {
        if (!this._isActive(this._status()) && this._isPlayable(this._status())) await player.play();
        if (player !== this._player) return;
        this._started = true;
        if (firstPlay && this._audioIndex !== null) await this._selectAudio(this._audioIndex);
        if (this._subtitleEnabled && this._subtitleIndex !== null) await this._selectSubtitle(this._subtitleIndex);
        player.setSubtitleDelay?.(this._subtitleDelay);
        if (this._pendingSeek !== null) {
          const target = this._pendingSeek;
          this._pendingSeek = null;
          await this._seek(target);
        }
        if (!this._subtitleEnabled) player.setSubtitleEnable?.(false);
        this._resize();
      } finally {
        if (player === this._player) player.setVolume(this._muted ? 0 : this._volume);
      }
    }

    play() {
      this._paused = false;
      this._emit("play");
      return this._run(() => this._play()).catch((error) => {
        if (error.name !== "AbortError") {
          this._paused = true;
          this._error = error;
          this._emit("pause");
          this._emit("error", error);
        }
        throw error;
      });
    }

    pause() {
      this._paused = true;
      this._emit("pause");
      return this._run(async () => {
        await this._settle();
        if (this._player && this._started && this._isActive(this._status())) {
          await this._player.pause();
        }
      });
    }

    async _seek(seconds) {
      if (!this._player) return;
      await this._settle();
      const player = this._player;
      this._seeking = true;
      this._emit("seeking");
      const milliseconds = Math.max(0, Math.round(seconds * 1000));
      try {
        await player.seek(BigInt(milliseconds));
        if (player !== this._player) return;
        if (this._seekTarget === null) this._currentTime = seconds;
        this._ended = false;
        if (!this._subtitleEnabled) player.setSubtitleEnable?.(false);
      } finally {
        this._seeking = false;
      }
      this._emit("seeked");
      this._emit("timeupdate");
    }

    _scheduleSeek(target) {
      this._seekTarget = target;
      if (this._seekQueued) return;
      this._seekQueued = true;
      this._run(async () => {
        while (this._seekTarget !== null) {
          const nextTarget = this._seekTarget;
          this._seekTarget = null;
          await this._seek(nextTarget);
        }
      }).catch((error) => {
        if (error.name !== "AbortError") {
          this._error = error;
          this._emit("error", error);
        }
      }).finally(() => {
        this._seekQueued = false;
        if (this._seekTarget !== null) this._scheduleSeek(this._seekTarget);
      });
    }

    getAudioStreams() {
      return this._streams.filter((stream) => stream && [1, "Audio"].includes(stream.mediaType));
    }

    getSubtitleStreams() {
      return this._streams.filter((stream) => stream && [3, "Subtitle"].includes(stream.mediaType));
    }

    selectAudioByIndex(index) {
      return this._run(() => this._selectAudio(index));
    }

    async _selectAudio(index) {
      const streams = this.getAudioStreams();
      const selected = streams[index];
      if (!selected || !this._player) throw new Error("Audio track is unavailable");
      this._audioIndex = index;
      if (!this._started) return selected;
      await this._settle();
      if (this._player.getSelectedAudioStreamId?.() !== selected.id) await this._player.selectAudio(selected.id);
      await this._settle();
      if (!this._subtitleEnabled) this._player.setSubtitleEnable?.(false);
      return selected;
    }

    selectSubtitleByIndex(index) {
      return this._run(() => this._selectSubtitle(index));
    }

    async _selectSubtitle(index) {
      const selected = this.getSubtitleStreams()[index];
      if (!selected || !this._player) throw new Error("Subtitle track is unavailable");
      const wasEnabled = this._subtitleEnabled;
      this._subtitleIndex = index;
      this._subtitleEnabled = true;
      if (!this._started) return selected;
      await this._settle();
      if (this._player.getSelectedSubtitleStreamId?.() !== selected.id) await this._player.selectSubtitle(selected.id);
      if (this._player.getSelectedSubtitleStreamId?.() !== undefined && this._player.getSelectedSubtitleStreamId() !== selected.id) {
        throw new Error("This subtitle track is not supported by the decoder");
      }
      if (!wasEnabled && typeof this._player.setSubtitleEnable === "function") {
        this._player.setSubtitleEnable(true);
      }
      return selected;
    }

    setSubtitleEnabled(enabled) {
      const nextEnabled = Boolean(enabled);
      this._subtitleEnabled = nextEnabled;
      return this._run(async () => {
        this._subtitleEnabled = nextEnabled;
        if (this._player) this._player.setSubtitleEnable?.(nextEnabled);
      });
    }

    setSubtitleDelay(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value)) return;
      this._subtitleDelay = Math.round(Math.max(-5, Math.min(5, value)) * 1000);
      this._player?.setSubtitleDelay?.(this._subtitleDelay);
    }

    load() {
      if (this._source) return this.open(this._source, {
        currentTime: this.currentTime, audioIndex: this._audioIndex,
        subtitleIndex: this._subtitleEnabled ? this._subtitleIndex : null,
      });
      return Promise.resolve(this);
    }

    get paused() { return this._paused; }
    get ended() { return this._ended; }
    get seeking() { return this._seeking || this._seekQueued; }
    get readyState() { return this._readyState; }
    get duration() { return this._duration; }
    get currentTime() { return this._currentTime; }
    set currentTime(value) {
      let target = Number(value);
      if (!Number.isFinite(target)) return;
      target = Math.max(0, Math.min(target, Number.isFinite(this._duration) ? this._duration : Infinity));
      this._currentTime = target;
      if (!this._player || !this._started) {
        this._pendingSeek = target;
        this._emit("timeupdate");
      } else {
        this._scheduleSeek(target);
      }
    }
    get volume() { return this._volume; }
    set volume(value) {
      this._volume = Math.max(0, Math.min(1, Number(value)));
      if (this._player) this._player.setVolume(this._muted ? 0 : this._volume);
      this._emit("volumechange");
    }
    get muted() { return this._muted; }
    set muted(value) {
      this._muted = Boolean(value);
      if (this._player) this._player.setVolume(this._muted ? 0 : this._volume);
      this._emit("volumechange");
    }
    get playbackRate() { return this._playbackRate; }
    set playbackRate(value) {
      this._playbackRate = Number(value) || 1;
      if (this._player) this._player.setPlaybackRate(this._playbackRate);
      this._emit("ratechange");
    }
    get loop() { return this._loop; }
    set loop(value) { this._loop = Boolean(value); }
    get buffered() {
      const media = this._host.querySelector("video, audio");
      return media?.buffered || { length: 0, start() { throw new RangeError("No buffered range"); }, end() { throw new RangeError("No buffered range"); } };
    }
    get videoWidth() {
      const stream = this._streams.find((item) => item && [0, "Video"].includes(item.mediaType));
      return Number(stream && (stream.codecparProxy?.width || stream.width)) || 0;
    }
    get videoHeight() {
      const stream = this._streams.find((item) => item && [0, "Video"].includes(item.mediaType));
      return Number(stream && (stream.codecparProxy?.height || stream.height)) || 0;
    }
    get error() { return this._error; }

    async destroy() {
      this._resizeObserver?.disconnect();
      this._generation += 1;
      this._pendingSeek = this._seekTarget = null;
      this._loaded = this._started = false;
      if (!this._player) return;
      const player = this._player;
      this._player = null;
      await player.destroy();
    }

    disconnectedCallback() {
      this.destroy().catch(() => undefined);
    }
  }

  if (!customElements.get("amaterasu-libmedia-player")) {
    customElements.define("amaterasu-libmedia-player", AmaterasuLibmediaPlayer);
  }
  window.AmaterasuLibmediaPlayer = AmaterasuLibmediaPlayer;
})();
