// Encoding Profile Creator — Full Feature Implementation
(function() {
  const previewCode = document.getElementById('preview-code');
  const previewLang = document.getElementById('preview-lang');
  const tabJson = document.getElementById('tab-json');
  const tabCmd = document.getElementById('tab-cmd');
  let currentMode = 'json';

  // --- DATABASE AND API LOGIC ---
  const urlParams = new URLSearchParams(window.location.search);
  const userId = urlParams.get('user_id') || '';
  const token = urlParams.get('token') || '';
  const isOfflineMode = !userId || !token;
  const LOCAL_STORAGE_KEY = 'amaterasu_encoding_profiles';

  let currentProfileId = null;
  let cachedProfiles = {};

  // Internal state for stream tag builders
  let metadataTagList = [];  // [{key: "s:v:0", value: "title=..."}]
  let dispositionTagList = []; // [{key: "v:0", value: "default"}]

  const generateId = () => Math.random().toString(36).substring(2, 10);
  const apiPath = (path) => `${path}?user_id=${userId}&token=${token}`;

  async function responseError(response, action) {
    let detail = '';
    try {
      const body = await response.json();
      detail = body.detail || body.error || '';
    } catch (_) {
      detail = await response.text().catch(() => '');
    }
    return new Error(detail || `${action} failed with HTTP ${response.status}`);
  }

  // ========================================================================
  //  PRESETS & OPTIONS
  // ========================================================================
  const QUICK_PRESETS = [
    {
      name: "🎯 H.265 Balanced",
      video_codec: "libx265", audio_codec: "aac", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 23, preset: "medium", pix_fmt: "yuv420p" },
      audio_params: { bitrate: "192k" }
    },
    {
      name: "💎 H.265 High Quality",
      video_codec: "libx265", audio_codec: "flac", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 18, preset: "slow", pix_fmt: "yuv420p10le" },
      audio_params: {}
    },
    {
      name: "⚡ H.264 Fast Encode",
      video_codec: "libx264", audio_codec: "aac", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 20, preset: "veryfast", pix_fmt: "yuv420p" },
      audio_params: { bitrate: "192k" }
    },
    {
      name: "🚀 AV1 Balanced",
      video_codec: "libsvtav1", audio_codec: "libopus", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 30, preset: 6, pix_fmt: "yuv420p10le", keyint_seconds: 10, fast_decode: true },
      audio_params: { bitrate: "128k", vbr: true }
    },
    {
      name: "🎌 Anime Encode",
      video_codec: "libx265", audio_codec: "libopus", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 20, preset: "slow", pix_fmt: "yuv420p10le", extra_params: "tune=animation" },
      audio_params: { bitrate: "192k" }
    },
    {
      name: "🌐 Web Streaming",
      video_codec: "libx264", audio_codec: "aac", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 23, preset: "fast", pix_fmt: "yuv420p", profile: "high", level: "4.1", extra_params: "tune=zerolatency" },
      audio_params: { bitrate: "128k" }
    }
  ];

  const SVT_AV1_PRESETS = Array.from({ length: 14 }, (_, i) => ({
    value: i,
    label: `Preset ${i} ${i < 4 ? '(Slowest)' : i > 9 ? '(Fastest)' : ''}`
  }));

  const X264_X265_PRESETS = [
    { value: "veryslow", label: "Very Slow" },
    { value: "slower", label: "Slower" },
    { value: "slow", label: "Slow" },
    { value: "medium", label: "Medium" },
    { value: "fast", label: "Fast" },
    { value: "faster", label: "Faster" },
    { value: "veryfast", label: "Very Fast" },
    { value: "superfast", label: "Super Fast" },
    { value: "ultrafast", label: "Ultra Fast" }
  ];

  const VIDEO_PROFILE_OPTIONS = {
    libsvtav1: [{ value: '0', label: 'Main (4:2:0)' }],
    libx264: [
      { value: 'baseline', label: 'Baseline' },
      { value: 'main', label: 'Main' },
      { value: 'high', label: 'High' },
      { value: 'high10', label: 'High 10' }
    ],
    libx265: [
      { value: 'main', label: 'Main' },
      { value: 'main10', label: 'Main 10' }
    ]
  };

  const PIXEL_FORMAT_OPTIONS = {
    libsvtav1: [
      { value: 'yuv420p10le', label: '10-bit YUV 4:2:0 (Recommended)' },
      { value: 'yuv420p', label: '8-bit YUV 4:2:0 (Standard)' }
    ],
    libx264: [
      { value: 'yuv420p', label: '8-bit YUV 4:2:0 (Most compatible)' },
      { value: 'yuv420p10le', label: '10-bit YUV 4:2:0' },
      { value: 'yuv422p', label: '8-bit YUV 4:2:2' },
      { value: 'yuv444p', label: '8-bit YUV 4:4:4' }
    ],
    libx265: [
      { value: 'yuv420p10le', label: '10-bit YUV 4:2:0 (Recommended)' },
      { value: 'yuv420p', label: '8-bit YUV 4:2:0 (Standard)' },
      { value: 'yuv422p', label: '8-bit YUV 4:2:2' },
      { value: 'yuv444p', label: '8-bit YUV 4:4:4' }
    ],
    'libvpx-vp9': [
      { value: 'yuv420p10le', label: '10-bit YUV 4:2:0' },
      { value: 'yuv420p', label: '8-bit YUV 4:2:0' },
      { value: 'yuv422p', label: '8-bit YUV 4:2:2' },
      { value: 'yuv444p', label: '8-bit YUV 4:4:4' }
    ],
    mpeg4: [{ value: 'yuv420p', label: '8-bit YUV 4:2:0' }],
    copy: []
  };

  const DISPOSITION_OPTIONS = [
    { label: "0 (Remove all flags)", value: "0" },
    { label: "default (Mark as default)", value: "default" },
    { label: "forced (Mark as forced)", value: "forced" },
    { label: "default+forced", value: "default+forced" },
    { label: "dub (Dub track)", value: "dub" },
    { label: "comment (Commentary)", value: "comment" },
    { label: "hearing_impaired", value: "hearing_impaired" },
    { label: "visual_impaired", value: "visual_impaired" },
    { label: "captions", value: "captions" }
  ];

  const LANGUAGES = [
    { value: 'eng', label: 'English (eng)' },
    { value: 'jpn', label: 'Japanese (jpn)' },
    { value: 'spa', label: 'Spanish (spa)' },
    { value: 'fra', label: 'French (fra)' },
    { value: 'ger', label: 'German (ger)' },
    { value: 'ita', label: 'Italian (ita)' },
    { value: 'kor', label: 'Korean (kor)' },
    { value: 'chi', label: 'Chinese (chi)' },
    { value: 'rus', label: 'Russian (rus)' },
    { value: 'ara', label: 'Arabic (ara)' },
    { value: 'hin', label: 'Hindi (hin)' },
    { value: 'por', label: 'Portuguese (por)' },
    { value: 'und', label: 'Undefined (und)' }
  ];

  const standardMetadataKeys = ['title', 'v_track', 'a_track', 's_track'];

  // ========================================================================
  //  API LAYER
  // ========================================================================
  const profileApi = {
    list: async () => {
      if (!isOfflineMode) {
        try {
          const res = await fetch(apiPath('/api/profiles'));
          if (res.ok) return await res.json();
        } catch (e) { console.error("API error, falling back to local", e); }
      }
      const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
      return stored ? JSON.parse(stored) : {};
    },
    save: async (id, data) => {
      if (!isOfflineMode) {
        try {
          const method = id ? 'PUT' : 'POST';
          const url = id ? `/api/profiles/${id}` : '/api/profiles';
          const res = await fetch(apiPath(url), {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
          });
          if (res.ok) {
            const result = await res.json();
            return result.id || id;
          }
          throw await responseError(res, 'Saving profile');
        } catch (e) {
          console.error("Profile API save failed", e);
          throw e;
        }
      }
      const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
      const profiles = stored ? JSON.parse(stored) : {};
      const newId = id || generateId();
      profiles[newId] = { ...data, updatedAt: new Date().toISOString() };
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
      return newId;
    },
    delete: async (id) => {
      if (!isOfflineMode) {
        try {
          const res = await fetch(apiPath(`/api/profiles/${id}`), { method: 'DELETE' });
          if (res.ok) return;
          throw await responseError(res, 'Deleting profile');
        } catch (e) {
          console.error("Profile API delete failed", e);
          throw e;
        }
      }
      const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (stored) {
        const profiles = JSON.parse(stored);
        delete profiles[id];
        localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
      }
    },
    setDefault: async (id) => {
      if (!isOfflineMode) {
        try {
          const res = await fetch(apiPath(`/api/profiles/${id}/default`), { method: 'POST' });
          if (res.ok) return;
          throw await responseError(res, 'Setting default profile');
        } catch (e) {
          console.error("Profile API default update failed", e);
          throw e;
        }
      }
      const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (stored) {
        const profiles = JSON.parse(stored);
        Object.keys(profiles).forEach(k => profiles[k].is_default = false);
        if (profiles[id]) profiles[id].is_default = true;
        localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
      }
    }
  };

  // ========================================================================
  //  QUICK PRESETS RENDERING
  // ========================================================================
  const presetsContainer = document.getElementById('quick-presets-container');
  if (presetsContainer) {
    QUICK_PRESETS.forEach((preset, idx) => {
      const card = document.createElement('button');
      card.className = 'preset-card';
      card.innerHTML = `
        <div class="preset-card-name">${preset.name}</div>
        <div class="preset-card-desc">${preset.video_codec} · ${preset.audio_codec}</div>
      `;
      card.addEventListener('click', () => applyPreset(preset));
      presetsContainer.appendChild(card);
    });
  }

  function applyPreset(preset) {
    // Set basic fields
    setVal('v-codec', preset.video_codec);
    setVal('a-codec', preset.audio_codec);
    setVal('s-mode', preset.subtitle_mode);

    // Reset every codec-specific field so values from the previously selected
    // profile cannot leak into this preset and create an invalid combination.
    const videoParams = preset.video_params || {};
    updatePresetDropdown();
    setVal('v-crf', videoParams.crf ?? 23);
    setVal('v-preset-select', videoParams.preset ?? (preset.video_codec === 'libsvtav1' ? 6 : 'medium'));
    setVal('v-pix_fmt', videoParams.pix_fmt || (preset.video_codec === 'libsvtav1' ? 'yuv420p10le' : 'yuv420p'));
    setVal('v-profile', videoParams.profile ?? '');
    setVal('v-level', videoParams.level || '');
    setVal('v-color-prim', videoParams.color_primaries || '');
    setVal('v-color-trc', videoParams.color_trc || '');
    setVal('v-colorspace', videoParams.colorspace || '');
    setVal('v-fps-mode', videoParams.fps_mode || 'vfr');
    setVal('v-extra', videoParams.extra_params || '');
    setVal('v-keyint-seconds', videoParams.keyint_seconds || 10);
    alignPixelFormatForProfile();
    const fastDecodeEl = document.getElementById('v-fast-decode');
    if (fastDecodeEl) fastDecodeEl.checked = videoParams.fast_decode !== false;
    updateCRFDisplay();
    updatePresetDisplay();

    // Audio params
    const audioParams = preset.audio_params || {};
    setVal('a-bitrate', audioParams.bitrate || (preset.audio_codec === 'libopus' ? '128k' : '192k'));
    setVal('a-channels', audioParams.channels ?? 2);
    const vbrEl = document.getElementById('a-vbr');
    if (vbrEl) vbrEl.checked = preset.audio_codec === 'libopus' && Boolean(audioParams.vbr);

    // Clear tag builders
    metadataTagList = [];
    dispositionTagList = [];

    // Populate custom metadata from preset
    if (preset.metadata) {
      Object.entries(preset.metadata).forEach(([k, v]) => {
        if (!standardMetadataKeys.includes(k.trim())) {
          metadataTagList.push({ key: k, value: String(v) });
        }
      });
    }

    renderAllTagBuilders();
    updateConditionalVisibility();
    generatePreview();

    if (typeof showToast === 'function') showToast(`Applied preset: ${preset.name}`);
  }

  // ========================================================================
  //  ACCORDION
  // ========================================================================
  document.querySelectorAll('.acc-trigger').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const isOpen = trigger.classList.contains('open');
      trigger.classList.toggle('open', !isOpen);
      trigger.nextElementSibling.style.display = isOpen ? 'none' : 'block';
    });
  });

  // ========================================================================
  //  CHIPS
  // ========================================================================
  window.insertChip = function (targetId, value) {
    const el = document.getElementById(targetId);
    if (el) {
      el.value = el.value + value;
      generatePreview();
    }
  };

  // ========================================================================
  //  DYNAMIC PRESET DROPDOWN
  // ========================================================================
  function updatePresetDropdown() {
    const codec = getVal('v-codec');
    const presetSelect = document.getElementById('v-preset-select');
    if (!presetSelect) return;

    let options;
    if (codec === 'libsvtav1') {
      options = SVT_AV1_PRESETS;
    } else if (codec === 'libx264' || codec === 'libx265') {
      options = X264_X265_PRESETS;
    } else {
      options = [];
    }

    presetSelect.innerHTML = '';
    options.forEach(opt => {
      const o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      presetSelect.appendChild(o);
    });

    // Set default preset value
    if (codec === 'libsvtav1') {
      presetSelect.value = 6;
    } else if (codec === 'libx264' || codec === 'libx265') {
      presetSelect.value = 'medium';
    }

    updatePresetDisplay();
    updatePixelFormatOptions();
    updateProfileOptions();
  }

  function updatePixelFormatOptions() {
    const pixelSelect = document.getElementById('v-pix_fmt');
    if (!pixelSelect) return;
    const codec = getVal('v-codec');
    const options = PIXEL_FORMAT_OPTIONS[codec] || [];
    const current = pixelSelect.value;
    pixelSelect.innerHTML = '';
    options.forEach(option => {
      const element = document.createElement('option');
      element.value = option.value;
      element.textContent = option.label;
      pixelSelect.appendChild(element);
    });
    if (options.length) {
      pixelSelect.value = options.some(option => option.value === current)
        ? current
        : options[0].value;
    }
  }

  function alignPixelFormatForProfile() {
    const codec = getVal('v-codec');
    const profile = getVal('v-profile');
    if (codec === 'libx264' && profile) {
      setVal('v-pix_fmt', profile === 'high10' ? 'yuv420p10le' : 'yuv420p');
    } else if (codec === 'libx265' && profile) {
      setVal('v-pix_fmt', profile === 'main10' ? 'yuv420p10le' : 'yuv420p');
    }
  }

  function updateProfileOptions() {
    const profileSelect = document.getElementById('v-profile');
    if (!profileSelect) return;
    const current = profileSelect.value;
    const options = VIDEO_PROFILE_OPTIONS[getVal('v-codec')] || [];
    profileSelect.innerHTML = '<option value="">Default / Auto</option>';
    options.forEach(option => {
      const element = document.createElement('option');
      element.value = option.value;
      element.textContent = option.label;
      profileSelect.appendChild(element);
    });
    profileSelect.value = options.some(option => option.value === current) ? current : '';
  }

  function updatePresetDisplay() {
    const presetVal = document.getElementById('v-preset-val');
    const presetSelect = document.getElementById('v-preset-select');
    if (presetVal && presetSelect) {
      presetVal.textContent = presetSelect.value;
    }
  }

  // ========================================================================
  //  CRF DISPLAY
  // ========================================================================
  function updateCRFDisplay() {
    const crfEl = document.getElementById('v-crf');
    const crfVal = document.getElementById('v-crf-val');
    const crfHint = document.getElementById('v-crf-hint');
    if (!crfEl || !crfVal) return;

    const val = parseInt(crfEl.value);
    crfVal.textContent = val;

    if (crfHint) {
      if (val < 18) crfHint.textContent = 'Near lossless — very large file size';
      else if (val <= 22) crfHint.textContent = 'High quality — larger file size';
      else if (val <= 28) crfHint.textContent = 'Good balance of quality and size';
      else if (val <= 35) crfHint.textContent = 'Smaller file — some quality loss';
      else crfHint.textContent = 'Low quality — small file size';
    }
  }

  const vCrf = document.getElementById('v-crf');
  if (vCrf) {
    vCrf.addEventListener('input', () => {
      updateCRFDisplay();
      generatePreview();
    });
  }

  const vPresetSelect = document.getElementById('v-preset-select');
  if (vPresetSelect) {
    vPresetSelect.addEventListener('change', () => {
      updatePresetDisplay();
      generatePreview();
    });
  }

  // ========================================================================
  //  CONDITIONAL FIELD VISIBILITY
  // ========================================================================
  function updateConditionalVisibility() {
    const vCodec = getVal('v-codec');
    const aCodec = getVal('a-codec');

    // Video: hide CRF, preset, pix_fmt when codec = copy
    const isVideoCopy = vCodec === 'copy';
    toggleEl('v-crf-group', !isVideoCopy);
    toggleEl('v-preset-group', !isVideoCopy && (vCodec === 'libsvtav1' || vCodec === 'libx264' || vCodec === 'libx265'));
    toggleEl('v-av1-playback-group', vCodec === 'libsvtav1');

    // Audio: VBR is an explicit switch only for the libopus encoder.
    const isAudioCopy = aCodec === 'copy';
    const isFlac = aCodec === 'flac';
    toggleEl('a-bitrate-group', !isAudioCopy && !isFlac);
    toggleEl('a-channels-group', !isAudioCopy);
    toggleEl('a-vbr-group', aCodec === 'libopus');
  }

  function toggleEl(id, show) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('hidden', !show);
  }

  // Listen for codec changes
  document.getElementById('v-codec')?.addEventListener('change', () => {
    updatePresetDropdown();
    updateConditionalVisibility();
    generatePreview();
  });
  document.getElementById('v-profile')?.addEventListener('change', () => {
    alignPixelFormatForProfile();
    generatePreview();
  });
  document.getElementById('a-codec')?.addEventListener('change', () => {
    updateConditionalVisibility();
    generatePreview();
  });
  
  // Listen for channel changes
  document.getElementById('a-channels')?.addEventListener('change', (e) => {
    if (e.target.value === '0') {
      const vbrEl = document.getElementById('a-vbr');
      if (vbrEl) vbrEl.checked = false;
    }
    generatePreview();
  });

  // ========================================================================
  //  TRACK SELECTOR DROPDOWNS
  // ========================================================================
  document.querySelectorAll('.track-selector-dropdown').forEach(sel => {
    sel.addEventListener('change', () => {
      const targetId = sel.dataset.target;
      const customInput = document.getElementById(targetId);
      if (sel.value === 'custom') {
        if (customInput) {
          customInput.style.display = 'block';
          customInput.value = '';
          customInput.focus();
        }
      } else {
        if (customInput) {
          customInput.style.display = 'none';
          customInput.value = sel.value === '?' ? '' : sel.value;
        }
      }
      generatePreview();
    });
  });

  // ========================================================================
  //  STREAM TAG BUILDER
  // ========================================================================
  function matchesPrefix(key, prefix) {
    const trimmed = key.trim();
    if (!trimmed.startsWith(prefix)) return false;
    const remainder = trimmed.slice(prefix.length);
    return /^[\d?]+$/.test(remainder);
  }

  function renderAllTagBuilders() {
    // Metadata tags
    ['s:v:', 's:a:', 's:s:'].forEach(prefix => {
      const container = document.querySelector(`.tag-builder-rows[data-prefix="${prefix}"]`);
      if (container) renderMetaTagRows(container, prefix);
    });

    // Disposition tags
    ['v:', 'a:', 's:'].forEach(prefix => {
      const container = document.querySelector(`.tag-builder-rows[data-prefix="${prefix}"]`);
      if (container) renderDispTagRows(container, prefix);
    });

    refreshIcons();
  }

  function renderMetaTagRows(container, prefix) {
    const localItems = metadataTagList.filter(item => matchesPrefix(item.key, prefix));

    if (localItems.length === 0) {
      container.innerHTML = '<div class="tag-builder-empty">No metadata tags. Click "Add Tag" to add one.</div>';
      return;
    }

    container.innerHTML = '';
    localItems.forEach((item, localIdx) => {
      const trackIndex = item.key.trim().slice(prefix.length);

      // Parse value: "title=SomeTitle" or "language=eng" or raw custom "BPS=120"
      const splitIdx = item.value.indexOf('=');
      let tagType = 'custom';
      let tagKey = item.value;
      let tagValue = '';
      if (splitIdx !== -1) {
        tagKey = item.value.substring(0, splitIdx);
        tagValue = item.value.substring(splitIdx + 1);
        if (['title', 'language', 'handler_name'].includes(tagKey)) {
          tagType = tagKey;
        }
      }

      const row = document.createElement('div');
      row.className = 'tag-row';
      row.dataset.prefix = prefix;
      row.dataset.localIdx = localIdx;

      // Track selector
      let trackHtml = `<select class="tag-track" data-field="track">
        <option value="0" ${trackIndex === '0' ? 'selected' : ''}>Track 1</option>
        <option value="1" ${trackIndex === '1' ? 'selected' : ''}>Track 2</option>
        <option value="2" ${trackIndex === '2' ? 'selected' : ''}>Track 3</option>
        <option value="3" ${trackIndex === '3' ? 'selected' : ''}>Track 4</option>
        <option value="?" ${trackIndex === '?' ? 'selected' : ''}>All (?)</option>
      </select>`;

      // Tag type
      let typeHtml = `<select class="tag-type" data-field="type">
        <option value="title" ${tagType === 'title' ? 'selected' : ''}>Title</option>
        <option value="language" ${tagType === 'language' ? 'selected' : ''}>Language</option>
        <option value="handler_name" ${tagType === 'handler_name' ? 'selected' : ''}>Handler</option>
        <option value="custom" ${tagType === 'custom' ? 'selected' : ''}>Custom</option>
      </select>`;

      // Value field (depends on tag type)
      let valueHtml;
      if (tagType === 'language') {
        let langOptions = LANGUAGES.map(l =>
          `<option value="${l.value}" ${tagValue === l.value ? 'selected' : ''}>${l.label}</option>`
        ).join('');
        valueHtml = `<select class="tag-value" data-field="value"><option value="" disabled>Select Language...</option>${langOptions}</select>`;
      } else if (tagType === 'custom') {
        valueHtml = `<input type="text" class="tag-value" data-field="value" placeholder="e.g. BPS=120" value="${escHtml(item.value)}">`;
      } else {
        valueHtml = `<input type="text" class="tag-value" data-field="value" placeholder="Enter ${tagType}..." value="${escHtml(tagValue)}">`;
      }

      row.innerHTML = `${trackHtml}${typeHtml}${valueHtml}<button type="button" class="tag-remove" title="Remove"><i data-lucide="trash-2" style="width:14px;height:14px;"></i></button>`;
      container.appendChild(row);
    });
  }

  function renderDispTagRows(container, prefix) {
    const localItems = dispositionTagList.filter(item => matchesPrefix(item.key, prefix));

    if (localItems.length === 0) {
      container.innerHTML = '<div class="tag-builder-empty">No disposition flags. Click "Add Flag" to add one.</div>';
      return;
    }

    container.innerHTML = '';
    localItems.forEach((item, localIdx) => {
      const trackIndex = item.key.trim().slice(prefix.length);

      const row = document.createElement('div');
      row.className = 'tag-row';
      row.dataset.prefix = prefix;
      row.dataset.localIdx = localIdx;

      let trackHtml = `<select class="tag-track" data-field="track">
        <option value="0" ${trackIndex === '0' ? 'selected' : ''}>Track 1</option>
        <option value="1" ${trackIndex === '1' ? 'selected' : ''}>Track 2</option>
        <option value="2" ${trackIndex === '2' ? 'selected' : ''}>Track 3</option>
        <option value="3" ${trackIndex === '3' ? 'selected' : ''}>Track 4</option>
        <option value="?" ${trackIndex === '?' ? 'selected' : ''}>All (?)</option>
      </select>`;

      let dispOptions = DISPOSITION_OPTIONS.map(d =>
        `<option value="${d.value}" ${item.value === d.value ? 'selected' : ''}>${d.label}</option>`
      ).join('');
      let valueHtml = `<select class="tag-value" data-field="value"><option value="" disabled ${!item.value ? 'selected' : ''}>Select disposition...</option>${dispOptions}</select>`;

      row.innerHTML = `${trackHtml}${valueHtml}<button type="button" class="tag-remove" title="Remove"><i data-lucide="trash-2" style="width:14px;height:14px;"></i></button>`;
      container.appendChild(row);
    });
  }

  // Event delegation for tag builder interactions
  document.addEventListener('click', (e) => {
    // Add metadata tag
    const addMetaBtn = e.target.closest('[data-add-meta]');
    if (addMetaBtn) {
      const stream = addMetaBtn.dataset.addMeta;
      const prefix = `s:${stream}:`;
      metadataTagList.push({ key: `${prefix}0`, value: 'title=' });
      renderAllTagBuilders();
      generatePreview();
      return;
    }

    // Add disposition tag
    const addDispBtn = e.target.closest('[data-add-disp]');
    if (addDispBtn) {
      const stream = addDispBtn.dataset.addDisp;
      const prefix = `${stream}:`;
      dispositionTagList.push({ key: `${prefix}0`, value: '' });
      renderAllTagBuilders();
      generatePreview();
      return;
    }

    // Remove tag
    const removeBtn = e.target.closest('.tag-remove');
    if (removeBtn) {
      const row = removeBtn.closest('.tag-row');
      const container = row.closest('.tag-builder-rows');
      const prefix = container.dataset.prefix;

      // Determine if metadata or disposition
      const isDisp = !prefix.startsWith('s:');

      // Get current local items for this prefix
      const sourceList = isDisp ? dispositionTagList : metadataTagList;
      const localItems = sourceList.filter(item => matchesPrefix(item.key, prefix));
      const localIdx = parseInt(row.dataset.localIdx);

      // Find actual index in global list
      let count = 0;
      for (let i = 0; i < sourceList.length; i++) {
        if (matchesPrefix(sourceList[i].key, prefix)) {
          if (count === localIdx) {
            sourceList.splice(i, 1);
            break;
          }
          count++;
        }
      }

      renderAllTagBuilders();
      generatePreview();
      return;
    }
  });

  // Event delegation for tag builder field changes
  document.addEventListener('change', (e) => {
    const row = e.target.closest('.tag-row');
    if (!row) return;

    const container = row.closest('.tag-builder-rows');
    if (!container) return;

    const prefix = container.dataset.prefix;
    const isDisp = !prefix.startsWith('s:');
    const sourceList = isDisp ? dispositionTagList : metadataTagList;
    const localItems = sourceList.filter(item => matchesPrefix(item.key, prefix));
    const localIdx = parseInt(row.dataset.localIdx);

    if (localIdx >= localItems.length) return;

    const field = e.target.dataset.field;
    const item = localItems[localIdx];

    if (field === 'track') {
      item.key = `${prefix}${e.target.value}`;
    } else if (field === 'value') {
      if (isDisp) {
        item.value = e.target.value;
      } else {
        // For metadata, just set the raw value
        item.value = e.target.value;
      }
    } else if (field === 'type') {
      // Tag type changed — reconstruct value
      const newType = e.target.value;
      const oldSplit = item.value.indexOf('=');
      const oldValue = oldSplit !== -1 ? item.value.substring(oldSplit + 1) : '';

      if (newType === 'custom') {
        item.value = item.value; // keep as-is
      } else {
        item.value = `${newType}=${oldValue}`;
      }

      // Re-render to swap the value field type
      renderAllTagBuilders();
    }

    generatePreview();
  });

  // Handle input events on tag value fields (for text inputs)
  document.addEventListener('input', (e) => {
    if (!e.target.matches('.tag-row .tag-value')) return;

    const row = e.target.closest('.tag-row');
    const container = row.closest('.tag-builder-rows');
    if (!container) return;

    const prefix = container.dataset.prefix;
    const isDisp = !prefix.startsWith('s:');
    const sourceList = isDisp ? dispositionTagList : metadataTagList;
    const localItems = sourceList.filter(item => matchesPrefix(item.key, prefix));
    const localIdx = parseInt(row.dataset.localIdx);

    if (localIdx >= localItems.length) return;
    localItems[localIdx].value = e.target.value;
    generatePreview();
  });

  // ========================================================================
  //  PROFILE JSON GENERATION
  // ========================================================================
  function getProfileJSON() {
    const vCodec = getVal('v-codec');
    const aCodec = getVal('a-codec');

    // Build metadata from tag list
    const metadata = {};
    const gTitle = getVal('g-title');
    if (gTitle) metadata.title = gTitle;

    // v_track, a_track, s_track from selectors
    const vTrack = getTrackValue('v');
    const aTrack = getTrackValue('a');
    const sTrack = getTrackValue('s');
    if (vTrack) metadata.v_track = vTrack;
    if (aTrack) metadata.a_track = aTrack;
    if (sTrack) metadata.s_track = sTrack;

    // Stream-scoped metadata tags
    metadataTagList.forEach(item => {
      if (item.key && item.value) {
        let uniqueKey = item.key.trim();
        while (metadata[uniqueKey] !== undefined) uniqueKey += ' ';
        metadata[uniqueKey] = item.value;
      }
    });

    // Build disposition
    const disposition = {};
    dispositionTagList.forEach(item => {
      if (item.key && item.value) {
        disposition[item.key.trim()] = item.value;
      }
    });

    const profile = {
      name: getVal('p-name') || "Custom Profile",
      rename: getVal('g-rename') || "",
      cover_image: getVal('g-cover') || "",
      video_codec: vCodec || "libx264",
      audio_codec: aCodec || "aac",
      subtitle_mode: getVal('s-mode') || "copy",
      metadata,
      video_params: {
        crf: parseInt(getVal('v-crf') || "23"),
        preset: vCodec === 'libsvtav1' ? parseInt(getVal('v-preset-select') || "6") : (getVal('v-preset-select') || "medium"),
        pix_fmt: getVal('v-pix_fmt') || "yuv420p",
        profile: getVal('v-profile') || "",
        level: getVal('v-level') || "",
        color_primaries: getVal('v-color-prim') || "",
        color_trc: getVal('v-color-trc') || "",
        colorspace: getVal('v-colorspace') || "",
        extra_params: getVal('v-extra') || "",
        keyint_seconds: vCodec === 'libsvtav1' ? parseInt(getVal('v-keyint-seconds') || "10") : undefined,
        fast_decode: vCodec === 'libsvtav1' ? (document.getElementById('v-fast-decode')?.checked !== false) : undefined,
        fps_mode: getVal('v-fps-mode') || "vfr"
      },
      audio_params: {
        bitrate: getVal('a-bitrate') || (aCodec === 'libopus' ? "128k" : "192k"),
        channels: parseInt(getVal('a-channels') || "2"),
        vbr: aCodec === 'libopus' && (document.getElementById('a-vbr')?.checked || false)
      }
    };

    if (Object.keys(disposition).length > 0) {
      profile.disposition = disposition;
    }

    // Clean up empty strings from video_params
    Object.keys(profile.video_params).forEach(k => {
      if (profile.video_params[k] === "") delete profile.video_params[k];
    });

    // Clean up empty rename/cover
    if (!profile.rename) delete profile.rename;
    if (!profile.cover_image) delete profile.cover_image;

    return profile;
  }

  function getTrackValue(stream) {
    const sel = document.getElementById(`m-${stream}_track-select`);
    const custom = document.getElementById(`m-${stream}_track`);
    if (!sel) return '';
    if (sel.value === 'custom') return custom?.value || '';
    if (sel.value === '?') return '';
    return sel.value;
  }

  // ========================================================================
  //  FFMPEG COMMAND GENERATION
  // ========================================================================
  function getFFmpegCmd(profile) {
    const useAutomaticTimestamps = profile.audio_codec === 'copy';
    let cmd = `ffmpeg -y -nostdin${useAutomaticTimestamps ? '' : ' -fflags +genpts'} -i input.mkv \\\n`;

    // Track mapping
    if (profile.metadata?.v_track) {
      cmd += `  -map 0:v:${profile.metadata.v_track === '?' ? '' : profile.metadata.v_track} \\\n`;
    }
    if (profile.metadata?.a_track) {
      cmd += `  -map 0:a:${profile.metadata.a_track === '?' ? '' : profile.metadata.a_track} \\\n`;
    }
    if (profile.metadata?.s_track && profile.subtitle_mode !== 'none') {
      cmd += `  -map 0:s:${profile.metadata.s_track === '?' ? '' : profile.metadata.s_track} \\\n`;
    }

    // Video
    cmd += `  -c:v ${profile.video_codec}`;
    if (profile.video_codec !== 'copy') {
      if (profile.video_params?.pix_fmt) cmd += ` -pix_fmt ${profile.video_params.pix_fmt}`;
      if (profile.video_codec === 'libsvtav1') {
        const svtParts = [];
        if (useAutomaticTimestamps) {
          if (profile.video_params?.preset !== undefined) svtParts.push(`preset=${profile.video_params.preset}`);
          if (profile.video_params?.crf !== undefined) svtParts.push(`crf=${profile.video_params.crf}`);
        } else {
          if (profile.video_params?.preset !== undefined) cmd += ` -preset ${profile.video_params.preset}`;
          if (profile.video_params?.crf !== undefined) cmd += ` -crf ${profile.video_params.crf}`;
        }
        let extraParams = String(profile.video_params?.extra_params || '').trim();
        if (useAutomaticTimestamps && profile.video_params?.fast_decode === false) {
          extraParams = extraParams.split(':').filter(part => !part.startsWith('fast-decode=')).join(':');
        }
        if (extraParams) svtParts.push(extraParams);
        if (profile.video_params?.fast_decode === true && !/(^|:)fast-decode=/.test(extraParams)) {
          svtParts.push(`fast-decode=${profile.video_params.fast_decode ? 1 : 0}`);
        } else if (!useAutomaticTimestamps && profile.video_params?.fast_decode === false && !/(^|:)fast-decode=/.test(extraParams)) {
          svtParts.push('fast-decode=0');
        }
        if (profile.video_params?.profile !== undefined && profile.video_params.profile !== '') {
          svtParts.push(`profile=${profile.video_params.profile}`);
        }
        if (profile.video_params?.level) {
          svtParts.push(`level=${String(profile.video_params.level).replace('.', '')}`);
        }
        if (svtParts.length) cmd += ` -svtav1-params "${svtParts.join(':')}"`;
      } else {
        if (profile.video_params?.crf !== undefined) cmd += ` -crf ${profile.video_params.crf}`;
        if (profile.video_params?.preset !== undefined && ['libx264', 'libx265'].includes(profile.video_codec)) {
          cmd += ` -preset ${profile.video_params.preset}`;
        }
        if (profile.video_codec === 'libvpx-vp9') cmd += ` -b:v 0`;
        if (profile.video_params?.extra_params && ['libx264', 'libx265'].includes(profile.video_codec)) {
          const codecParam = profile.video_codec === 'libx265' ? 'x265' : 'x264';
          cmd += ` -${codecParam}-params "${profile.video_params.extra_params}"`;
        }
      }
      if (profile.video_codec !== 'libsvtav1' && profile.video_params?.profile) {
        cmd += ` -profile:v ${profile.video_params.profile}`;
      }
      if (profile.video_codec !== 'libsvtav1' && profile.video_params?.level) {
        cmd += ` -level ${profile.video_params.level}`;
      }
      if (profile.video_params?.color_primaries) cmd += ` \\\n  -color_primaries ${profile.video_params.color_primaries}`;
      if (profile.video_params?.color_trc) cmd += ` -color_trc ${profile.video_params.color_trc}`;
      if (profile.video_params?.colorspace) cmd += ` -colorspace ${profile.video_params.colorspace}`;
      const fpsMode = profile.video_params?.fps_mode || 'vfr';
      if (!(useAutomaticTimestamps && ['auto', 'vfr'].includes(fpsMode))) {
        cmd += ` -fps_mode:v:0 ${fpsMode}`;
      }
    }
    cmd += ` \\\n`;

    // Audio
    cmd += `  -c:a ${profile.audio_codec}`;
    if (profile.audio_codec !== 'copy' && profile.audio_codec !== 'flac') {
      if (profile.audio_params?.bitrate) cmd += ` -b:a ${profile.audio_params.bitrate}`;
    }
    if (profile.audio_codec !== 'copy' && profile.audio_params?.channels) {
      cmd += ` -ac ${profile.audio_params.channels}`;
    }
    if (profile.audio_codec === 'libopus' && profile.audio_params?.vbr) {
      cmd += ` -vbr on`;
    }
    cmd += ` \\\n`;

    // Subtitles
    if (profile.subtitle_mode === 'none') {
      cmd += `  -sn \\\n`;
    } else if (profile.subtitle_mode === 'burn') {
      cmd += `  -vf subtitles=input.mkv \\\n`;
    } else {
      cmd += `  -c:s copy \\\n`;
    }

    // Global metadata
    if (profile.metadata?.title) {
      cmd += `  -metadata title="${profile.metadata.title}" \\\n`;
    }

    // Stream metadata tags
    if (profile.metadata) {
      Object.entries(profile.metadata).forEach(([k, v]) => {
        if (!standardMetadataKeys.includes(k.trim())) {
          if (k.includes(':')) {
            cmd += `  -metadata:${k.trim()} "${v}" \\\n`;
          } else {
            cmd += `  -metadata "${k}=${v}" \\\n`;
          }
        }
      });
    }

    // Disposition flags
    if (profile.disposition) {
      Object.entries(profile.disposition).forEach(([k, v]) => {
        cmd += `  -disposition:${k.trim()} ${v} \\\n`;
      });
    }

    cmd += `  -max_muxing_queue_size 4096`;
    if (!useAutomaticTimestamps) cmd += ` -avoid_negative_ts make_zero`;
    cmd += ` \\\n`;
    if (!useAutomaticTimestamps) cmd += `  -cluster_time_limit 5000 `;
    cmd += `output.mkv`;
    return cmd;
  }

  // ========================================================================
  //  PREVIEW
  // ========================================================================
  function generatePreview() {
    if (!previewCode) return;
    const profile = getProfileJSON();

    if (currentMode === 'json') {
      const exportData = { ...profile };
      delete exportData.is_default;
      previewCode.textContent = JSON.stringify(exportData, null, 2);
    } else {
      previewCode.textContent = getFFmpegCmd(profile);
    }
  }

  // Tabs
  if (tabJson && tabCmd) {
    tabJson.addEventListener('click', () => {
      currentMode = 'json';
      tabJson.classList.add('preview-tab--active');
      tabCmd.classList.remove('preview-tab--active');
      if (previewLang) previewLang.textContent = 'JSON';
      generatePreview();
    });
    tabCmd.addEventListener('click', () => {
      currentMode = 'ffmpeg';
      tabCmd.classList.add('preview-tab--active');
      tabJson.classList.remove('preview-tab--active');
      if (previewLang) previewLang.textContent = 'BASH';
      generatePreview();
    });
  }

  // Preview copy button
  document.getElementById('preview-copy-btn')?.addEventListener('click', () => {
    const text = previewCode?.textContent || '';
    navigator.clipboard.writeText(text).then(() => {
      if (typeof showToast === 'function') showToast("Copied to clipboard!");
    });
  });

  // ========================================================================
  //  LOAD PROFILE INTO FORM
  // ========================================================================
  function loadProfileIntoForm(id, data) {
    currentProfileId = id;

    // Basic fields
    setVal('p-name', data.name || 'Custom Profile');
    setVal('g-rename', data.rename || '');
    setVal('g-cover', data.cover_image || '');
    setVal('v-codec', data.video_codec || 'libx264');
    setVal('a-codec', data.audio_codec || 'aac');
    setVal('s-mode', data.subtitle_mode || 'copy');

    // Video params
    const videoParams = data.video_params || {};
    const isAv1 = getVal('v-codec') === 'libsvtav1';
    const isHevc = getVal('v-codec') === 'libx265';
    updatePresetDropdown();
    setVal('v-crf', videoParams.crf ?? (isAv1 ? 30 : (isHevc ? 24 : 23)));
    setVal('v-preset-select', videoParams.preset ?? (isAv1 ? 6 : 'medium'));
    setVal('v-pix_fmt', videoParams.pix_fmt || ((isAv1 || isHevc) ? 'yuv420p10le' : 'yuv420p'));
    setVal('v-profile', videoParams.profile ?? '');
    setVal('v-level', videoParams.level || '');
    setVal('v-color-prim', videoParams.color_primaries || '');
    setVal('v-color-trc', videoParams.color_trc || '');
    setVal('v-colorspace', videoParams.colorspace || '');
    setVal('v-fps-mode', videoParams.fps_mode || 'vfr');
    setVal('v-extra', videoParams.extra_params || '');
    setVal('v-keyint-seconds', videoParams.keyint_seconds || 10);
    alignPixelFormatForProfile();
    const fastDecodeEl = document.getElementById('v-fast-decode');
    const legacyTuneZero = String(videoParams.extra_params || '')
      .split(':').some(part => part.trim() === 'tune=0');
    if (fastDecodeEl) {
      fastDecodeEl.checked = videoParams.fast_decode !== undefined
        ? Boolean(videoParams.fast_decode)
        : !legacyTuneZero;
    }
    updateCRFDisplay();
    updatePresetDisplay();

    // Audio params
    const audioParams = data.audio_params || {};
    const isOpus = getVal('a-codec') === 'libopus';
    setVal('a-bitrate', audioParams.bitrate || (isOpus ? '128k' : '192k'));
    setVal('a-channels', audioParams.channels ?? 2);
    const vbrEl = document.getElementById('a-vbr');
    if (vbrEl) vbrEl.checked = isOpus && audioParams.vbr !== false;

    // Track selectors
    const profileMetadata = data.metadata || {};
    setVal('g-title', profileMetadata.title || '');
    setTrackSelector('v', profileMetadata.v_track || '');
    setTrackSelector('a', profileMetadata.a_track || '');
    setTrackSelector('s', profileMetadata.s_track || '');

    // Stream metadata tags
    metadataTagList = [];
    if (data.metadata) {
      Object.entries(data.metadata).forEach(([k, v]) => {
        if (!standardMetadataKeys.includes(k.trim())) {
          metadataTagList.push({ key: k, value: String(v) });
        }
      });
    }

    // Disposition tags
    dispositionTagList = [];
    if (data.disposition) {
      Object.entries(data.disposition).forEach(([k, v]) => {
        dispositionTagList.push({ key: k, value: String(v) });
      });
    }

    renderAllTagBuilders();
    updateConditionalVisibility();
    updateDeleteButton();
    generatePreview();
  }

  function setTrackSelector(stream, value) {
    const sel = document.getElementById(`m-${stream}_track-select`);
    const custom = document.getElementById(`m-${stream}_track`);
    if (!sel) return;

    if (!value || value === '?') {
      sel.value = '?';
      if (custom) custom.style.display = 'none';
    } else {
      // Check if it matches a preset option
      const presetOpt = Array.from(sel.options).find(o => o.value === value && o.value !== 'custom');
      if (presetOpt) {
        sel.value = value;
        if (custom) custom.style.display = 'none';
      } else {
        sel.value = 'custom';
        if (custom) {
          custom.style.display = 'block';
          custom.value = value;
        }
      }
    }
  }

  function updateDeleteButton() {
    const btn = document.getElementById('btn-delete');
    if (btn) btn.style.display = currentProfileId ? 'inline-flex' : 'none';
  }

  // ========================================================================
  //  BUTTON ACTIONS
  // ========================================================================
  // Copy
  document.getElementById('btn-copy')?.addEventListener('click', () => {
    const profile = getProfileJSON();
    const exportData = { ...profile };
    delete exportData.is_default;
    const text = currentMode === 'ffmpeg' ? getFFmpegCmd(profile) : JSON.stringify(exportData, null, 2);
    navigator.clipboard.writeText(text).then(() => {
      if (typeof showToast === 'function') showToast("Copied to clipboard!");
    });
  });

  // Import JSON
  document.getElementById('btn-import')?.addEventListener('click', async () => {
    // Try clipboard first
    let text = '';
    try {
      text = await navigator.clipboard.readText();
    } catch (e) {
      text = prompt("Paste your profile JSON here:") || '';
    }

    if (!text) return;

    try {
      const data = JSON.parse(text);
      loadProfileIntoForm(null, data);
      if (typeof showToast === 'function') showToast("Profile imported successfully!");
    } catch (err) {
      if (typeof showToast === 'function') showToast("Invalid JSON format!", "error");
    }
  });

  // Reset
  document.getElementById('btn-reset')?.addEventListener('click', () => {
    if (!confirm('Reset all settings to defaults?')) return;

    currentProfileId = null;
    setVal('p-name', 'Custom Profile');
    setVal('v-codec', 'libx264');
    setVal('a-codec', 'aac');
    setVal('s-mode', 'copy');
    setVal('v-crf', 23);
    setVal('v-pix_fmt', 'yuv420p');
    setVal('v-profile', '');
    setVal('v-level', '');
    setVal('v-color-prim', '');
    setVal('v-color-trc', '');
    setVal('v-colorspace', '');
    setVal('v-fps-mode', 'vfr');
    setVal('v-extra', '');
    setVal('v-keyint-seconds', '10');
    const fastDecodeEl = document.getElementById('v-fast-decode');
    if (fastDecodeEl) fastDecodeEl.checked = true;
    setVal('a-bitrate', '192k');
    setVal('a-channels', '2');
    setVal('g-rename', '');
    setVal('g-title', '');
    setVal('g-cover', '');

    const vbrEl = document.getElementById('a-vbr');
    if (vbrEl) vbrEl.checked = false;

    // Reset track selectors
    ['v', 'a', 's'].forEach(s => setTrackSelector(s, ''));

    metadataTagList = [];
    dispositionTagList = [];

    updatePresetDropdown();
    updateCRFDisplay();
    updateConditionalVisibility();
    updateDeleteButton();
    renderAllTagBuilders();
    generatePreview();

    if (typeof showToast === 'function') showToast("Settings reset to defaults");
  });

  // Save
  document.getElementById('btn-save')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-save');
    const origHTML = btn.innerHTML;
    btn.innerHTML = '<i data-lucide="loader" style="width:14px;height:14px;" class="fa-spin"></i> Saving...';
    btn.disabled = true;

    try {
      const data = getProfileJSON();
      currentProfileId = await profileApi.save(currentProfileId, data);
      updateDeleteButton();
      if (typeof showToast === 'function') showToast("Profile saved successfully!");
    } catch (err) {
      if (typeof showToast === 'function') showToast("Failed to save profile", "error");
    } finally {
      btn.innerHTML = origHTML;
      btn.disabled = false;
      refreshIcons();
    }
  });

  // Delete
  document.getElementById('btn-delete')?.addEventListener('click', async () => {
    if (!currentProfileId) return;
    if (!confirm('Delete this profile entirely?')) return;

    try {
      await profileApi.delete(currentProfileId);
      currentProfileId = null;
      updateDeleteButton();
      if (typeof showToast === 'function') showToast("Profile deleted");
    } catch (err) {
      if (typeof showToast === 'function') showToast("Failed to delete profile", "error");
    }
  });

  // ========================================================================
  //  PROFILES MODAL
  // ========================================================================
  const profilesModal = document.getElementById('profiles-modal');
  const profilesListContainer = document.getElementById('profiles-list-container');

  document.getElementById('btn-close-modal')?.addEventListener('click', () => {
    if (profilesModal) profilesModal.style.display = 'none';
  });

  // Close modal on overlay click
  profilesModal?.addEventListener('click', (e) => {
    if (e.target === profilesModal) profilesModal.style.display = 'none';
  });

  document.getElementById('btn-my-profiles')?.addEventListener('click', () => {
    if (profilesModal) {
      profilesModal.style.display = 'flex';
      renderProfilesList();
    }
  });

  window.actionProfile = async function (action, id) {
    if (!cachedProfiles[id] && action !== 'delete') return;

    try {
      if (action === 'load') {
        loadProfileIntoForm(id, cachedProfiles[id]);
        profilesModal.style.display = 'none';
        if (typeof showToast === 'function') showToast("Profile loaded!");
      } else if (action === 'delete') {
        if (confirm("Are you sure you want to delete this profile?")) {
          await profileApi.delete(id);
          if (currentProfileId === id) {
            currentProfileId = null;
            updateDeleteButton();
          }
          renderProfilesList();
          if (typeof showToast === 'function') showToast("Profile deleted");
        }
      } else if (action === 'default') {
        await profileApi.setDefault(id);
        renderProfilesList();
        if (typeof showToast === 'function') showToast("Default profile updated");
      } else if (action === 'duplicate') {
        const original = cachedProfiles[id];
        if (original) {
          const copy = { ...JSON.parse(JSON.stringify(original)), name: `${original.name} (Copy)`, is_default: false };
          await profileApi.save(null, copy);
          renderProfilesList();
          if (typeof showToast === 'function') showToast("Profile duplicated!");
        }
      } else if (action === 'copy') {
        const exportData = { ...cachedProfiles[id] };
        delete exportData.is_default;
        await navigator.clipboard.writeText(JSON.stringify(exportData, null, 4));
        if (typeof showToast === 'function') showToast("JSON copied to clipboard!");
      } else if (action === 'toggle') {
        const previewEl = document.getElementById(`profile-preview-${id}`);
        if (previewEl) {
          previewEl.style.display = previewEl.style.display === 'none' ? 'block' : 'none';
        }
      }
    } catch (error) {
      console.error(`Profile action '${action}' failed`, error);
      if (typeof showToast === 'function') showToast(error.message || "Profile action failed", "error");
    }
  };

  async function renderProfilesList() {
    if (!profilesListContainer) return;
    profilesListContainer.innerHTML = '<div style="text-align:center; padding: 40px; color: var(--bs-text-muted);"><i data-lucide="loader" class="fa-spin" style="width:24px;height:24px;margin-bottom:8px;"></i><h3>Loading...</h3></div>';

    try {
      const loadedProfiles = await profileApi.list();
      cachedProfiles = Object.fromEntries(
        Object.entries(loadedProfiles || {}).filter(
          ([id, profile]) => id !== '_id' && profile && typeof profile === 'object' && !Array.isArray(profile)
        )
      );
    } catch (error) {
      console.error("Unable to load encoding profiles", error);
      profilesListContainer.innerHTML = '<div style="text-align:center; padding:40px; color:var(--bs-danger);">Unable to load profiles. Check the database connection and try again.</div>';
      if (typeof showToast === 'function') showToast("Unable to load profiles", "error");
      return;
    }
    const ids = Object.keys(cachedProfiles);

    if (ids.length === 0) {
      profilesListContainer.innerHTML = '<div style="text-align:center; padding: 40px; color: var(--bs-text-muted);"><i data-lucide="folder-open" style="width:24px;height:24px;margin-bottom:8px;"></i><h3 style="color:var(--bs-text-primary); margin-bottom:4px;">No Profiles Found</h3><p style="font-size:13px;">Create and save a profile first.</p></div>';
      refreshIcons();
      return;
    }

    let html = '';
    for (const id of ids) {
      const p = cachedProfiles[id];
      const presetStr = p.video_params?.preset !== undefined
        ? `<span class="badge-chip">${escHtml(p.video_params.preset)}</span>`
        : '';
      const crfStr = p.video_params?.crf !== undefined
        ? `<span class="badge-chip">CRF ${escHtml(p.video_params.crf)}</span>`
        : '';

      html += `
        <div class="profile-card">
          <div class="profile-card-header">
            <div class="profile-card-info">
              <div class="profile-card-name">
                ${escHtml(p.name || 'Unnamed Profile')}
                ${p.is_default ? '<span class="badge-default"><i data-lucide="star" style="width:10px;height:10px;"></i> Default</span>' : ''}
              </div>
              <div class="profile-card-meta">
                <span class="profile-card-meta-item"><i data-lucide="film" style="width:12px;height:12px;"></i> ${escHtml(p.video_codec || 'copy')}</span>
                <span class="profile-card-meta-item"><i data-lucide="music" style="width:12px;height:12px;"></i> ${escHtml(p.audio_codec || 'copy')}</span>
                ${presetStr} ${crfStr}
              </div>
            </div>
            <div class="profile-card-actions">
              ${!p.is_default ? `<button onclick="actionProfile('default', '${id}')" class="btn btn--ghost btn--sm" title="Set Default"><i data-lucide="star" style="width:14px;height:14px;"></i></button>` : ''}
              <button onclick="actionProfile('load', '${id}')" class="btn btn--primary btn--sm" title="Load">Load</button>
              <button onclick="actionProfile('duplicate', '${id}')" class="btn btn--ghost btn--sm" title="Duplicate"><i data-lucide="files" style="width:14px;height:14px;"></i></button>
              <button onclick="actionProfile('copy', '${id}')" class="btn btn--ghost btn--sm" title="Copy JSON"><i data-lucide="copy" style="width:14px;height:14px;"></i></button>
              <button onclick="actionProfile('toggle', '${id}')" class="btn btn--ghost btn--sm" title="Preview JSON"><i data-lucide="code" style="width:14px;height:14px;"></i></button>
              <button onclick="actionProfile('delete', '${id}')" class="btn btn--ghost btn--sm btn--danger" title="Delete"><i data-lucide="trash-2" style="width:14px;height:14px;"></i></button>
            </div>
          </div>
          <div id="profile-preview-${id}" class="profile-card-preview" style="display: none;">
            <pre>${escHtml(JSON.stringify(Object.fromEntries(Object.entries(p).filter(([k]) => k !== 'is_default')), null, 2))}</pre>
          </div>
        </div>
      `;
    }
    profilesListContainer.innerHTML = html;
    refreshIcons();
  }

  // ========================================================================
  //  INPUT LISTENERS
  // ========================================================================
  const allInputs = document.querySelectorAll('.encode-form-wrapper input, .encode-form-wrapper select, .encode-form-wrapper textarea');
  allInputs.forEach(input => {
    input.addEventListener('input', generatePreview);
    input.addEventListener('change', generatePreview);
  });

  // ========================================================================
  //  HELPERS
  // ========================================================================
  function getVal(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
  }

  function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }

  function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function refreshIcons() {
    if (window.lucide) window.lucide.createIcons();
  }

  // ========================================================================
  //  INIT
  // ========================================================================
  updatePresetDropdown();
  updateCRFDisplay();
  updateConditionalVisibility();
  renderAllTagBuilders();
  generatePreview();
  refreshIcons();
})();
