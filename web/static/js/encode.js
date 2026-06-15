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
      name: "🔬 AV1 Max Compression",
      video_codec: "libsvtav1", audio_codec: "libopus", subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 28, preset: 4, pix_fmt: "yuv420p10le" },
      audio_params: { bitrate: "128k" }
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
        } catch (e) { console.error("API error, saving locally", e); }
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
        } catch (e) { console.error("API error, deleting locally", e); }
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
        } catch (e) { console.error("API error, setting default locally", e); }
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
    const nameEl = document.getElementById('p-name');
    const currentName = nameEl?.value || '';

    // Set basic fields
    setVal('v-codec', preset.video_codec);
    setVal('a-codec', preset.audio_codec);
    setVal('s-mode', preset.subtitle_mode);

    // Video params
    if (preset.video_params) {
      if (preset.video_params.crf !== undefined) {
        setVal('v-crf', preset.video_params.crf);
        updateCRFDisplay();
      }
      if (preset.video_params.pix_fmt) setVal('v-pix_fmt', preset.video_params.pix_fmt);
      if (preset.video_params.profile !== undefined) setVal('v-profile', preset.video_params.profile);
      if (preset.video_params.level !== undefined) setVal('v-level', preset.video_params.level);
      if (preset.video_params.color_primaries !== undefined) setVal('v-color-prim', preset.video_params.color_primaries);
      if (preset.video_params.color_trc !== undefined) setVal('v-color-trc', preset.video_params.color_trc);
      if (preset.video_params.colorspace !== undefined) setVal('v-colorspace', preset.video_params.colorspace);
      if (preset.video_params.extra_params !== undefined) setVal('v-extra', preset.video_params.extra_params);
    }

    // Update preset dropdown for codec
    updatePresetDropdown();
    if (preset.video_params?.preset !== undefined) {
      setVal('v-preset-select', preset.video_params.preset);
      updatePresetDisplay();
    }

    // Audio params
    if (preset.audio_params) {
      if (preset.audio_params.bitrate) setVal('a-bitrate', preset.audio_params.bitrate);
      if (preset.audio_params.channels !== undefined) setVal('a-channels', preset.audio_params.channels);
      if (preset.audio_params.vbr !== undefined) {
        const vbrEl = document.getElementById('a-vbr');
        if (vbrEl) vbrEl.checked = preset.audio_params.vbr;
      }
    }

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
      presetSelect.value = 4;
    } else if (codec === 'libx264' || codec === 'libx265') {
      presetSelect.value = 'medium';
    }

    updatePresetDisplay();
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

    // Audio: hide bitrate for copy/flac, hide channels for copy, hide VBR for copy
    const isAudioCopy = aCodec === 'copy';
    const isFlac = aCodec === 'flac';
    toggleEl('a-bitrate-group', !isAudioCopy && !isFlac);
    toggleEl('a-channels-group', !isAudioCopy);
    toggleEl('a-vbr-group', !isAudioCopy);
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
      video_codec: vCodec || "libx265",
      audio_codec: aCodec || "libopus",
      subtitle_mode: getVal('s-mode') || "copy",
      metadata,
      video_params: {
        crf: parseInt(getVal('v-crf') || "24"),
        preset: vCodec === 'libsvtav1' ? parseInt(getVal('v-preset-select') || "4") : (getVal('v-preset-select') || "medium"),
        pix_fmt: getVal('v-pix_fmt') || "yuv420p10le",
        profile: getVal('v-profile') || "",
        level: getVal('v-level') || "",
        color_primaries: getVal('v-color-prim') || "",
        color_trc: getVal('v-color-trc') || "",
        colorspace: getVal('v-colorspace') || "",
        extra_params: getVal('v-extra') || ""
      },
      audio_params: {
        bitrate: getVal('a-bitrate') || "128k",
        channels: parseInt(getVal('a-channels') || "2"),
        vbr: document.getElementById('a-vbr')?.checked || false
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
    let cmd = `ffmpeg -i input.mkv \\\n`;

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
      if (profile.video_params?.crf !== undefined) cmd += ` -crf ${profile.video_params.crf}`;
      if (profile.video_params?.preset !== undefined) cmd += ` -preset ${profile.video_params.preset}`;
      if (profile.video_params?.pix_fmt) cmd += ` -pix_fmt ${profile.video_params.pix_fmt}`;
      if (profile.video_params?.profile) cmd += ` -profile:v ${profile.video_params.profile}`;
      if (profile.video_params?.level) cmd += ` -level ${profile.video_params.level}`;
      if (profile.video_params?.color_primaries) cmd += ` \\\n  -color_primaries ${profile.video_params.color_primaries}`;
      if (profile.video_params?.color_trc) cmd += ` -color_trc ${profile.video_params.color_trc}`;
      if (profile.video_params?.colorspace) cmd += ` -colorspace ${profile.video_params.colorspace}`;
      if (profile.video_params?.extra_params) cmd += ` \\\n  ${profile.video_params.extra_params}`;
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
    if (profile.audio_codec !== 'copy' && profile.audio_params?.vbr) {
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

    cmd += `  output.mkv`;
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
    if (data.name) setVal('p-name', data.name);
    if (data.rename !== undefined) setVal('g-rename', data.rename);
    if (data.cover_image !== undefined) setVal('g-cover', data.cover_image);
    if (data.video_codec) setVal('v-codec', data.video_codec);
    if (data.audio_codec) setVal('a-codec', data.audio_codec);
    if (data.subtitle_mode) setVal('s-mode', data.subtitle_mode);

    // Video params
    updatePresetDropdown();
    if (data.video_params) {
      if (data.video_params.crf !== undefined) {
        setVal('v-crf', data.video_params.crf);
        updateCRFDisplay();
      }
      if (data.video_params.preset !== undefined) {
        setVal('v-preset-select', data.video_params.preset);
        updatePresetDisplay();
      }
      if (data.video_params.pix_fmt) setVal('v-pix_fmt', data.video_params.pix_fmt);
      if (data.video_params.profile) setVal('v-profile', data.video_params.profile);
      if (data.video_params.level) setVal('v-level', data.video_params.level);
      if (data.video_params.color_primaries) setVal('v-color-prim', data.video_params.color_primaries);
      if (data.video_params.color_trc) setVal('v-color-trc', data.video_params.color_trc);
      if (data.video_params.colorspace) setVal('v-colorspace', data.video_params.colorspace);
      if (data.video_params.extra_params) setVal('v-extra', data.video_params.extra_params);
    }

    // Audio params
    if (data.audio_params) {
      if (data.audio_params.bitrate) setVal('a-bitrate', data.audio_params.bitrate);
      if (data.audio_params.channels !== undefined) setVal('a-channels', data.audio_params.channels);
      if (data.audio_params.vbr !== undefined) {
        const vbrEl = document.getElementById('a-vbr');
        if (vbrEl) vbrEl.checked = data.audio_params.vbr;
      }
    }

    // Track selectors
    if (data.metadata) {
      if (data.metadata.title !== undefined) setVal('g-title', data.metadata.title);
      setTrackSelector('v', data.metadata.v_track || '');
      setTrackSelector('a', data.metadata.a_track || '');
      setTrackSelector('s', data.metadata.s_track || '');
    }

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
    setVal('v-codec', 'libx265');
    setVal('a-codec', 'libopus');
    setVal('s-mode', 'copy');
    setVal('v-crf', 24);
    setVal('v-pix_fmt', 'yuv420p10le');
    setVal('v-profile', '');
    setVal('v-level', '');
    setVal('v-color-prim', '');
    setVal('v-color-trc', '');
    setVal('v-colorspace', '');
    setVal('v-extra', '');
    setVal('a-bitrate', '128k');
    setVal('a-channels', '2');
    setVal('g-rename', '');
    setVal('g-title', '');
    setVal('g-cover', '');

    const vbrEl = document.getElementById('a-vbr');
    if (vbrEl) vbrEl.checked = true;

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
      navigator.clipboard.writeText(JSON.stringify(exportData, null, 4));
      if (typeof showToast === 'function') showToast("JSON copied to clipboard!");
    } else if (action === 'toggle') {
      const previewEl = document.getElementById(`profile-preview-${id}`);
      if (previewEl) {
        previewEl.style.display = previewEl.style.display === 'none' ? 'block' : 'none';
      }
    }
  };

  async function renderProfilesList() {
    if (!profilesListContainer) return;
    profilesListContainer.innerHTML = '<div style="text-align:center; padding: 40px; color: var(--bs-text-muted);"><i data-lucide="loader" class="fa-spin" style="width:24px;height:24px;margin-bottom:8px;"></i><h3>Loading...</h3></div>';

    cachedProfiles = await profileApi.list();
    const ids = Object.keys(cachedProfiles);

    if (ids.length === 0) {
      profilesListContainer.innerHTML = '<div style="text-align:center; padding: 40px; color: var(--bs-text-muted);"><i data-lucide="folder-open" style="width:24px;height:24px;margin-bottom:8px;"></i><h3 style="color:var(--bs-text-primary); margin-bottom:4px;">No Profiles Found</h3><p style="font-size:13px;">Create and save a profile first.</p></div>';
      refreshIcons();
      return;
    }

    let html = '';
    for (const id of ids) {
      const p = cachedProfiles[id];
      const presetStr = p.video_params?.preset ? `<span class="badge-chip">${p.video_params.preset}</span>` : '';
      const crfStr = p.video_params?.crf !== undefined ? `<span class="badge-chip">CRF ${p.video_params.crf}</span>` : '';

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
