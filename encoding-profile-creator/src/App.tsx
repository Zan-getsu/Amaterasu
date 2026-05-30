import { useState, useEffect } from 'react';
import { LandingPage } from './components/pages/LandingPage';
import { ProfileBuilder } from './components/pages/ProfileBuilder';
import { ProfileList } from './components/pages/ProfileList';
import { profileApi } from './utils/api';
import type { EncodingProfile } from './types';

function App() {
  const [currentPage, setCurrentPage] = useState<'landing' | 'builder' | 'list'>('landing');
  const [profiles, setProfiles] = useState<Record<string, EncodingProfile>>({});
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load profiles
  const loadProfiles = async () => {
    setIsLoading(true);
    try {
      const data = await profileApi.list();
      setProfiles(data);
    } catch (error) {
      console.error('Failed to load profiles:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadProfiles();
  }, []);

  const handleSaveProfile = async (profileData: EncodingProfile) => {
    if (editingProfileId) {
      await profileApi.update(editingProfileId, profileData);
    } else {
      await profileApi.create(profileData);
    }
    await loadProfiles();
    setEditingProfileId(null);
    setCurrentPage('list');
  };

  const handleEditProfile = (id: string) => {
    setEditingProfileId(id);
    setCurrentPage('builder');
  };

  const handleDeleteProfile = async (id: string) => {
    await profileApi.delete(id);
    await loadProfiles();
  };

  const handleDuplicateProfile = async (id: string) => {
    const profileToDuplicate = profiles[id];
    if (profileToDuplicate) {
      const duplicatedProfile = {
        ...profileToDuplicate,
        name: `${profileToDuplicate.name} (Copy)`,
        is_default: false
      };
      await profileApi.create(duplicatedProfile);
      await loadProfiles();
    }
  };

  const handleSetDefault = async (id: string) => {
    await profileApi.setDefault(id);
    await loadProfiles();
  };

  const navigateToBuilder = () => {
    setEditingProfileId(null);
    setCurrentPage('builder');
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-[#ff3e3e] flex flex-col items-center">
          <i className="fa-solid fa-fire-flame-curved fa-spin fa-2xl mb-4"></i>
          <p className="font-outfit font-bold tracking-widest text-white/70">LOADING...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="grid-background"></div>
      <div className="radial-glow glow-1"></div>
      <div className="radial-glow glow-2"></div>
      
      {currentPage === 'landing' && (
        <LandingPage 
          onNavigate={(page) => page === 'builder' ? navigateToBuilder() : setCurrentPage('list')} 
          profileCount={Object.keys(profiles).length} 
        />
      )}
      
      {currentPage === 'builder' && (
        <ProfileBuilder 
          initialData={editingProfileId ? profiles[editingProfileId] : null}
          onNavigate={setCurrentPage} 
          onSave={handleSaveProfile} 
          onDelete={editingProfileId ? () => {
            handleDeleteProfile(editingProfileId);
            setCurrentPage('list');
          } : undefined}
        />
      )}
      
      {currentPage === 'list' && (
        <ProfileList 
          profiles={profiles}
          onNavigate={(page) => page === 'builder' ? navigateToBuilder() : setCurrentPage('landing')} 
          onEdit={handleEditProfile}
          onDelete={handleDeleteProfile}
          onDuplicate={handleDuplicateProfile}
          onSetDefault={handleSetDefault}
        />
      )}
    </>
  );
}

export default App;
