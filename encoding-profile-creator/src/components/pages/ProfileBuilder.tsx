import React, { useState, useEffect } from 'react';
import { ArrowLeft, Save, Copy, RotateCcw, Film, Music, Type, Tag, CheckCircle, Trash2 } from 'lucide-react';
import type { EncodingProfile } from '../../types';
import { QUICK_PRESETS, OPTIONS } from '../../data/presets';
import { SelectField } from '../shared/SelectField';
import { TextField } from '../shared/TextField';
import { ToggleField } from '../shared/ToggleField';
import { SliderField } from '../shared/SliderField';
import { SectionCard } from '../shared/SectionCard';
import { DynamicList } from '../shared/DynamicList';

interface ProfileBuilderProps {
  initialData?: EncodingProfile | null;
  onNavigate: (page: 'landing' | 'list') => void;
  onSave: (data: EncodingProfile) => void;
  onDelete?: () => void;
}

const DEFAULT_PROFILE: EncodingProfile = {
  name: "New Profile",
  video_codec: "libsvtav1",
  audio_codec: "libopus",
  subtitle_mode: "copy",
  metadata: {},
  video_params: {
    crf: 28,
    preset: 4,
    pix_fmt: "yuv420p10le"
  },
  audio_params: {
    bitrate: "128k"
  }
};

export const ProfileBuilder: React.FC<ProfileBuilderProps> = ({ initialData, onNavigate, onSave, onDelete }) => {
  const [profile, setProfile] = useState<EncodingProfile>(initialData || DEFAULT_PROFILE);
  const [customMetaList, setCustomMetaList] = useState<{key: string, value: string}[]>([]);
  const [dispositionList, setDispositionList] = useState<{key: string, value: string}[]>([]);
  const [copied, setCopied] = useState(false);

  // Sync custom metadata list and disposition list with profile object
  useEffect(() => {
    if (initialData) {
      const standardKeys = ['title', 'v_track', 'a_track', 's_track'];
      const custom = Object.entries(initialData.metadata || {})
        .filter(([key]) => !standardKeys.includes(key))
        .map(([key, value]) => ({ key, value: String(value) }));
      setCustomMetaList(custom);

      const disps = Object.entries(initialData.disposition || {})
        .map(([key, value]) => ({ key, value: String(value) }));
      setDispositionList(disps);
    }
  }, [initialData]);

  const updateProfile = (updates: Partial<EncodingProfile>) => {
    setProfile(prev => ({ ...prev, ...updates }));
  };

  const updateVideoParams = (updates: Partial<EncodingProfile['video_params']>) => {
    setProfile(prev => ({
      ...prev,
      video_params: { ...prev.video_params, ...updates }
    }));
  };

  const updateAudioParams = (updates: Partial<EncodingProfile['audio_params']>) => {
    setProfile(prev => ({
      ...prev,
      audio_params: { ...prev.audio_params, ...updates }
    }));
  };

  const updateMetadata = (key: string, value: string | undefined) => {
    setProfile(prev => {
      const newMeta = { ...prev.metadata };
      if (value === undefined || value === '') {
        delete newMeta[key];
      } else {
        newMeta[key] = value;
      }
      return { ...prev, metadata: newMeta };
    });
  };

  const applyCustomMetadata = (items: {key: string, value: string}[]) => {
    setCustomMetaList(items);
    setProfile(prev => {
      const standardKeys = ['title', 'v_track', 'a_track', 's_track'];
      const newMeta: Record<string, string> = {};
      
      // Keep standard keys
      standardKeys.forEach(k => {
        if (prev.metadata?.[k] !== undefined) newMeta[k] = prev.metadata[k]!;
      });
      
      // Add valid custom keys
      items.forEach(item => {
        if (item.key && item.value) {
          newMeta[item.key] = item.value;
        }
      });
      
      return { ...prev, metadata: newMeta };
    });
  };

  const applyDisposition = (items: {key: string, value: string}[]) => {
    setDispositionList(items);
    setProfile(prev => {
      const newDisp: Record<string, string> = {};
      items.forEach(item => {
        if (item.key && item.value) {
          newDisp[item.key] = item.value;
        }
      });
      return { ...prev, disposition: Object.keys(newDisp).length > 0 ? newDisp : undefined };
    });
  };

  const handleCopyJSON = () => {
    const { is_default, ...exportData } = profile;
    navigator.clipboard.writeText(JSON.stringify(exportData, null, 4));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getPresetOptions = () => {
    if (profile.video_codec === 'libsvtav1') return OPTIONS.svtAv1Presets;
    if (profile.video_codec === 'libx264' || profile.video_codec === 'libx265') return OPTIONS.x264x265Presets;
    return [];
  };

  return (
    <div className="container mx-auto px-4 py-8 max-w-[800px] relative z-10">
      
      {/* Sticky Top Bar */}
      <div className="sticky top-4 z-50 glass-card rounded-2xl p-4 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 shadow-2xl">
        <div className="flex items-center gap-4 w-full md:w-auto">
          <button 
            onClick={() => onNavigate('landing')}
            className="p-2 text-slate-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl transition-colors"
          >
            <ArrowLeft size={20} />
          </button>
          <input
            type="text"
            value={profile.name}
            onChange={(e) => updateProfile({ name: e.target.value })}
            className="bg-transparent border-none text-xl font-bold text-white focus:outline-none focus:ring-0 w-full md:w-64 placeholder:text-slate-600"
            placeholder="Profile Name"
          />
        </div>
        
        <div className="flex items-center gap-2 w-full md:w-auto justify-end">
          {initialData && (
            <button 
              onClick={() => {
                if (confirm('Delete this profile entirely?')) {
                  if (onDelete) onDelete();
                }
              }}
              className="p-2.5 text-slate-400 hover:text-red-500 bg-white/5 hover:bg-red-500/10 border border-transparent hover:border-red-500/20 rounded-xl transition-colors"
              title="Delete Profile"
            >
              <Trash2 size={18} />
            </button>
          )}
          <button 
            onClick={() => {
              if (confirm('Reset all settings?')) {
                setProfile(DEFAULT_PROFILE);
                setCustomMetaList([]);
              }
            }}
            className="p-2.5 text-slate-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl transition-colors"
            title="Reset"
          >
            <RotateCcw size={18} />
          </button>
          <button 
            onClick={handleCopyJSON}
            className={`btn-glass !py-2.5 !px-4 ${copied ? '!border-emerald-500/50 text-emerald-500' : ''}`}
          >
            {copied ? <CheckCircle size={18} /> : <Copy size={18} />}
            <span className="hidden sm:inline">{copied ? 'Copied' : 'Copy JSON'}</span>
          </button>
          <button 
            onClick={() => onSave(profile)}
            className="btn-primary !py-2.5 !px-6"
          >
            <Save size={18} />
            <span className="hidden sm:inline">Save Profile</span>
          </button>
        </div>
      </div>

      {/* Quick Presets */}
      <div className="mb-8">
        <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-4 ml-2">Quick Presets</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {QUICK_PRESETS.map((preset, idx) => (
            <button
              key={idx}
              onClick={() => {
                setProfile({ ...preset, name: profile.name });
                const standardKeys = ['title', 'v_track', 'a_track', 's_track'];
                const custom = Object.entries(preset.metadata || {})
                  .filter(([key]) => !standardKeys.includes(key))
                  .map(([key, value]) => ({ key, value: String(value) }));
                setCustomMetaList(custom);
              }}
              className="text-left p-3 rounded-xl bg-black/40 border border-white/5 hover:border-[#ff3e3e]/50 hover:bg-[#ff3e3e]/10 transition-all group"
            >
              <div className="text-sm font-bold text-white group-hover:text-[#ff3e3e] truncate">{preset.name}</div>
              <div className="text-xs text-slate-500 mt-1 truncate">{preset.video_codec} • {preset.audio_codec}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Video Settings */}
      <SectionCard title="Video Settings" icon={<Film size={20} />} defaultOpen={true}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <SelectField
            label="Video Codec"
            value={profile.video_codec}
            onChange={(e) => updateProfile({ video_codec: e.target.value })}
            options={OPTIONS.videoCodecs}
          />
          
          <SelectField
            label="Pixel Format"
            value={profile.video_params?.pix_fmt || 'yuv420p10le'}
            onChange={(e) => updateVideoParams({ pix_fmt: e.target.value })}
            options={OPTIONS.pixelFormats}
          />
          
          {profile.video_codec !== 'copy' && (
            <div className="md:col-span-2">
              <SliderField
                label="CRF (Quality)"
                value={profile.video_params?.crf ?? 28}
                min={0}
                max={63}
                onChange={(e) => updateVideoParams({ crf: parseInt(e.target.value) })}
                formatValue={(v) => `${v} ${v < 18 ? '(Lossless)' : v > 35 ? '(Low Qual)' : ''}`}
              />
            </div>
          )}

          {getPresetOptions().length > 0 && (
            <SelectField
              label="Preset / Speed"
              value={profile.video_params?.preset || (profile.video_codec === 'libsvtav1' ? 4 : 'medium')}
              onChange={(e) => updateVideoParams({ preset: profile.video_codec === 'libsvtav1' ? parseInt(e.target.value) : e.target.value })}
              options={getPresetOptions()}
            />
          )}

          <SelectField
            label="Format Profile"
            value={profile.video_params?.profile?.toString() || ''}
            onChange={(e) => updateVideoParams({ profile: e.target.value })}
            options={OPTIONS.formatProfiles}
          />

          <SelectField
            label="Format Level"
            value={profile.video_params?.level || ''}
            onChange={(e) => updateVideoParams({ level: e.target.value })}
            options={OPTIONS.formatLevels}
          />

          <SelectField
            label="Color Primaries"
            value={profile.video_params?.color_primaries || ''}
            onChange={(e) => updateVideoParams({ color_primaries: e.target.value })}
            options={OPTIONS.colorSpaces}
          />

          <SelectField
            label="Color Transfer (TRC)"
            value={profile.video_params?.color_trc || ''}
            onChange={(e) => updateVideoParams({ color_trc: e.target.value })}
            options={OPTIONS.colorSpaces}
          />

          <SelectField
            label="Colorspace"
            value={profile.video_params?.colorspace || ''}
            onChange={(e) => updateVideoParams({ colorspace: e.target.value })}
            options={OPTIONS.colorSpaces}
          />

          <div className="md:col-span-1">
            <TextField
              label="Extra Parameters"
              value={profile.video_params?.extra_params || ''}
              onChange={(e) => updateVideoParams({ extra_params: e.target.value })}
              placeholder="e.g. tune=animation:film-grain=4 (Colon-separated)"
            />
          </div>
        </div>
      </SectionCard>

      {/* Audio Settings */}
      <SectionCard title="Audio Settings" icon={<Music size={20} />} defaultOpen={false}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <SelectField
            label="Audio Codec"
            value={profile.audio_codec}
            onChange={(e) => updateProfile({ audio_codec: e.target.value })}
            options={OPTIONS.audioCodecs}
          />
          
          {profile.audio_codec !== 'copy' && profile.audio_codec !== 'flac' && (
            <SelectField
              label="Bitrate"
              value={profile.audio_params?.bitrate || '128k'}
              onChange={(e) => updateAudioParams({ bitrate: e.target.value })}
              options={OPTIONS.audioBitrates}
            />
          )}
          
          {profile.audio_codec !== 'copy' && (
            <SelectField
              label="Channels"
              value={profile.audio_params?.channels || 0}
              onChange={(e) => updateAudioParams({ channels: parseInt(e.target.value) })}
              options={OPTIONS.audioChannels}
            />
          )}

          {profile.audio_codec !== 'copy' && (
            <div className="md:col-span-2 pt-2">
              <ToggleField
                label="Variable Bitrate (VBR)"
                checked={!!profile.audio_params?.vbr}
                onChange={(checked) => updateAudioParams({ vbr: checked })}
                description="Optimize bitrate based on audio complexity"
              />
            </div>
          )}
        </div>
      </SectionCard>

      {/* Subtitle Settings */}
      <SectionCard title="Subtitle Settings" icon={<Type size={20} />} defaultOpen={false}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <SelectField
            label="Subtitle Mode"
            value={profile.subtitle_mode}
            onChange={(e) => updateProfile({ subtitle_mode: e.target.value })}
            options={OPTIONS.subtitleModes}
          />
        </div>
      </SectionCard>

      {/* Metadata & Stream Tags */}
      <SectionCard title="Metadata & Stream Tags" icon={<Tag size={20} />} defaultOpen={false}>
        <div className="flex flex-col gap-8">
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <TextField
              label="Rename File To"
              value={profile.rename || ''}
              onChange={(e) => updateProfile({ rename: e.target.value })}
              placeholder="e.g. {title} - {episode}.mkv"
            />
            <TextField
              label="Global Title"
              value={profile.metadata?.title || ''}
              onChange={(e) => updateMetadata('title', e.target.value)}
              placeholder="e.g. {basename} (Supports dynamic variables)"
            />
          </div>

          <TextField
            label="Cover Image URL (Direct or Telegram Link)"
            value={profile.cover_image || ''}
            onChange={(e) => updateProfile({ cover_image: e.target.value })}
            placeholder="e.g. https://t.me/channel/123 or https://example.com/poster.jpg"
          />

          <div className="border-t border-white/10 pt-6">
            <h4 className="text-sm font-bold text-slate-300 mb-4">Track Selection</h4>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <TextField
                label="Video Track"
                value={profile.metadata?.v_track || ''}
                onChange={(e) => updateMetadata('v_track', e.target.value)}
                placeholder="e.g. 0 or ?"
              />
              <TextField
                label="Audio Track"
                value={profile.metadata?.a_track || ''}
                onChange={(e) => updateMetadata('a_track', e.target.value)}
                placeholder="e.g. 0 or ?"
              />
              <TextField
                label="Subtitle Track"
                value={profile.metadata?.s_track || ''}
                onChange={(e) => updateMetadata('s_track', e.target.value)}
                placeholder="e.g. 0 or ?"
              />
            </div>
            <p className="text-xs text-slate-500 mt-2">Use index numbers (0, 1, 2) or "?" for all tracks.</p>
          </div>

          <div className="border-t border-white/10 pt-6">
            <DynamicList
              label="Custom Stream Metadata Tags"
              items={customMetaList}
              onChange={applyCustomMetadata}
              addButtonText="Add Stream Tag"
              keyPlaceholder="s:a:0"
              valuePlaceholder="title=English Dub"
            />
            <div className="bg-black/20 p-3 rounded-lg border border-white/5 mt-4">
              <p className="text-xs text-slate-400 font-mono mb-1">Common Keys:</p>
              <ul className="text-xs text-slate-500 list-disc list-inside">
                <li>s:v:0 (First video stream)</li>
                <li>s:a:0 (First audio stream)</li>
                <li>s:s:0 (First subtitle stream)</li>
              </ul>
            </div>
          </div>

          <div className="border-t border-white/10 pt-6">
            <DynamicList
              label="Stream Disposition Flags"
              items={dispositionList}
              onChange={applyDisposition}
              addButtonText="Add Disposition"
              keyPlaceholder="v:0"
              valuePlaceholder="Select disposition..."
              valueOptions={[
                { label: "0 (Remove all flags)", value: "0" },
                { label: "default (Mark as default)", value: "default" },
                { label: "forced (Mark as forced)", value: "forced" },
                { label: "default+forced (Default & Forced)", value: "default+forced" },
                { label: "dub (Dub track)", value: "dub" },
                { label: "comment (Commentary)", value: "comment" },
                { label: "hearing_impaired", value: "hearing_impaired" },
                { label: "visual_impaired", value: "visual_impaired" },
                { label: "captions", value: "captions" }
              ]}
            />
            <div className="bg-black/20 p-3 rounded-lg border border-white/5 mt-4">
              <p className="text-xs text-slate-400 font-mono mb-1">Disposition Values:</p>
              <ul className="text-xs text-slate-500 list-disc list-inside">
                <li>Select from the dropdown to assign flags correctly.</li>
              </ul>
              <p className="text-xs text-slate-400 font-mono mt-2 mb-1">Common Keys:</p>
              <ul className="text-xs text-slate-500 list-disc list-inside">
                <li>v:0 (First video) · a:0, a:1 (Audio streams)</li>
                <li>s:0, s:1 (Subtitle streams)</li>
              </ul>
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Live JSON Preview */}
      <div className="mt-8">
        <div className="flex justify-between items-center mb-4 px-2">
          <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider">Live Output</h3>
        </div>
        <div className="glass-card rounded-2xl p-6 bg-black/60 relative group">
          <button 
            onClick={handleCopyJSON}
            className="absolute top-4 right-4 p-2 bg-white/10 hover:bg-[#ff3e3e]/20 text-slate-300 hover:text-[#ff3e3e] rounded-lg border border-white/10 transition-all opacity-0 group-hover:opacity-100"
            title="Copy JSON"
          >
            {copied ? <CheckCircle size={16} /> : <Copy size={16} />}
          </button>
          <pre className="text-xs sm:text-sm text-slate-300 font-mono overflow-x-auto selection:bg-[#ff3e3e]/30 selection:text-white">
            <code>{
              JSON.stringify(
                Object.fromEntries(Object.entries(profile).filter(([k]) => k !== 'is_default')), 
                null, 
                4
              )
            }</code>
          </pre>
        </div>
      </div>

    </div>
  );
};
