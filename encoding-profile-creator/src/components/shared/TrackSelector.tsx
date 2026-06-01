import React, { useState } from 'react';
import { SelectField } from './SelectField';
import { TextField } from './TextField';

interface TrackSelectorProps {
  label: string;
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
}

const COMMON_TRACKS = [
  { label: 'Keep All Tracks (?)', value: '?' },
  { label: 'Track 1 Only (0)', value: '0' },
  { label: 'Track 2 Only (1)', value: '1' },
  { label: 'Tracks 1 & 2 (0,1)', value: '0,1' },
  { label: 'Tracks 2 & 1 (1,0)', value: '1,0' },
];

export const TrackSelector: React.FC<TrackSelectorProps> = ({ label, value, onChange, placeholder = "e.g. 0,1 or ?" }) => {
  const valueIsCustom = !!value && !COMMON_TRACKS.find(t => t.value === value);
  const [customMode, setCustomMode] = useState(valueIsCustom);
  const isCustom = customMode || valueIsCustom;

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    if (val === 'custom') {
      setCustomMode(true);
      onChange('');
    } else {
      setCustomMode(false);
      onChange(val);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <SelectField
        label={label}
        value={isCustom ? 'custom' : (value || '?')}
        onChange={handleSelectChange}
        options={[
          ...COMMON_TRACKS,
          { label: 'Custom Mapping...', value: 'custom' }
        ]}
      />
      {isCustom && (
        <div className="mt-1">
          <TextField
            label=""
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
          />
          <p className="text-xs text-slate-500 mt-1">Enter raw FFmpeg track index (e.g. 0,1,2). Use 0-based indexing.</p>
        </div>
      )}
    </div>
  );
};
