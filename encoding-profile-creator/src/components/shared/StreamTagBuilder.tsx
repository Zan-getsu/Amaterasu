import React from 'react';
import { Plus, Trash2 } from 'lucide-react';

interface KeyValuePair {
  key: string;
  value: string;
}

interface StreamTagBuilderProps {
  label: string;
  prefix: string; // e.g., 's:v:' for video metadata, 'v:' for video disposition
  items: KeyValuePair[]; // The global list
  onChange: (items: KeyValuePair[]) => void;
  addButtonText?: string;
  valuePlaceholder?: string;
  valueOptions?: { label: string, value: string }[];
}

const LANGUAGES = [
  { value: 'eng', label: 'English (eng)' },
  { value: 'jpn', label: 'Japanese (jpn)' },
  { value: 'spa', label: 'Spanish (spa)' },
  { value: 'fra', label: 'French (fra)' },
  { value: 'ger', label: 'German (ger)' },
  { value: 'ita', label: 'Italian (ita)' },
  { value: 'kor', label: 'Korean (kor)' },
  { value: 'chi', label: 'Chinese (chi)' },
  { value: 'rus', label: 'Russian (rus)' },
  { value: 'ara', label: 'Arabic (ara)' },
  { value: 'hin', label: 'Hindi (hin)' },
  { value: 'por', label: 'Portuguese (por)' },
];

export const StreamTagBuilder: React.FC<StreamTagBuilderProps> = ({ 
  label, 
  prefix,
  items, 
  onChange,
  addButtonText = "Add Tag",
  valuePlaceholder = "Value",
  valueOptions
}) => {
  // Filter items that belong to this prefix. We ignore trailing spaces when matching the prefix.
  const localItems = items.filter(item => item.key.trim().startsWith(prefix));
  const otherItems = items.filter(item => !item.key.trim().startsWith(prefix));

  const handleAdd = () => {
    onChange([...items, { key: `${prefix}0`, value: valueOptions ? '' : 'title=' }]);
  };

  const handleRemove = (localIndex: number) => {
    const newLocalItems = [...localItems];
    newLocalItems.splice(localIndex, 1);
    onChange([...otherItems, ...newLocalItems]);
  };

  const handleKeyChange = (localIndex: number, newTrackVal: string) => {
    const newLocalItems = [...localItems];
    // Preserve trailing spaces if there were any, though applyCustomMetadata handles it.
    newLocalItems[localIndex].key = `${prefix}${newTrackVal}`;
    onChange([...otherItems, ...newLocalItems]);
  };

  const handleValueChange = (localIndex: number, newValue: string) => {
    const newLocalItems = [...localItems];
    newLocalItems[localIndex].value = newValue;
    onChange([...otherItems, ...newLocalItems]);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-slate-300">{label}</label>
        <button
          type="button"
          onClick={handleAdd}
          className="text-xs flex items-center gap-1 text-[#ff3e3e] hover:text-[#ff7a00] transition-colors bg-white/5 hover:bg-white/10 px-2 py-1 rounded border border-white/5"
        >
          <Plus size={14} />
          {addButtonText}
        </button>
      </div>
      
      {localItems.length === 0 ? (
        <div className="text-center p-4 rounded-lg bg-black/20 border border-white/5 text-slate-500 text-sm">
          No tags added for this stream. Click "{addButtonText}" to add one.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {localItems.map((item, index) => {
            const trackIndex = item.key.trim().slice(prefix.length);
            
            // If it's a disposition field, it's simple
            if (valueOptions) {
              return (
                <div key={index} className="flex gap-2 items-start">
                  <div className="w-1/3">
                    <select
                      value={trackIndex}
                      onChange={(e) => handleKeyChange(index, e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 appearance-none"
                    >
                      <option value="0">Track 1</option>
                      <option value="1">Track 2</option>
                      <option value="2">Track 3</option>
                      <option value="3">Track 4</option>
                      <option value="?">All Tracks (?)</option>
                    </select>
                  </div>
                  <div className="flex-1 flex gap-2">
                    <select
                      value={item.value}
                      onChange={(e) => handleValueChange(index, e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 appearance-none"
                    >
                      <option value="" disabled className="text-slate-500">{valuePlaceholder}</option>
                      {valueOptions.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => handleRemove(index)}
                      className="p-2 text-slate-500 hover:text-red-500 bg-white/5 hover:bg-red-500/10 rounded-lg border border-white/5 transition-colors"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              );
            }

            // Otherwise, it's a metadata field. We split key=value
            const splitIdx = item.value.indexOf('=');
            let tagType = 'custom';
            let tagKey = item.value;
            let tagValue = '';

            if (splitIdx !== -1) {
              tagKey = item.value.substring(0, splitIdx);
              tagValue = item.value.substring(splitIdx + 1);
              if (['title', 'language', 'handler_name'].includes(tagKey)) {
                tagType = tagKey;
              }
            }

            const handleMetadataChange = (newType: string, newKey: string, newVal: string) => {
              if (newType === 'custom') {
                handleValueChange(index, newKey);
              } else {
                handleValueChange(index, `${newType}=${newVal}`);
              }
            };

            return (
              <div key={index} className="flex gap-2 items-start">
                <div className="w-[28%]">
                  <select
                    value={trackIndex}
                    onChange={(e) => handleKeyChange(index, e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 appearance-none"
                  >
                    <option value="0">Track 1</option>
                    <option value="1">Track 2</option>
                    <option value="2">Track 3</option>
                    <option value="3">Track 4</option>
                    <option value="?">All Tracks (?)</option>
                  </select>
                </div>
                <div className="flex-1 flex gap-2">
                  <select
                    value={tagType}
                    onChange={(e) => {
                      const t = e.target.value;
                      if (t === 'custom') handleMetadataChange(t, tagKey, tagValue);
                      else handleMetadataChange(t, t, tagValue);
                    }}
                    className="w-1/3 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 appearance-none"
                  >
                    <option value="title">Title</option>
                    <option value="language">Language</option>
                    <option value="handler_name">Handler</option>
                    <option value="custom">Custom</option>
                  </select>
                  
                  {tagType === 'language' ? (
                    <select
                      value={tagValue}
                      onChange={(e) => handleMetadataChange(tagType, tagKey, e.target.value)}
                      className="w-2/3 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 appearance-none"
                    >
                      <option value="" disabled>Select Language...</option>
                      {LANGUAGES.map(lang => (
                        <option key={lang.value} value={lang.value}>{lang.label}</option>
                      ))}
                      <option value="und">Undefined (und)</option>
                    </select>
                  ) : tagType === 'custom' ? (
                    <input
                      type="text"
                      placeholder="e.g. BPS=120"
                      value={item.value}
                      onChange={(e) => handleValueChange(index, e.target.value)}
                      className="w-2/3 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-[#ff3e3e]/50"
                    />
                  ) : (
                    <input
                      type="text"
                      placeholder={`Enter ${tagType}...`}
                      value={tagValue}
                      onChange={(e) => handleMetadataChange(tagType, tagKey, e.target.value)}
                      className="w-2/3 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-[#ff3e3e]/50"
                    />
                  )}
                  
                  <button
                    type="button"
                    onClick={() => handleRemove(index)}
                    className="p-2 text-slate-500 hover:text-red-500 bg-white/5 hover:bg-red-500/10 rounded-lg border border-white/5 transition-colors"
                    title="Remove"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
