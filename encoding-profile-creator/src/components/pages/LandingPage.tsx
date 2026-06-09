import React from 'react';
import { PlusCircle, ListVideo, Database, HardDrive } from 'lucide-react';
import { isOfflineMode } from '../../utils/api';

interface LandingPageProps {
  onNavigate: (page: 'builder' | 'list') => void;
  profileCount: number;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onNavigate, profileCount }) => {
  const isOffline = isOfflineMode();

  return (
    <div className="container mx-auto px-4 py-12 max-w-[680px] min-h-screen flex flex-col justify-center relative z-10">
      <div className="glass-card rounded-[2rem] p-10 md:p-14 text-center">
        
        {/* Fire Logo Animation */}
        <div className="logo-container mb-10">
          <div className="fire-glow-outer"></div>
          <div className="fire-glow"></div>
          <i className="fa-solid fa-fire-flame-curved fire-flame"></i>
        </div>

        <div className="version mb-6">
          <i className="fa-solid fa-bolt mr-2 text-[#ff7a00]"></i>
          PROFILES v1.2.1
        </div>

        <h1 className="text-4xl md:text-5xl font-black font-outfit mb-4 tracking-wider uppercase text-transparent bg-clip-text bg-gradient-to-br from-[#ff3e3e] to-[#ff7a00] filter drop-shadow-[0_0_30px_rgba(255,62,62,0.15)]">
          Encoding Profile Creator
        </h1>
        
        <p className="text-slate-400 text-lg mb-10 max-w-[480px] mx-auto">
          Visually build FFmpeg encoding profiles for Amaterasu. Syncs directly to your Telegram bot.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-10">
          <button 
            onClick={() => onNavigate('builder')}
            className="btn-primary w-full py-4 text-lg"
          >
            <PlusCircle size={22} />
            Create Profile
          </button>
          
          <button 
            onClick={() => onNavigate('list')}
            className="btn-glass w-full py-4 text-lg"
          >
            <ListVideo size={22} />
            My Profiles ({profileCount})
          </button>
        </div>

        {/* Status Indicator */}
        <div className="flex items-center justify-center gap-2 text-sm">
          {isOffline ? (
            <div className="flex items-center gap-2 text-amber-500 bg-amber-500/10 px-4 py-2 rounded-full border border-amber-500/20">
              <HardDrive size={16} />
              <span>Offline Mode (Local Storage Only)</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-emerald-500 bg-emerald-500/10 px-4 py-2 rounded-full border border-emerald-500/20">
              <Database size={16} />
              <span>Connected to MongoDB</span>
            </div>
          )}
        </div>

      </div>

      <div className="mt-12 text-center text-slate-500 text-sm">
        Designed for Amaterasu • <i className="fa-solid fa-code text-[#ff3e3e]"></i> with React
      </div>
    </div>
  );
};
