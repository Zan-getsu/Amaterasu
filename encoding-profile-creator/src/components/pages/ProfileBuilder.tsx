import React, { useState, useEffect } from 'react';
import { ArrowLeft, Save, Copy, RotateCcw, Film, Music, Type, Tag, CheckCircle, Trash2, Download, Terminal, Code } from 'lucide-react';
import type { EncodingProfile } from '../../types';
import { QUICK_PRESETS, OPTIONS } from '../../data/presets';
import { SelectField } from '../shared/SelectField';
import { TextField } from '../shared/TextField';
import { ToggleField } from '../shared/ToggleField';
import { SliderField } from '../shared/SliderField';
import { SectionCard } from '../shared/SectionCard';
import { TrackSelector } from '../shared/TrackSelector';
import { StreamTagBuilder } from '../shared/StreamTagBuilder';

const DISPOSITION_OPTIONS = [
  { label: "0 (Remove all flags)", value: "0" },
  { label: "default (Mark as default)", value: "default" },
  { label: "forced (Mark as forced)", value: "forced" },
  { label: "default+forced (Default & Forced)", value: "default+forced" },
  { label: "dub (Dub track)", value: "dub" },
  { label: "comment (Commentary)", value: "comment" },
  { label: "hearing_impaired", value: "hearing_impaired" },
  { label: "visual_impaired", value: "visual_impaired" },
  { label: "captions", value: "captions" }
];

const DYNAMIC_VARS = ['{title}', '{episode}', '{quality}', '{resolution}', '{source}', '{audio}'];

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
  const [previewMode, setPreviewMode] = useState<'json' | 'ffmpeg'>('json');

  // Sync custom metadata list and disposition list with profile object
  useEffect(() => {
    if (initialData) {
      const standardKeys = ['title', 'v_track', 'a_track', 's_track'];
      const custom = Object.entries(initialData.metadata || {})
        .filter(([key]) => !standardKeys.includes(key.trim()))
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
      
      // Add valid custom keys, appending trailing spaces for duplicate keys
      items.forEach(item => {
        if (item.key && item.value) {
          let uniqueKey = item.key.trim();
          while (newMeta[uniqueKey] !== undefined) {
             uniqueKey += ' ';
          }
          newMeta[uniqueKey] = item.value;
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

  const handleImportJSON = () => {
    const input = prompt("Paste your profile JSON here:");
    if (!input) return;
    try {
      const parsed = JSON.parse(input);
      setProfile({ ...DEFAULT_PROFILE, ...parsed, name: parsed.name || "Imported Profile" });
      
      const standardKeys = ['title', 'v_track', 'a_track', 's_track'];
      const custom = Object.entries(parsed.metadata || {})
        .filter(([key]) => !standardKeys.includes(key.trim()))
        .map(([key, value]) => ({ key, value: String(value) }));
      setCustomMetaList(custom);

      const disps = Object.entries(parsed.disposition || {})
        .map(([key, value]) => ({ key, value: String(value) }));
      setDispositionList(disps);
    } catch (e) {
      alert("Invalid JSON format!");
    }
  };

  const insertVar = (field: 'rename' | 'title', variable: string) => {
    if (field === 'rename') {
      updateProfile({ rename: (profile.rename || '') + variable });
    } else {
      updateMetadata('title', (profile.metadata?.title || '') + variable);
    }
  };

  const getPresetOptions = () => {
    if (profile.video_codec === 'libsvtav1') return OPTIONS.svtAv1Presets;
    if (profile.video_codec === 'libx264' || profile.video_codec === 'libx265') return OPTIONS.x264x265Presets;
    return [];
  };

  const generateFFmpegCommand = () => {
    let cmd = `ffmpeg -i input.mkv \\\n`;
    
    if (profile.metadata?.v_track) cmd += `  -map 0:v:${profile.metadata.v_track === '?' ? '' : profile.metadata.v_track} \\\n`;
    if (profile.metadata?.a_track) cmd += `  -map 0:a:${profile.metadata.a_track === '?' ? '' : profile.metadata.a_track} \\\n`;
    if (profile.metadata?.s_track) cmd += `  -map 0:s:${profile.metadata.s_track === '?' ? '' : profile.metadata.s_track} \\\n`;

    cmd += `  -c:v ${profile.video_codec} `;
    if (profile.video_codec !== 'copy') {
      if (profile.video_params?.crf !== undefined) cmd += `-crf ${profile.video_params.crf} `;
      if (profile.video_params?.preset !== undefined) cmd += `-preset ${profile.video_params.preset} `;
      if (profile.video_params?.pix_fmt) cmd += `-pix_fmt ${profile.video_params.pix_fmt} `;
    }
    cmd += `\\\n`;

    cmd += `  -c:a ${profile.audio_codec} `;
    if (profile.audio_codec !== 'copy' && profile.audio_codec !== 'flac') {
      if (profile.audio_params?.bitrate) cmd += `-b:a ${profile.audio_params.bitrate} `;
    }
    cmd += `\\\n`;

    cmd += `  -c:s ${profile.subtitle_mode} \\\n`;

    if (profile.metadata) {
      Object.entries(profile.metadata).forEach(([k, v]) => {
        if (!['v_track', 'a_track', 's_track', 'title'].includes(k.trim())) {
          if (k.includes(':')) {
             cmd += `  -metadata:${k.trim()} "${v}" \\\n`;
          } else {
             cmd += `  -metadata "${k}=${v}" \\\n`;
          }
        }
      });
    }

    if (profile.disposition) {
      Object.entries(profile.disposition).forEach(([k, v]) => {
        cmd += `  -disposition:${k.trim()} ${v} \\\n`;
      });
    }

    cmd += `  output.mkv`;
    return cmd;
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
          <button 
            onClick={handleImportJSON}
            className="p-2.5 text-slate-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl transition-colors hidden sm:block"
            title="Import Profile"
          >
            <Download size={18} />
          </button>
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
                  .filter(([key]) => !standardKeys.includes(key.trim()))
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
            tooltip="Bit depth and chroma subsampling. yuv420p10le is recommended for 10-bit AV1/HEVC."
            value={profile.video_params?.pix_fmt || 'yuv420p10le'}
            onChange={(e) => updateVideoParams({ pix_fmt: e.target.value })}
            options={OPTIONS.pixelFormats}
          />
          
          {profile.video_codec !== 'copy' && (
            <div className="md:col-span-2">
              <SliderField
                label="CRF (Quality)"
                tooltip="Constant Rate Factor. Lower value = Higher quality and larger file size. 18 is near lossless, 24-28 is standard for AV1/HEVC."
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
              tooltip="Slower presets provide better compression efficiency at the cost of encoding time."
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
          
          <div className="md:col-span-2 border-t border-white/10 pt-6 mt-2">
            <h4 className="text-sm font-bold text-slate-300 mb-4">Video Track Selection & Tags</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <TrackSelector
                label="Video Tracks to Keep"
                value={profile.metadata?.v_track || ''}
                onChange={(val) => updateMetadata('v_track', val)}
              />
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
              <StreamTagBuilder
                label="Video Metadata Tags"
                prefix="s:v:"
                items={customMetaList}
                onChange={applyCustomMetadata}
              />
              <StreamTagBuilder
                label="Video Disposition Flags"
                prefix="v:"
                items={dispositionList}
                onChange={applyDisposition}
                valueOptions={DISPOSITION_OPTIONS}
                valuePlaceholder="Select disposition..."
              />
            </div>
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

          <div className="md:col-span-2 border-t border-white/10 pt-6 mt-2">
            <h4 className="text-sm font-bold text-slate-300 mb-4">Audio Track Selection & Tags</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <TrackSelector
                label="Audio Tracks to Keep"
                value={profile.metadata?.a_track || ''}
                onChange={(val) => updateMetadata('a_track', val)}
              />
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
              <StreamTagBuilder
                label="Audio Metadata Tags"
                prefix="s:a:"
                items={customMetaList}
                onChange={applyCustomMetadata}
              />
              <StreamTagBuilder
                label="Audio Disposition Flags"
                prefix="a:"
                items={dispositionList}
                onChange={applyDisposition}
                valueOptions={DISPOSITION_OPTIONS}
                valuePlaceholder="Select disposition..."
              />
            </div>
          </div>
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
          
          <div className="md:col-span-2 border-t border-white/10 pt-6 mt-2">
            <h4 className="text-sm font-bold text-slate-300 mb-4">Subtitle Track Selection & Tags</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <TrackSelector
                label="Subtitle Tracks to Keep"
                value={profile.metadata?.s_track || ''}
                onChange={(val) => updateMetadata('s_track', val)}
              />
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
              <StreamTagBuilder
                label="Subtitle Metadata Tags"
                prefix="s:s:"
                items={customMetaList}
                onChange={applyCustomMetadata}
              />
              <StreamTagBuilder
                label="Subtitle Disposition Flags"
                prefix="s:"
                items={dispositionList}
                onChange={applyDisposition}
                valueOptions={DISPOSITION_OPTIONS}
                valuePlaceholder="Select disposition..."
              />
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Global Metadata */}
      <SectionCard title="Global Metadata" icon={<Tag size={20} />} defaultOpen={false}>
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <TextField
                label="Rename File To"
                value={profile.rename || ''}
                onChange={(e) => updateProfile({ rename: e.target.value })}
                placeholder="e.g. {title} - {episode}.mkv"
              />
              <div className="flex flex-wrap gap-1.5 mt-2">
                {DYNAMIC_VARS.map(v => (
                  <button key={v} onClick={() => insertVar('rename', v)} className="text-[10px] bg-white/5 hover:bg-[#ff3e3e]/20 text-slate-400 hover:text-white px-1.5 py-0.5 rounded border border-white/5 transition-colors">
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <TextField
                label="Global Title"
                value={profile.metadata?.title || ''}
                onChange={(e) => updateMetadata('title', e.target.value)}
                placeholder="e.g. {basename}"
              />
              <div className="flex flex-wrap gap-1.5 mt-2">
                {DYNAMIC_VARS.map(v => (
                  <button key={v} onClick={() => insertVar('title', v)} className="text-[10px] bg-white/5 hover:bg-[#ff3e3e]/20 text-slate-400 hover:text-white px-1.5 py-0.5 rounded border border-white/5 transition-colors">
                    {v}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <TextField
            label="Cover Image URL (Direct or Telegram Link)"
            value={profile.cover_image || ''}
            onChange={(e) => updateProfile({ cover_image: e.target.value })}
            placeholder="e.g. https://t.me/channel/123 or https://example.com/poster.jpg"
          />
        </div>
      </SectionCard>

      {/* Live Preview Section */}
      <div className="mt-8">
        <div className="flex justify-between items-center mb-4 px-2">
          <div className="flex bg-black/40 p-1 rounded-lg border border-white/5">
            <button 
              onClick={() => setPreviewMode('json')}
              className={`px-3 py-1.5 text-xs font-bold rounded flex items-center gap-2 transition-all ${previewMode === 'json' ? 'bg-[#ff3e3e] text-white' : 'text-slate-400 hover:text-white'}`}
            >
              <Code size={14} /> JSON Layout
            </button>
            <button 
              onClick={() => setPreviewMode('ffmpeg')}
              className={`px-3 py-1.5 text-xs font-bold rounded flex items-center gap-2 transition-all ${previewMode === 'ffmpeg' ? 'bg-[#ff3e3e] text-white' : 'text-slate-400 hover:text-white'}`}
            >
              <Terminal size={14} /> FFmpeg Command
            </button>
          </div>
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
            {previewMode === 'json' ? (
              <code>{
                JSON.stringify(
                  Object.fromEntries(Object.entries(profile).filter(([k]) => k !== 'is_default')), 
                  null, 
                  4
                )
              }</code>
            ) : (
              <code>{generateFFmpegCommand()}</code>
            )}
          </pre>
        </div>
      </div>

    </div>
  );
};
