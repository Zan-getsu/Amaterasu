// Run with: node --test tests/player_runtime.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

const source = readFileSync(resolve(__dirname, '../web/static/js/libmedia-player.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function fixture() {
  const instances = [];
  const scripts = [];
  class FakePlayer {
    constructor(options) {
      this.options = options;
      instances.push(this);
      this.events = {};
      this.calls = [];
      this.status = 0;
      this.audio = this.subtitle = -1;
    }
    on(event, callback) { this.events[event] = callback; }
    getStatus() { return this.status; }
    async load() { this.calls.push('load'); this.status = 3; await this.loadGate; this.status = 4; }
    getDuration() { return 120000n; }
    getStreams() {
      return [
        { mediaType: 'Video', id: 0, codecparProxy: { width: 1920, height: 1080 } },
        { mediaType: 'Audio', id: 12 }, { mediaType: 'Audio', id: 14 },
        { mediaType: 'Subtitle', id: 22 }, { mediaType: 'Subtitle', id: 28 },
      ];
    }
    async play() {
      assert.ok([4, 7, 8].includes(this.status), 'must load before play');
      this.calls.push('play');
      this.audio = this.audio < 0 ? 12 : this.audio;
      this.subtitle = this.subtitle < 0 ? 22 : this.subtitle;
      this.status = 6;
      this.subtitleEnabled = true; // AVPlayer restarts subtitles on resume and seek.
      this.events.played?.();
    }
    async pause() { this.calls.push('pause'); this.status = 8; this.events.paused?.(); }
    async selectAudio(id) {
      assert.notEqual(this.audio, -1, 'audio renderer exists only after play');
      this.calls.push(`audio:${id}`); this.audio = id;
      this.subtitleEnabled = true; // Codec-changing selections can seek internally.
    }
    async selectSubtitle(id) {
      assert.notEqual(this.subtitle, -1, 'subtitle renderer exists only after play');
      this.calls.push(`subtitle:${id}`); await this.subtitleGate; this.subtitle = id;
    }
    getSelectedAudioStreamId() { return this.audio; }
    getSelectedSubtitleStreamId() { return this.subtitle; }
    setSubtitleEnable(value) { this.subtitleEnabled = value; }
    setSubtitleDelay(value) { this.subtitleDelay = value; }
    setVolume(value) { this.volume = value; }
    setPlaybackRate(value) { this.rate = value; }
    async seek(value) {
      assert.equal(typeof value, 'bigint');
      this.calls.push(`seek:${value}`);
      await this.seekGate;
      if (this.seekError) throw this.seekError;
      this.subtitleEnabled = true;
    }
    async destroy() { this.calls.push('destroy'); this.status = 2; }
  }
  class Element extends EventTarget {
    attachShadow() { return { append() {} }; }
  }
  const context = vm.createContext({
    HTMLElement: Element, Event, DOMException, console,
    CustomEvent: class extends Event { constructor(type, options) { super(type); this.detail = options.detail; } },
    document: {
      createElement: () => ({ querySelector: () => null }),
      head: { appendChild: script => scripts.push(script) },
    },
    customElements: { get() {}, define() {} },
    window: { AVPlayer: FakePlayer, setTimeout },
  });
  vm.runInContext(source, context);
  return { adapter: new context.window.AmaterasuLibmediaPlayer(), instances, context, scripts };
}

test('initial tracks wait for renderers and preserve source resolution and volume', async () => {
  const { adapter, instances } = fixture();
  await adapter.open('/stream', { audioIndex: 1, subtitleIndex: 1, currentTime: 30, volume: 0.4 });
  assert.equal(instances[0].options.enableWorker, false, 'avoid AVPlayer 1.3.1 subtitle packet proxy bug');
  assert.deepEqual(instances[0].calls, ['load']);
  await adapter.play();
  assert.deepEqual(instances[0].calls, ['load', 'play', 'audio:14', 'subtitle:28', 'seek:30000']);
  assert.equal(instances[0].volume, 0.4);
  assert.equal(adapter.currentTime, 30);
  assert.equal(adapter.videoWidth, 1920);
  assert.equal(adapter.videoHeight, 1080);
  assert.equal(adapter.buffered.length, 0, 'unknown buffer must not advertise a fully downloaded file');
});

test('off remains off after resume and seek; paused track selection waits for play', async () => {
  const { adapter, instances } = fixture();
  await adapter.open('/stream');
  await adapter.selectSubtitleByIndex(1);
  assert.equal(instances[0].subtitle, -1);
  await adapter.play();
  assert.equal(instances[0].subtitle, 28);
  await adapter.setSubtitleEnabled(false);
  await adapter.pause();
  await adapter.play();
  assert.equal(instances[0].subtitleEnabled, false);
  adapter.currentTime = 40;
  await tick();
  assert.equal(instances[0].subtitleEnabled, false);
  await adapter.selectAudioByIndex(1);
  assert.equal(instances[0].subtitleEnabled, false, 'audio switching must not restart disabled subtitles');
  adapter.setSubtitleDelay(0.75);
  assert.equal(instances[0].subtitleDelay, 750);
});

test('latest seek wins while old playback timestamps arrive', async () => {
  const { adapter, instances } = fixture();
  await adapter.open('/stream', { autoplay: true });
  const gate = deferred();
  instances[0].seekGate = gate.promise;
  adapter.currentTime = 10;
  await tick();
  adapter.currentTime = 20;
  adapter.currentTime = 30;
  instances[0].events.time(2000n);
  assert.equal(adapter.currentTime, 30);
  assert.equal(adapter.seeking, true);
  gate.resolve();
  await tick();
  assert.deepEqual(instances[0].calls.filter(call => call.startsWith('seek:')), ['seek:10000', 'seek:30000']);
  assert.equal(adapter.currentTime, 30);
  assert.equal(adapter.seeking, false);
});

test('seek failure is reported once without repeating a decoder operation', async () => {
  const { adapter, instances } = fixture();
  await adapter.open('/stream', { autoplay: true });
  instances[0].seekError = new Error('network unavailable');
  let errors = 0;
  adapter.addEventListener('error', () => { errors++; });
  adapter.currentTime = 10;
  await tick();
  assert.equal(errors, 1);
  assert.equal(adapter.error.message, 'network unavailable');
  assert.equal(instances[0].calls.filter(call => call.startsWith('seek:')).length, 1);
  assert.equal(adapter.seeking, false);
});

test('retry serializes loading and playback, preserving position and selected tracks', async () => {
  const { adapter, instances } = fixture();
  await adapter.open('/stream', { audioIndex: 1, subtitleIndex: 1, autoplay: true });
  adapter.currentTime = 35;
  await tick();
  await Promise.all([adapter.load(), adapter.play()]);
  assert.deepEqual(instances[1].calls, ['load', 'play', 'audio:14', 'subtitle:28', 'seek:35000']);
  instances[0].events.time(999000n);
  assert.equal(adapter.currentTime, 35, 'retired player events must not change the current position');
});

test('destroy invalidates pending commands and a late load cannot resurrect playback', async () => {
  const { adapter, instances } = fixture();
  const opening = adapter.open('/stream');
  await Promise.resolve();
  await Promise.resolve();
  const closing = adapter.destroy();
  await assert.rejects(opening, { name: 'AbortError' });
  await closing;
  assert.equal(adapter._player, null);
  assert.ok(instances.every(player => !player.calls.includes('play')));
});

test('subtitle off queued behind a slow selection is the final renderer state', async () => {
  const { adapter, instances } = fixture();
  await adapter.open('/stream', { autoplay: true });
  const gate = deferred();
  instances[0].subtitleGate = gate.promise;
  const selecting = adapter.selectSubtitleByIndex(1);
  await tick();
  const disabling = adapter.setSubtitleEnabled(false);
  gate.resolve();
  await Promise.all([selecting, disabling]);
  assert.equal(instances[0].subtitleEnabled, false);
});

test('a failed decoder script download can be retried', async () => {
  const { adapter, context, scripts } = fixture();
  const Player = context.window.AVPlayer;
  delete context.window.AVPlayer;
  const first = adapter.open('/stream');
  await tick();
  scripts[0].onerror();
  await assert.rejects(first, /could not be loaded/);
  const retry = adapter.open('/stream');
  await tick();
  assert.equal(scripts.length, 2);
  context.window.AVPlayer = Player;
  scripts[1].onload();
  await retry;
  assert.equal(adapter.readyState, 4);
});
