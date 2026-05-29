import React, { useState } from 'react';
import { ArrowLeft, Copy, Star, Trash2, Edit, Check, Settings, Film, Music, CheckCircle } from 'lucide-react';
import type { EncodingProfile } from '../../types';

interface ProfileListProps {
  profiles: Record<string, EncodingProfile>;
  onNavigate: (page: 'landing' | 'builder') => void;
  onEdit: (profileId: string) => void;
  onDelete: (profileId: string) => void;
  onSetDefault: (profileId: string) => void;
}

export const ProfileList: React.FC<ProfileListProps> = ({ 
  profiles, 
  onNavigate, 
  onEdit, 
  onDelete,
  onSetDefault
}) => {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const entries = Object.entries(profiles);

  const handleCopyJSON = (id: string, profile: any) => {
    // Remove UI only fields before copying
    const { is_default, ...exportData } = profile;
    navigator.clipboard.writeText(JSON.stringify(exportData, null, 4));
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="container mx-auto px-4 py-8 max-w-[800px] min-h-screen relative z-10">
      
      {/* Top Bar */}
      <div className="flex items-center justify-between mb-8">
        <button 
          onClick={() => onNavigate('landing')}
          className="flex items-center gap-2 text-slate-300 hover:text-white transition-colors bg-white/5 hover:bg-white/10 px-4 py-2 rounded-xl border border-white/10"
        >
          <ArrowLeft size={18} />
          Back to Home
        </button>
        <button 
          onClick={() => onNavigate('builder')}
          className="btn-primary py-2 px-6"
        >
          New Profile
        </button>
      </div>

      <div className="mb-8">
        <h2 className="text-3xl font-black font-outfit text-white mb-2">My Profiles</h2>
        <p className="text-slate-400">Manage your saved FFmpeg encoding configurations.</p>
      </div>

      {entries.length === 0 ? (
        <div className="glass-card rounded-[2rem] p-12 text-center flex flex-col items-center border-dashed border-white/20">
          <div className="w-20 h-20 bg-white/5 rounded-full flex items-center justify-center text-slate-500 mb-6">
            <Settings size={32} />
          </div>
          <h3 className="text-xl font-bold text-white mb-3">No profiles yet</h3>
          <p className="text-slate-400 mb-8 max-w-[300px]">Create your first encoding profile to save time on future encodes.</p>
          <button 
            onClick={() => onNavigate('builder')}
            className="btn-primary"
          >
            Create Profile
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {entries.map(([id, data]) => {
            const isExpanded = expandedId === id;
            return (
              <div key={id} className="glass-card rounded-2xl overflow-hidden transition-all duration-300">
                {/* Header / Summary */}
                <div 
                  className="p-6 cursor-pointer hover:bg-white/5 flex items-center justify-between"
                  onClick={() => setExpandedId(isExpanded ? null : id)}
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-bold text-white">{data.name || 'Unnamed Profile'}</h3>
                      {data.is_default && (
                        <span className="bg-[#ff3e3e]/20 text-[#ff3e3e] text-xs px-2 py-0.5 rounded flex items-center gap-1 border border-[#ff3e3e]/30">
                          <Star size={12} fill="currentColor" />
                          Default
                        </span>
                      )}
                    </div>
                    
                    <div className="flex items-center gap-6 text-sm text-slate-400">
                      <div className="flex items-center gap-1.5">
                        <Film size={14} className="text-slate-500" />
                        <span className="text-slate-300 font-medium">{data.video_codec}</span>
                        {data.video_params?.preset && (
                          <span className="bg-black/30 px-1.5 rounded text-xs">{data.video_params.preset}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Music size={14} className="text-slate-500" />
                        <span className="text-slate-300 font-medium">{data.audio_codec}</span>
                      </div>
                    </div>
                  </div>
                  
                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={(e) => { e.stopPropagation(); onSetDefault(id); }}
                      className={`p-2.5 rounded-xl border transition-all ${
                        data.is_default 
                          ? 'bg-[#ff3e3e]/10 border-[#ff3e3e]/30 text-[#ff3e3e]' 
                          : 'bg-white/5 border-white/10 text-slate-400 hover:bg-white/10 hover:text-white'
                      }`}
                      title="Set as Default"
                    >
                      <Star size={18} className={data.is_default ? 'fill-current' : ''} />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); onEdit(id); }}
                      className="p-2.5 rounded-xl bg-white/5 border border-white/10 text-slate-400 hover:bg-white/10 hover:text-white transition-all"
                      title="Edit"
                    >
                      <Edit size={18} />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleCopyJSON(id, data); }}
                      className={`p-2.5 rounded-xl border transition-all ${
                        copiedId === id 
                          ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-500' 
                          : 'bg-white/5 border-white/10 text-slate-400 hover:bg-white/10 hover:text-white'
                      }`}
                      title="Copy JSON"
                    >
                      {copiedId === id ? <Check size={18} /> : <Copy size={18} />}
                    </button>
                    <button
                      onClick={(e) => { 
                        e.stopPropagation(); 
                        if(confirm('Are you sure you want to delete this profile?')) onDelete(id); 
                      }}
                      className="p-2.5 rounded-xl bg-white/5 border border-white/10 text-slate-400 hover:bg-red-500/20 hover:text-red-500 hover:border-red-500/30 transition-all ml-2"
                      title="Delete"
                    >
                      <Trash2 size={18} />
                    </button>
                  </div>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="border-t border-white/10 p-6 bg-black/40">
                    <div className="flex justify-between items-center mb-4">
                      <h4 className="text-sm font-medium text-slate-400 uppercase tracking-wider">JSON Preview</h4>
                      {copiedId === id ? (
                        <span className="text-emerald-500 text-xs flex items-center gap-1 font-medium bg-emerald-500/10 px-2 py-1 rounded">
                          <CheckCircle size={12} /> Copied
                        </span>
                      ) : null}
                    </div>
                    <pre className="text-xs sm:text-sm text-slate-300 font-mono overflow-x-auto p-4 rounded-xl bg-[#0a0a0a] border border-white/5 shadow-inner">
                      <code>{
                        JSON.stringify(
                          Object.fromEntries(Object.entries(data).filter(([k]) => k !== 'is_default')), 
                          null, 
                          4
                        )
                      }</code>
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
