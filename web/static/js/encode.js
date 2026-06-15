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

  // Populate Form from Profile Data
  function loadProfileIntoForm(id, data) {
    currentProfileId = id;
    if(data.name) document.getElementById('p-name').value = data.name;
    if(data.rename !== undefined) document.getElementById('g-rename').value = data.rename;
    if(data.cover_image !== undefined) document.getElementById('g-cover').value = data.cover_image;
    if(data.video_codec) document.getElementById('v-codec').value = data.video_codec;
    if(data.audio_codec) document.getElementById('a-codec').value = data.audio_codec;
    if(data.subtitle_mode) document.getElementById('s-mode').value = data.subtitle_mode;
    
    if(data.metadata) {
      if(data.metadata.title !== undefined) document.getElementById('g-title').value = data.metadata.title;
      if(data.metadata.v_track !== undefined) document.getElementById('v-metadata-title').value = data.metadata.v_track;
      if(data.metadata.a_track !== undefined) document.getElementById('a-metadata-title').value = data.metadata.a_track;
      if(data.metadata.s_track !== undefined) document.getElementById('s-metadata-title').value = data.metadata.s_track;
      
      const customMeta = { ...data.metadata };
      delete customMeta.title; delete customMeta.v_track; delete customMeta.a_track; delete customMeta.s_track;
      if(Object.keys(customMeta).length > 0) {
        document.getElementById('g-custom-meta').value = JSON.stringify(customMeta, null, 2);
      } else {
        document.getElementById('g-custom-meta').value = "";
      }
    }
    
    if(data.video_params) {
      if(data.video_params.crf !== undefined) {
          document.getElementById('v-crf').value = data.video_params.crf;
          if(document.getElementById('v-crf-val')) document.getElementById('v-crf-val').textContent = data.video_params.crf;
      }
      if(data.video_params.preset) {
          document.getElementById('v-preset-select').value = data.video_params.preset;
          if(document.getElementById('v-preset-val')) document.getElementById('v-preset-val').textContent = data.video_params.preset;
      }
      if(data.video_params.pix_fmt) document.getElementById('v-pix_fmt').value = data.video_params.pix_fmt;
      if(data.video_params.profile) document.getElementById('v-profile').value = data.video_params.profile;
      if(data.video_params.level) document.getElementById('v-level').value = data.video_params.level;
      if(data.video_params.color_primaries) document.getElementById('v-color-prim').value = data.video_params.color_primaries;
      if(data.video_params.color_trc) document.getElementById('v-color-trc').value = data.video_params.color_trc;
      if(data.video_params.colorspace) document.getElementById('v-colorspace').value = data.video_params.colorspace;
      if(data.video_params.extra_params) document.getElementById('v-extra').value = data.video_params.extra_params;
    }

    if(data.audio_params) {
      if(data.audio_params.bitrate) document.getElementById('a-bitrate').value = data.audio_params.bitrate;
      if(data.audio_params.channels) document.getElementById('a-channels').value = data.audio_params.channels;
      if(data.audio_params.vbr !== undefined) document.getElementById('a-vbr').checked = data.audio_params.vbr;
    }

    if(data.disposition) {
      document.getElementById('g-disposition').value = JSON.stringify(data.disposition, null, 2);
    } else {
      document.getElementById('g-disposition').value = "";
    }
    
    generatePreview();
  }
  // ------------------------------

  // Handle Accordion specific to this page if not handled globally
  document.querySelectorAll('.bs-accordion-trigger').forEach(trigger => {
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
    let customMeta = {};
    try {
      const metaStr = document.getElementById('g-custom-meta')?.value?.trim();
      if(metaStr) customMeta = JSON.parse(metaStr);
    } catch(e) {}

    let disposition = undefined;
    try {
      const dispStr = document.getElementById('g-disposition')?.value?.trim();
      if(dispStr) disposition = JSON.parse(dispStr);
    } catch(e) {}

    return {
      name: document.getElementById('p-name')?.value || "Custom Profile",
      rename: document.getElementById('g-rename')?.value || "",
      cover_image: document.getElementById('g-cover')?.value || "",
      video_codec: document.getElementById('v-codec')?.value || "libx265",
      audio_codec: document.getElementById('a-codec')?.value || "libopus",
      subtitle_mode: document.getElementById('s-mode')?.value || "copy",
      metadata: {
        title: document.getElementById('g-title')?.value || "",
        v_track: document.getElementById('v-metadata-title')?.value || "",
        a_track: document.getElementById('a-metadata-title')?.value || "",
        s_track: document.getElementById('s-metadata-title')?.value || "",
        ...customMeta
      },
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
      disposition: disposition
    };
  }

  // Generate FFmpeg Command
  function getFFmpegCmd(profile) {
    let cmd = `ffmpeg -i input.mkv \\\n`;
    
    // Video
    cmd += `  -c:v ${profile.video_codec} \\\n`;
    if(profile.video_codec !== 'copy') {
      cmd += `  -crf ${profile.video_params.crf} -preset ${profile.video_params.preset} \\\n`;
      cmd += `  -pix_fmt ${profile.video_params.pix_fmt} \\\n`;
      if(profile.video_params.profile) cmd += `  -profile:v ${profile.video_params.profile} \\\n`;
      if(profile.video_params.level) cmd += `  -level ${profile.video_params.level} \\\n`;
      if(profile.video_params.color_primaries) cmd += `  -color_primaries ${profile.video_params.color_primaries} \\\n`;
      if(profile.video_params.color_trc) cmd += `  -color_trc ${profile.video_params.color_trc} \\\n`;
      if(profile.video_params.colorspace) cmd += `  -colorspace ${profile.video_params.colorspace} \\\n`;
      if(profile.video_params.extra_params) cmd += `  ${profile.video_params.extra_params} \\\n`;
    }
    
    // Audio
    cmd += `  -c:a ${profile.audio_codec} \\\n`;
    if(profile.audio_codec !== 'copy') {
      cmd += `  -b:a ${profile.audio_params.bitrate} -ac ${profile.audio_params.channels} \\\n`;
      if(profile.audio_params.vbr) cmd += `  -vbr on \\\n`;
    }

    // Subtitles
    if(profile.subtitle_mode === 'none') {
      cmd += `  -sn \\\n`;
    } else {
      cmd += `  -c:s copy \\\n`;
    }

    // Metadata
    if(profile.metadata.title) cmd += `  -metadata title="${profile.metadata.title}" \\\n`;
    if(profile.metadata.v_track) cmd += `  -metadata:s:v:0 title="${profile.metadata.v_track}" \\\n`;
    if(profile.metadata.a_track) cmd += `  -metadata:s:a:0 title="${profile.metadata.a_track}" \\\n`;
    if(profile.metadata.s_track) cmd += `  -metadata:s:s:0 title="${profile.metadata.s_track}" \\\n`;
    
    // Custom Tags
    for(const key in profile.metadata) {
      if(!['title', 'v_track', 'a_track', 's_track'].includes(key)) {
        cmd += `  -metadata ${key}="${profile.metadata[key]}" \\\n`;
      }
    }

    // Disposition
    if(profile.disposition) {
      for(const [stream, val] of Object.entries(profile.disposition)) {
        cmd += `  -disposition:${stream} ${val} \\\n`;
      }
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
      tabJson.className = 'bs-btn bs-btn--sm bs-btn--primary';
      tabCmd.className = 'bs-btn bs-btn--sm bs-btn--ghost';
      if(previewLang) previewLang.textContent = 'JSON';
      generatePreview();
    });
    tabCmd.addEventListener('click', () => {
      currentMode = 'ffmpeg';
      tabCmd.className = 'bs-btn bs-btn--sm bs-btn--primary';
      tabJson.className = 'bs-btn bs-btn--sm bs-btn--ghost';
      if(previewLang) previewLang.textContent = 'BASH';
      generatePreview();
    });
  }

  // --- BUTTON ACTIONS ---

  // Import JSON Modal
  document.getElementById('btn-import')?.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      const data = JSON.parse(text);
      loadProfileIntoForm(null, data);
      if(typeof showToast === 'function') showToast("Profile imported from clipboard!");
    } catch(err) {
      if(typeof showToast === 'function') showToast("Invalid JSON in clipboard", "error");
    }
  });

  // Save to DB
  document.getElementById('btn-save')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-save');
    const origHTML = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
    btn.disabled = true;

    try {
      const data = getProfileJSON();
      currentProfileId = await profileApi.save(currentProfileId, data);
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
        if(currentProfileId === id) currentProfileId = null;
        renderProfilesList();
        if(typeof showToast === 'function') showToast("Profile deleted");
      }
    } else if (action === 'default') {
      await profileApi.setDefault(id);
      renderProfilesList();
      if(typeof showToast === 'function') showToast("Default profile updated");
    }
  };

  async function renderProfilesList() {
    if(!profilesListContainer) return;
    profilesListContainer.innerHTML = '<div class="bs-empty"><i class="fa-solid fa-spinner fa-spin bs-empty__icon"></i><h3 class="bs-empty__title">Loading...</h3></div>';
    
    cachedProfiles = await profileApi.list();
    const ids = Object.keys(cachedProfiles);
    
    if(ids.length === 0) {
      profilesListContainer.innerHTML = '<div class="bs-empty" style="padding: 40px;"><i class="fa-solid fa-folder-open bs-empty__icon"></i><h3 class="bs-empty__title">No Profiles Found</h3><p class="bs-empty__subtitle">Create and save a profile first.</p></div>';
      return;
    }

    let html = '';
    for(const id of ids) {
      const p = cachedProfiles[id];
      html += `
        <div class="bs-card bs-card--elevated" style="padding: 16px; margin-bottom: 8px;">
          <div class="bs-flex" style="justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px;">
            <div>
              <div style="font-weight: 700; color: var(--bs-text-primary); margin-bottom: 4px;">
                ${p.name || 'Unnamed Profile'} 
                ${p.is_default ? '<span class="bs-badge bs-badge--success" style="margin-left: 8px;">Default</span>' : ''}
              </div>
              <div style="font-size: 12px; color: var(--bs-text-muted);">
                <i class="fa-solid fa-film"></i> ${p.video_codec || 'copy'} · <i class="fa-solid fa-music"></i> ${p.audio_codec || 'copy'}
              </div>
            </div>
            <div class="bs-flex" style="gap: 8px;">
              ${!p.is_default ? `<button onclick="actionProfile('default', '${id}')" class="bs-btn bs-btn--sm bs-btn--ghost" title="Set Default"><i class="fa-solid fa-star"></i></button>` : ''}
              <button onclick="actionProfile('load', '${id}')" class="bs-btn bs-btn--sm bs-btn--primary">Load</button>
              <button onclick="actionProfile('delete', '${id}')" class="bs-btn bs-btn--sm bs-btn--danger"><i class="fa-solid fa-trash"></i></button>
            </div>
          </div>
        </div>
      `;
    }
    profilesListContainer.innerHTML = html;
  }

  document.getElementById('btn-my-profiles')?.addEventListener('click', () => {
    if(profilesModal) {
      profilesModal.style.display = 'flex';
      renderProfilesList();
    }
  });

  // Listeners
  inputs.forEach(input => {
    input.addEventListener('input', generatePreview);
    input.addEventListener('change', generatePreview);
  });

  // Initial preview
  generatePreview();
});
