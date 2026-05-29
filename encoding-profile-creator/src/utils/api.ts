import type { EncodingProfile } from '../types';

// Detect user_id from URL params
const urlParams = new URLSearchParams(window.location.search);
const userId = urlParams.get('user_id');

const LOCAL_STORAGE_KEY = 'amaterasu_encoding_profiles';

const generateId = () => Math.random().toString(36).substring(2, 10);

export const isOfflineMode = () => !userId;

export const profileApi = {
  list: async (): Promise<Record<string, EncodingProfile | any>> => {
    if (userId) {
      try {
        const response = await fetch(`/api/profiles?user_id=${userId}`);
        if (!response.ok) throw new Error('Failed to fetch profiles');
        return await response.json();
      } catch (error) {
        console.error('Error fetching profiles from API, falling back to local storage', error);
      }
    }
    
    // Fallback or offline mode
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
    return stored ? JSON.parse(stored) : {};
  },

  create: async (data: EncodingProfile): Promise<{ id: string }> => {
    if (userId) {
      try {
        const response = await fetch(`/api/profiles?user_id=${userId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error('Failed to create profile');
        return await response.json();
      } catch (error) {
        console.error('Error creating profile via API', error);
      }
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
    if (userId) {
      try {
        const response = await fetch(`/api/profiles/${pid}?user_id=${userId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error('Failed to update profile');
        return;
      } catch (error) {
        console.error('Error updating profile via API', error);
      }
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
    if (userId) {
      try {
        const response = await fetch(`/api/profiles/${pid}?user_id=${userId}`, {
          method: 'DELETE',
        });
        if (!response.ok) throw new Error('Failed to delete profile');
        return;
      } catch (error) {
        console.error('Error deleting profile via API', error);
      }
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
    if (userId) {
      try {
        const response = await fetch(`/api/profiles/${pid}/default?user_id=${userId}`, {
          method: 'POST',
        });
        if (!response.ok) throw new Error('Failed to set default profile');
        return;
      } catch (error) {
        console.error('Error setting default profile via API', error);
      }
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
