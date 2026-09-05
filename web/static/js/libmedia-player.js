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
      this._pendingSeek = null;
      this._seekTarget = null;
      this._seekQueued = false;
      this._queue = Promise.resolve();
      this._source = "";
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
      const next = this._queue.then(operation, operation);
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
      return status === 2 || status === 3 || status === 10;
    }

    async _settle() {
      for (let attempt = 0; this._player && this._isTransient(this._player.status) && attempt < 80; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 25));
      }
    }

    async open(url, options = {}) {
      this._source = url;
      this._emit("loadstart");
      const AVPlayer = await loadAVPlayer();
      if (this._player) {
        try {
          await this._player.destroy();
        } catch (error) {
          console.warn("[Amaterasu Player] Could not reset advanced decoder", error);
        }
      }

      const player = new AVPlayer({ container: this._host, isLive: false });
      this._player = player;
      player.on("time", (pts) => {
        this._currentTime = this._seconds(pts);
        this._emit("timeupdate");
      });
      player.on("played", () => {
        this._paused = false;
        this._ended = false;
        this._started = true;
        this._emit("play");
      });
      player.on("playing", () => {
        this._paused = false;
        this._emit("playing");
      });
      player.on("paused", () => {
        this._paused = true;
        this._emit("pause");
      });
      player.on("ended", () => {
        if (this._loop) {
          this.currentTime = 0;
          this.play().catch(() => undefined);
          return;
        }
        this._paused = true;
        this._ended = true;
        this._emit("ended");
      });
      player.on("seeking", () => this._emit("seeking"));
      player.on("seeked", () => this._emit("seeked"));
      player.on("error", (error) => this._emit("error", error));

      await player.load(url);
      this._streams = player.getStreams ? player.getStreams() : [];
      if (typeof player.setSubtitleEnable === "function") player.setSubtitleEnable(false);
      this._duration = this._durationFrom(this._streams);
      this._readyState = 4;
      this._loaded = true;
      this._emit("durationchange");
      this._emit("loadedmetadata");
      this._emit("canplay");
      this._emit("advancedstreams", this._streams);

      this.volume = options.volume === undefined ? this._volume : options.volume;
      this.muted = options.muted === undefined ? this._muted : options.muted;
      this.playbackRate = options.playbackRate || this._playbackRate;
      if (Number.isInteger(options.audioIndex) && options.audioIndex > 0) {
        await this.selectAudioByIndex(options.audioIndex);
      }
      if (Number.isInteger(options.subtitleIndex)) {
        await this.selectSubtitleByIndex(options.subtitleIndex);
      }
      if (Number(options.currentTime) > 0) {
        this.currentTime = Number(options.currentTime);
      }
      if (options.autoplay) await this.play();
      return this;
    }

    async _play() {
      if (!this._player || !this._loaded) return;
      await this._settle();
      if (!this._isActive(this._player.status) && this._isPlayable(this._player.status)) {
        await this._player.play();
      }
      this._started = true;
      if (this._pendingSeek !== null) {
        const target = this._pendingSeek;
        this._pendingSeek = null;
        await this._seek(target);
      }
    }

    play() {
      this._paused = false;
      this._emit("play");
      return this._run(() => this._play());
    }

    pause() {
      this._paused = true;
      this._emit("pause");
      return this._run(async () => {
        await this._settle();
        if (this._player && this._started && this._isActive(this._player.status)) {
          this._player.pause();
        }
      });
    }

    async _seek(seconds) {
      if (!this._player) return;
      this._emit("seeking");
      const milliseconds = Math.max(0, Math.round(seconds * 1000));
      try {
        await this._player.seek(BigInt(milliseconds));
      } catch (error) {
        await this._player.seek(milliseconds);
      }
      this._currentTime = seconds;
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
      }).catch((error) => this._emit("error", error)).finally(() => {
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
      return this._run(async () => {
        const streams = this.getAudioStreams();
        const selected = streams[index];
        if (!selected || !this._player) throw new Error("Audio track is unavailable");
        await this._settle();
        await this._player.selectAudio(selected.id);
        await this._settle();
        return selected;
      });
    }

    selectSubtitleByIndex(index) {
      return this._run(async () => {
        const selected = this.getSubtitleStreams()[index];
        if (!selected || !this._player) throw new Error("Subtitle track is unavailable");
        await this._settle();
        await this._player.selectSubtitle(selected.id);
        this._subtitleEnabled = true;
        if (typeof this._player.setSubtitleEnable === "function") {
          this._player.setSubtitleEnable(true);
        }
        return selected;
      });
    }

    setSubtitleEnabled(enabled) {
      const nextEnabled = Boolean(enabled);
      this._subtitleEnabled = nextEnabled;
      if (!this._player || typeof this._player.setSubtitleEnable !== "function") {
        return Promise.resolve();
      }
      return this._run(async () => {
        await this._settle();
        this._player.setSubtitleEnable(nextEnabled);
      });
    }

    load() {
      if (this._source) return this.open(this._source);
      return Promise.resolve(this);
    }

    get paused() { return this._paused; }
    get ended() { return this._ended; }
    get seeking() { return false; }
    get readyState() { return this._readyState; }
    get duration() { return this._duration; }
    get currentTime() { return this._currentTime; }
    set currentTime(value) {
      const target = Number(value);
      if (!Number.isFinite(target) || target < 0) return;
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
      const duration = Number.isFinite(this._duration) ? this._duration : 0;
      return {
        length: duration > 0 ? 1 : 0,
        start: () => 0,
        end: () => duration,
      };
    }
    get videoWidth() {
      const stream = this._streams.find((item) => item && [0, "Video"].includes(item.mediaType));
      return Number(stream && (stream.codecparProxy?.width || stream.width)) || this.clientWidth;
    }
    get videoHeight() {
      const stream = this._streams.find((item) => item && [0, "Video"].includes(item.mediaType));
      return Number(stream && (stream.codecparProxy?.height || stream.height)) || this.clientHeight;
    }
    get error() { return null; }

    async destroy() {
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
