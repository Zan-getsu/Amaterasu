import type { EncodingProfile } from '../types';

// Detect user_id from URL params
const urlParams = new URLSearchParams(window.location.search);
const userId = urlParams.get('user_id');
const token = urlParams.get('token');

const LOCAL_STORAGE_KEY = 'amaterasu_encoding_profiles';

const generateId = () => Math.random().toString(36).substring(2, 10);

export const isOfflineMode = () => !userId || !token;

const apiPath = (path: string) => {
  const params = new URLSearchParams({ user_id: userId || '', token: token || '' });
  return `${path}?${params.toString()}`;
};

export const profileApi = {
  list: async (): Promise<Record<string, EncodingProfile>> => {
    if (!isOfflineMode()) {
      const response = await fetch(apiPath('/api/profiles'));
      if (!response.ok) throw new Error('Failed to fetch profiles');
      return await response.json();
    }
    
    // Fallback or offline mode
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    return stored ? JSON.parse(stored) : {};
  },

  create: async (data: EncodingProfile): Promise<{ id: string }> => {
    if (!isOfflineMode()) {
      const response = await fetch(apiPath('/api/profiles'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error('Failed to create profile');
      return await response.json();
    }
    
    // Fallback or offline mode
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    const profiles = stored ? JSON.parse(stored) : {};
    const id = generateId();
    profiles[id] = { ...data, createdAt: new Date().toISOString() };
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
    return { id };
  },

  update: async (pid: string, data: EncodingProfile): Promise<void> => {
    if (!isOfflineMode()) {
      const response = await fetch(apiPath(`/api/profiles/${pid}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error('Failed to update profile');
      return;
    }
    
    // Fallback or offline mode
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (stored) {
      const profiles = JSON.parse(stored);
      profiles[pid] = { ...profiles[pid], ...data, updatedAt: new Date().toISOString() };
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
    }
  },

  delete: async (pid: string): Promise<void> => {
    if (!isOfflineMode()) {
      const response = await fetch(apiPath(`/api/profiles/${pid}`), {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to delete profile');
      return;
    }
    
    // Fallback or offline mode
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (stored) {
      const profiles = JSON.parse(stored);
      delete profiles[pid];
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
    }
  },

  setDefault: async (pid: string): Promise<void> => {
    if (!isOfflineMode()) {
      const response = await fetch(apiPath(`/api/profiles/${pid}/default`), {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to set default profile');
      return;
    }
    
    // Fallback or offline mode
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (stored) {
      const profiles = JSON.parse(stored);
      Object.keys(profiles).forEach(key => {
        profiles[key].is_default = false;
      });
      if (profiles[pid]) {
        profiles[pid].is_default = true;
      }
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(profiles));
    }
  }
};
