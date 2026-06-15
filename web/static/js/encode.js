// 5. Encode Page: Live Preview
document.addEventListener("DOMContentLoaded", () => {
  const inputs = document.querySelectorAll('input, select, textarea');
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

  const generateId = () => Math.random().toString(36).substring(2, 10);
  const apiPath = (path) => `${path}?user_id=${userId}&token=${token}`;

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
            method: method,
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
        if(profiles[id]) profiles[id].is_default = true;
        localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
      }
    }
  };

  const DEFAULT_PROFILE = {
    name: "New Profile",
    video_codec: "libsvtav1",
    audio_codec: "libopus",
    subtitle_mode: "copy",
    metadata: {},
    video_params: { crf: 28, preset: 4, pix_fmt: "yuv420p10le" },
    audio_params: { bitrate: "128k" }
  };

  const QUICK_PRESETS = [
    {
      name: "dYZ_ H.265 Balanced",
      video_codec: "libx265",
      audio_codec: "aac",
      subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 23, preset: "medium", pix_fmt: "yuv420p" },
      audio_params: { bitrate: "192k" }
    },
    {
      name: "dY'Z H.265 High Quality",
      video_codec: "libx265",
      audio_codec: "flac",
      subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 18, preset: "slow", pix_fmt: "yuv420p10le" },
      audio_params: {}
    },
    {
      name: "s H.264 Fast Encode",
      video_codec: "libx264",
      audio_codec: "aac",
      subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 20, preset: "veryfast", pix_fmt: "yuv420p" },
      audio_params: { bitrate: "192k" }
    },
    {
      name: "dY AV1 Max Compression",
      video_codec: "libsvtav1",
      audio_codec: "libopus",
      subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 28, preset: 4, pix_fmt: "yuv420p10le" },
      audio_params: { bitrate: "128k" }
    },
    {
      name: "dYZO Anime Encode",
      video_codec: "libx265",
      audio_codec: "libopus",
      subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 20, preset: "slow", pix_fmt: "yuv420p10le", extra_params: "tune=animation" },
      audio_params: { bitrate: "192k" }
    },
    {
      name: "dYO? Web Streaming",
      video_codec: "libx264",
      audio_codec: "aac",
      subtitle_mode: "copy",
      metadata: {},
      video_params: { crf: 23, preset: "fast", pix_fmt: "yuv420p", profile: "high", level: "4.1", extra_params: "tune=zerolatency" },
      audio_params: { bitrate: "128k" }
    }
  ];

  const LANGUAGES = [
    { value: "eng", label: "English (eng)" },
    { value: "jpn", label: "Japanese (jpn)" },
    { value: "kor", label: "Korean (kor)" },
    { value: "spa", label: "Spanish (spa)" },
    { value: "fre", label: "French (fre)" },
    { value: "ger", label: "German (ger)" },
    { value: "ita", label: "Italian (ita)" },
    { value: "hin", label: "Hindi (hin)" },
    { value: "rus", label: "Russian (rus)" },
    { value: "chi", label: "Chinese (chi)" },
    { value: "ara", label: "Arabic (ara)" },
    { value: "por", label: "Portuguese (por)" },
    { value: "und", label: "Undefined (und)" }
  ];

  const DISPOSITION_OPTS = [
    { value: "0", label: "0 (Remove all flags)" },
    { value: "default", label: "default (Mark as default)" },
    { value: "forced", label: "forced (Mark as forced)" },
    { value: "default+forced", label: "default+forced (Default & Forced)" },
    { value: "dub", label: "dub (Dub track)" },
    { value: "comment", label: "comment (Commentary)" },
    { value: "hearing_impaired", label: "hearing_impaired" },
    { value: "visual_impaired", label: "visual_impaired" },
    { value: "captions", label: "captions" }
  ];

  const TRACK_OPTS = [
    { value: "?", label: "All Tracks (?)" },
    { value: "0", label: "Track 1" },
    { value: "1", label: "Track 2" },
    { value: "2", label: "Track 3" },
    { value: "3", label: "Track 4" }
  ];

  // Populate Quick Presets UI
  const presetsContainer = document.getElementById('quick-presets-container');
  if (presetsContainer) {
    let presetsHtml = '';
    QUICK_PRESETS.forEach((preset, idx) => {
      presetsHtml += `
        <button type="button" class="preset-btn" data-idx="${idx}" style="text-align:left; padding: 12px; border-radius: var(--bs-radius-md); background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.05); cursor:pointer; transition:all var(--bs-transition-fast);">
          <div style="font-size:13px; font-weight:700; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${preset.name}</div>
          <div style="font-size:11px; color:var(--bs-text-muted); margin-top:4px;">${preset.video_codec} • ${preset.audio_codec}</div>
        </button>
      `;
    });
    presetsContainer.innerHTML = presetsHtml;

    document.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const idx = e.currentTarget.getAttribute('data-idx');
        const p = QUICK_PRESETS[idx];
        const currentName = document.getElementById('p-name')?.value || "New Profile";
        loadProfileIntoForm(null, { ...p, name: currentName });
        if(typeof showToast === 'function') showToast(`Preset applied: ${p.name}`);
      });
    });
  }

  // --- STREAM TAG BUILDER LOGIC ---
  const state = {
    'v-meta': [], 'v-disp': [],
    'a-meta': [], 'a-disp': [],
    's-meta': [], 's-disp': []
  };

  window.addTag = function(target) {
    if(target.endsWith('-meta')) {
      state[target].push({ track: '?', tagType: 'title', tagValue: '' });
    } else {
      state[target].push({ track: '?', tagValue: 'default' });
    }
    renderTags(target);
    generatePreview();
  };

  window.rmTag = function(target, idx) {
    state[target].splice(idx, 1);
    renderTags(target);
    generatePreview();
  };

  window.updTag = function(target, idx, field, val) {
    state[target][idx][field] = val;
    if(field === 'tagType') {
      if(val === 'language') state[target][idx].tagValue = 'eng';
      else state[target][idx].tagValue = '';
    }
    renderTags(target);
    generatePreview();
  };

  function renderTags(target) {
    const container = document.getElementById(`${target}-container`);
    if(!container) return;
    const isMeta = target.endsWith('-meta');

    let html = '';
    state[target].forEach((t, i) => {
      html += `<div style="display:flex; gap:8px; align-items:start;">`;
      
      // Track Select
      html += `<select class="form-select" style="flex:1;" onchange="updTag('${target}', ${i}, 'track', this.value)">`;
      TRACK_OPTS.forEach(opt => {
        html += `<option value="${opt.value}" ${t.track === opt.value ? 'selected' : ''}>${opt.label}</option>`;
      });
      html += `</select>`;

      if (isMeta) {
        // Tag Type Select
        html += `<select class="form-select" style="flex:1;" onchange="updTag('${target}', ${i}, 'tagType', this.value)">
                  <option value="title" ${t.tagType === 'title' ? 'selected' : ''}>Title</option>
                  <option value="language" ${t.tagType === 'language' ? 'selected' : ''}>Language</option>
                  <option value="handler_name" ${t.tagType === 'handler_name' ? 'selected' : ''}>Handler</option>
                  <option value="custom" ${t.tagType === 'custom' ? 'selected' : ''}>Custom</option>
                 </select>`;
        
        // Tag Value Input/Select
        if (t.tagType === 'language') {
          html += `<select class="form-select" style="flex:2;" onchange="updTag('${target}', ${i}, 'tagValue', this.value)">`;
          LANGUAGES.forEach(l => {
            html += `<option value="${l.value}" ${t.tagValue === l.value ? 'selected' : ''}>${l.label}</option>`;
          });
          html += `</select>`;
        } else {
          html += `<input type="text" class="form-input form-input--mono" style="flex:2;" placeholder="${t.tagType === 'custom' ? 'e.g. BPS=120' : 'Value...'}" value="${t.tagValue}" oninput="updTag('${target}', ${i}, 'tagValue', this.value)">`;
        }
      } else {
        // Disposition Value Select
        html += `<select class="form-select" style="flex:2;" onchange="updTag('${target}', ${i}, 'tagValue', this.value)">`;
        DISPOSITION_OPTS.forEach(opt => {
          html += `<option value="${opt.value}" ${t.tagValue === opt.value ? 'selected' : ''}>${opt.label}</option>`;
        });
        html += `</select>`;
      }

      html += `<button type="button" class="btn btn--ghost btn--icon" onclick="rmTag('${target}', ${i})" style="padding:10px; color:#e74c3c; border:none; background:rgba(255,255,255,0.05);"><i data-lucide="trash-2" style="width:16px;height:16px;"></i></button>`;
      html += `</div>`;
    });
    container.innerHTML = html;
    if (window.lucide) { window.lucide.createIcons(); }
  }

  // --- TRACK SELECTOR LOGIC ---
  window.toggleTrackInput = function(prefix) {
    const sel = document.getElementById(`${prefix}_sel`);
    const wrap = document.getElementById(`${prefix}_custom_wrap`);
    const inp = document.getElementById(`m-${prefix}`);
    if (sel.value === 'custom') {
      wrap.style.display = 'block';
      inp.value = '';
    } else {
      wrap.style.display = 'none';
      inp.value = sel.value;
    }
    generatePreview();
  };


  // Populate Form from Profile Data
  function loadProfileIntoForm(id, data) {
    currentProfileId = id;
    
    const delBtn = document.getElementById('btn-delete');
    if (delBtn) delBtn.style.display = id ? 'inline-flex' : 'none';

    if(data.name !== undefined) document.getElementById('p-name').value = data.name;
    if(data.rename !== undefined) document.getElementById('g-rename').value = data.rename;
    else document.getElementById('g-rename').value = "";
    if(data.cover_image !== undefined) document.getElementById('g-cover').value = data.cover_image;
    if(data.video_codec) document.getElementById('v-codec').value = data.video_codec;
    if(data.audio_codec) document.getElementById('a-codec').value = data.audio_codec;
    if(data.subtitle_mode) document.getElementById('s-mode').value = data.subtitle_mode;
    
    // Clear all state
    for(let k in state) state[k] = [];

    const handleTrackLoader = (prefix, val) => {
      const inp = document.getElementById(`m-${prefix}`);
      const sel = document.getElementById(`${prefix}_sel`);
      const wrap = document.getElementById(`${prefix}_custom_wrap`);
      if(!inp || !sel) return;
      inp.value = val !== undefined ? val : "";
      
      const isCommon = ['?', '0', '1', '0,1', '1,0'].includes(inp.value);
      if (inp.value === "") {
        sel.value = '?';
        wrap.style.display = 'none';
      } else if (isCommon) {
        sel.value = inp.value;
        wrap.style.display = 'none';
      } else {
        sel.value = 'custom';
        wrap.style.display = 'block';
      }
    };

    if(data.metadata) {
      document.getElementById('g-title').value = data.metadata.title || "";
      handleTrackLoader('v_track', data.metadata.v_track);
      handleTrackLoader('a_track', data.metadata.a_track);
      handleTrackLoader('s_track', data.metadata.s_track);
      
      const standardKeys = ['title', 'v_track', 'a_track', 's_track'];
      for(const k in data.metadata) {
        if(!standardKeys.includes(k.trim())) {
          const val = data.metadata[k];
          let track = '?';
          let tagType = 'custom';
          let tagValue = val;
          let target = null;
          
          let parsedKey = k.trim();
          if(parsedKey.startsWith('s:v:')) { target = 'v-meta'; parsedKey = parsedKey.substring(4); }
          else if(parsedKey.startsWith('s:a:')) { target = 'a-meta'; parsedKey = parsedKey.substring(4); }
          else if(parsedKey.startsWith('s:s:')) { target = 's-meta'; parsedKey = parsedKey.substring(4); }
          
          if(target) {
            const spl = parsedKey.indexOf(':');
            if(spl !== -1) {
              track = parsedKey.substring(0, spl);
              const tKey = parsedKey.substring(spl+1);
              if(['title','language','handler_name'].includes(tKey)) {
                tagType = tKey;
              } else {
                tagValue = `${tKey}=${val}`;
              }
            } else {
              if(['title','language','handler_name'].includes(parsedKey)) tagType = parsedKey;
              else tagValue = `${parsedKey}=${val}`;
            }
            state[target].push({ track, tagType, tagValue });
          }
        }
      }
    } else {
      document.getElementById('g-title').value = "";
      handleTrackLoader('v_track', "");
      handleTrackLoader('a_track', "");
      handleTrackLoader('s_track', "");
    }
    
    if(data.disposition) {
      for(const k in data.disposition) {
        const val = data.disposition[k];
        let track = '?';
        let target = null;
        let parsedKey = k.trim();
        
        if(parsedKey.startsWith('v:')) { target = 'v-disp'; track = parsedKey.substring(2); }
        else if(parsedKey.startsWith('a:')) { target = 'a-disp'; track = parsedKey.substring(2); }
        else if(parsedKey.startsWith('s:')) { target = 's-disp'; track = parsedKey.substring(2); }
        else if(parsedKey.startsWith('v')) { target = 'v-disp'; track = '?'; }
        else if(parsedKey.startsWith('a')) { target = 'a-disp'; track = '?'; }
        else if(parsedKey.startsWith('s')) { target = 's-disp'; track = '?'; }

        if(target) {
          if(track === '') track = '?';
          state[target].push({ track, tagValue: val });
        }
      }
    }

    Object.keys(state).forEach(renderTags);
    
    if(data.video_params) {
      if(data.video_params.crf !== undefined) {
          document.getElementById('v-crf').value = data.video_params.crf;
          if(document.getElementById('v-crf-val')) document.getElementById('v-crf-val').textContent = data.video_params.crf;
      }
      if(data.video_params.preset) {
          document.getElementById('v-preset-select').value = data.video_params.preset;
          if(document.getElementById('v-preset-val')) document.getElementById('v-preset-val').textContent = data.video_params.preset;
      }
      document.getElementById('v-pix_fmt').value = data.video_params.pix_fmt || "";
      document.getElementById('v-profile').value = data.video_params.profile || "";
      document.getElementById('v-level').value = data.video_params.level || "";
      document.getElementById('v-color-prim').value = data.video_params.color_primaries || "";
      document.getElementById('v-color-trc').value = data.video_params.color_trc || "";
      document.getElementById('v-colorspace').value = data.video_params.colorspace || "";
      document.getElementById('v-extra').value = data.video_params.extra_params || "";
    }

    if(data.audio_params) {
      document.getElementById('a-bitrate').value = data.audio_params.bitrate || "128k";
      document.getElementById('a-channels').value = data.audio_params.channels || "2";
      document.getElementById('a-vbr').checked = data.audio_params.vbr || false;
    }
    
    generatePreview();
  }

  // Handle Accordion
  document.querySelectorAll('.acc-trigger').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const isOpen = trigger.classList.contains('open');
      trigger.classList.toggle('open', !isOpen);
      trigger.nextElementSibling.style.display = isOpen ? 'none' : 'block';
    });
  });

  // Handle Chips
  window.insertChip = function(targetId, value) {
    const el = document.getElementById(targetId);
    if(el) {
      el.value = el.value + value;
      generatePreview();
    }
  };

  // Sync Slider values
  const vCrf = document.getElementById('v-crf');
  const vCrfVal = document.getElementById('v-crf-val');
  if(vCrf) {
    vCrf.addEventListener('input', (e) => {
      vCrfVal.textContent = e.target.value;
      generatePreview();
    });
  }

  const vPreset = document.getElementById('v-preset-select');
  const vPresetVal = document.getElementById('v-preset-val');
  if(vPreset) {
    vPreset.addEventListener('change', (e) => {
      vPresetVal.textContent = e.target.value;
    });
  }

  // Generate Profile JSON
  function getProfileJSON() {
    const v_track = document.getElementById('m-v_track')?.value || "";
    const a_track = document.getElementById('m-a_track')?.value || "";
    const s_track = document.getElementById('m-s_track')?.value || "";
    
    const metaObj = {
      title: document.getElementById('g-title')?.value || "",
      v_track: v_track === "?" ? "" : v_track,
      a_track: a_track === "?" ? "" : a_track,
      s_track: s_track === "?" ? "" : s_track,
    };
    
    const resolveMeta = (target, prefix) => {
      state[target].forEach(t => {
        let key = `${prefix}${t.track === '?' ? '' : t.track + ':'}`;
        if(t.tagType === 'custom') {
          const spl = t.tagValue.indexOf('=');
          if(spl !== -1) {
            key += t.tagValue.substring(0, spl);
            let ukey = key;
            while(metaObj[ukey] !== undefined) ukey += ' ';
            metaObj[ukey] = t.tagValue.substring(spl+1);
          }
        } else {
          key += t.tagType;
          let ukey = key;
          while(metaObj[ukey] !== undefined) ukey += ' ';
          metaObj[ukey] = t.tagValue;
        }
      });
    };
    resolveMeta('v-meta', 's:v:');
    resolveMeta('a-meta', 's:a:');
    resolveMeta('s-meta', 's:s:');

    ['title', 'v_track', 'a_track', 's_track'].forEach(k => {
      if(!metaObj[k]) delete metaObj[k];
    });

    const dispObj = {};
    const resolveDisp = (target, prefix) => {
      state[target].forEach(t => {
        dispObj[`${prefix}${t.track === '?' ? '' : ':'+t.track}`] = t.tagValue;
      });
    };
    resolveDisp('v-disp', 'v');
    resolveDisp('a-disp', 'a');
    resolveDisp('s-disp', 's');

    return {
      name: document.getElementById('p-name')?.value || "Custom Profile",
      rename: document.getElementById('g-rename')?.value || "",
      cover_image: document.getElementById('g-cover')?.value || "",
      video_codec: document.getElementById('v-codec')?.value || "libx265",
      audio_codec: document.getElementById('a-codec')?.value || "libopus",
      subtitle_mode: document.getElementById('s-mode')?.value || "copy",
      metadata: Object.keys(metaObj).length > 0 ? metaObj : undefined,
      video_params: {
        crf: parseInt(document.getElementById('v-crf')?.value || "24"),
        preset: document.getElementById('v-preset-select')?.value || "medium",
        pix_fmt: document.getElementById('v-pix_fmt')?.value || "yuv420p10le",
        profile: document.getElementById('v-profile')?.value || "",
        level: document.getElementById('v-level')?.value || "",
        color_primaries: document.getElementById('v-color-prim')?.value || "",
        color_trc: document.getElementById('v-color-trc')?.value || "",
        colorspace: document.getElementById('v-colorspace')?.value || "",
        extra_params: document.getElementById('v-extra')?.value || ""
      },
      audio_params: {
        bitrate: document.getElementById('a-bitrate')?.value || "128k",
        channels: parseInt(document.getElementById('a-channels')?.value || "2"),
        vbr: document.getElementById('a-vbr')?.checked || false
      },
      disposition: Object.keys(dispObj).length > 0 ? dispObj : undefined
    };
  }

  // Generate FFmpeg Command
  function getFFmpegCmd(profile) {
    let cmd = `ffmpeg -i input.mkv \\\n`;
    
    // Track Mapping
    if(profile.metadata?.v_track) cmd += `  -map 0:v${profile.metadata.v_track === '?' ? '' : ':'+profile.metadata.v_track} \\\n`;
    if(profile.metadata?.a_track) cmd += `  -map 0:a${profile.metadata.a_track === '?' ? '' : ':'+profile.metadata.a_track} \\\n`;
    if(profile.metadata?.s_track) cmd += `  -map 0:s${profile.metadata.s_track === '?' ? '' : ':'+profile.metadata.s_track} \\\n`;

    // Video
    cmd += `  -c:v ${profile.video_codec} `;
    if(profile.video_codec !== 'copy') {
      if(profile.video_params?.crf !== undefined) cmd += `-crf ${profile.video_params.crf} `;
      if(profile.video_params?.preset !== undefined) cmd += `-preset ${profile.video_params.preset} `;
      if(profile.video_params?.pix_fmt) cmd += `-pix_fmt ${profile.video_params.pix_fmt} `;
      cmd += `\\\n`;
      if(profile.video_params?.profile) cmd += `  -profile:v ${profile.video_params.profile} \\\n`;
      if(profile.video_params?.level) cmd += `  -level ${profile.video_params.level} \\\n`;
      if(profile.video_params?.color_primaries) cmd += `  -color_primaries ${profile.video_params.color_primaries} \\\n`;
      if(profile.video_params?.color_trc) cmd += `  -color_trc ${profile.video_params.color_trc} \\\n`;
      if(profile.video_params?.colorspace) cmd += `  -colorspace ${profile.video_params.colorspace} \\\n`;
      if(profile.video_params?.extra_params) cmd += `  ${profile.video_params.extra_params} \\\n`;
    } else {
      cmd += `\\\n`;
    }
    
    // Audio
    cmd += `  -c:a ${profile.audio_codec} `;
    if(profile.audio_codec !== 'copy' && profile.audio_codec !== 'flac') {
      if(profile.audio_params?.bitrate) cmd += `-b:a ${profile.audio_params.bitrate} `;
      if(profile.audio_params?.channels) cmd += `-ac ${profile.audio_params.channels} `;
      cmd += `\\\n`;
      if(profile.audio_params?.vbr) cmd += `  -vbr on \\\n`;
    } else {
      cmd += `\\\n`;
    }

    // Subtitles
    cmd += `  -c:s ${profile.subtitle_mode} \\\n`;

    // Metadata
    if(profile.metadata) {
      Object.entries(profile.metadata).forEach(([k, v]) => {
        if (!['v_track', 'a_track', 's_track', 'title'].includes(k.trim())) {
          if (k.includes(':')) {
             cmd += `  -metadata:${k.trim()} "${v}" \\\n`;
          } else {
             cmd += `  -metadata "${k.trim()}=${v}" \\\n`;
          }
        }
      });
      if(profile.metadata.title) cmd += `  -metadata title="${profile.metadata.title}" \\\n`;
    }

    // Disposition
    if(profile.disposition) {
      Object.entries(profile.disposition).forEach(([k, v]) => {
        cmd += `  -disposition:${k.trim()} ${v} \\\n`;
      });
    }

    cmd += `  output.mkv`;
    return cmd;
  }

  function generatePreview() {
    if(!previewCode) return;
    const profile = getProfileJSON();
    
    if (currentMode === 'json') {
      previewCode.textContent = JSON.stringify(profile, null, 2);
    } else {
      previewCode.textContent = getFFmpegCmd(profile);
    }
  }

  // Tabs
  if(tabJson && tabCmd) {
    tabJson.addEventListener('click', () => {
      currentMode = 'json';
      tabJson.className = 'preview-tab preview-tab--active';
      tabCmd.className = 'preview-tab';
      if(previewLang) previewLang.textContent = 'JSON';
      generatePreview();
    });
    tabCmd.addEventListener('click', () => {
      currentMode = 'ffmpeg';
      tabCmd.className = 'preview-tab preview-tab--active';
      tabJson.className = 'preview-tab';
      if(previewLang) previewLang.textContent = 'BASH';
      generatePreview();
    });
  }

  // --- BUTTON ACTIONS ---

  document.getElementById('btn-import')?.addEventListener('click', () => {
    const input = prompt("Paste your profile JSON here:");
    if (!input) return;
    try {
      const parsed = JSON.parse(input);
      loadProfileIntoForm(null, { ...DEFAULT_PROFILE, ...parsed, name: parsed.name || "Imported Profile" });
      if(typeof showToast === 'function') showToast("Profile imported successfully!");
    } catch(err) {
      alert("Invalid JSON format!");
    }
  });

  document.getElementById('btn-reset')?.addEventListener('click', () => {
    if(confirm("Are you sure you want to reset all settings?")) {
      loadProfileIntoForm(null, DEFAULT_PROFILE);
    }
  });

  document.getElementById('btn-delete')?.addEventListener('click', async () => {
    if(!currentProfileId) return;
    if(confirm("Are you sure you want to delete this profile?")) {
      await profileApi.delete(currentProfileId);
      loadProfileIntoForm(null, DEFAULT_PROFILE);
      renderProfilesList();
      if(typeof showToast === 'function') showToast("Profile deleted!");
    }
  });

  // Save to DB
  document.getElementById('btn-save')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-save');
    const origHTML = btn.innerHTML;
    btn.innerHTML = '<i data-lucide="loader" class="fa-spin" style="width:14px;height:14px;"></i> Saving...';
    if(window.lucide) window.lucide.createIcons();
    btn.disabled = true;

    try {
      const data = getProfileJSON();
      currentProfileId = await profileApi.save(currentProfileId, data);
      
      const delBtn = document.getElementById('btn-delete');
      if (delBtn) delBtn.style.display = 'inline-flex';

      if(typeof showToast === 'function') showToast("Profile saved successfully!");
    } catch(err) {
      if(typeof showToast === 'function') showToast("Failed to save profile", "error");
    } finally {
      btn.innerHTML = origHTML;
      btn.disabled = false;
    }
  });

  // --- MY PROFILES MODAL LOGIC ---
  const profilesModal = document.getElementById('profiles-modal');
  const profilesListContainer = document.getElementById('profiles-list-container');
  
  document.getElementById('btn-close-modal')?.addEventListener('click', () => {
    if(profilesModal) profilesModal.style.display = 'none';
  });

  window.actionProfile = async function(action, id) {
    if(!cachedProfiles[id]) return;
    
    if (action === 'load') {
      loadProfileIntoForm(id, cachedProfiles[id]);
      profilesModal.style.display = 'none';
      if(typeof showToast === 'function') showToast("Profile loaded!");
    } else if (action === 'delete') {
      if(confirm("Are you sure you want to delete this profile?")) {
        await profileApi.delete(id);
        if(currentProfileId === id) loadProfileIntoForm(null, DEFAULT_PROFILE);
        renderProfilesList();
        if(typeof showToast === 'function') showToast("Profile deleted");
      }
    } else if (action === 'default') {
      await profileApi.setDefault(id);
      renderProfilesList();
      if(typeof showToast === 'function') showToast("Default profile updated");
    } else if (action === 'duplicate') {
      const p = { ...cachedProfiles[id], name: cachedProfiles[id].name + " (Copy)", is_default: false };
      await profileApi.save(null, p);
      renderProfilesList();
      if(typeof showToast === 'function') showToast("Profile duplicated");
    }
  };

  async function renderProfilesList() {
    if(!profilesListContainer) return;
    profilesListContainer.innerHTML = '<div style="text-align:center; padding: 40px; color: var(--bs-text-muted);"><i data-lucide="loader" class="fa-spin" style="width:24px;height:24px;margin-bottom:8px;"></i><h3>Loading...</h3></div>';
    
    cachedProfiles = await profileApi.list();
    const ids = Object.keys(cachedProfiles);
    
    if(ids.length === 0) {
      profilesListContainer.innerHTML = '<div style="text-align:center; padding: 40px; color: var(--bs-text-muted);"><i data-lucide="folder-open" style="width:24px;height:24px;margin-bottom:8px;"></i><h3 style="color:var(--bs-text-primary); margin-bottom:4px;">No Profiles Found</h3><p style="font-size:13px;">Create and save a profile first.</p></div>';
      return;
    }

    let html = '';
    for(const id of ids) {
      const p = cachedProfiles[id];
      html += `
        <div style="background: var(--bs-graphite); border: 1px solid var(--bs-border); border-radius: var(--bs-radius-md); padding: 16px; margin-bottom: 8px;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px;">
            <div>
              <div style="font-weight: 700; color: var(--bs-text-primary); margin-bottom: 4px;">
                ${p.name || 'Unnamed Profile'} 
                ${p.is_default ? '<span class="chip" style="margin-left: 8px; border-color: #2ecc71; color: #2ecc71;">Default</span>' : ''}
              </div>
              <div style="font-size: 12px; color: var(--bs-text-muted); display:flex; gap:8px; align-items:center;">
                <i data-lucide="film" style="width:14px;height:14px;"></i> ${p.video_codec || 'copy'} • <i data-lucide="music" style="width:14px;height:14px;"></i> ${p.audio_codec || 'copy'}
              </div>
            </div>
            <div style="display: flex; gap: 8px;">
              ${!p.is_default ? `<button onclick="actionProfile('default', '${id}')" class="btn btn--ghost btn--sm" title="Set Default"><i data-lucide="star" style="width:14px;height:14px;"></i></button>` : ''}
              <button onclick="actionProfile('duplicate', '${id}')" class="btn btn--ghost btn--sm" title="Duplicate Profile"><i data-lucide="copy" style="width:14px;height:14px;"></i></button>
              <button onclick="actionProfile('load', '${id}')" class="btn btn--primary btn--sm">Load</button>
              <button onclick="actionProfile('delete', '${id}')" class="btn btn--ghost btn--sm" style="color: #e74c3c; border-color: rgba(231,76,60,0.3);"><i data-lucide="trash-2" style="width:14px;height:14px;"></i></button>
            </div>
          </div>
        </div>
      `;
    }
    profilesListContainer.innerHTML = html;
    if (window.lucide) { window.lucide.createIcons(); }
  }

  document.getElementById('btn-my-profiles')?.addEventListener('click', () => {
    if(profilesModal) {
      profilesModal.style.display = 'flex';
      renderProfilesList();
    }
  });

  // Listeners
  document.addEventListener('input', (e) => {
    if(e.target.matches('input, select, textarea')) generatePreview();
  });
  document.addEventListener('change', (e) => {
    if(e.target.matches('input, select, textarea')) generatePreview();
  });

  // Initialize
  loadProfileIntoForm(null, DEFAULT_PROFILE);
});
