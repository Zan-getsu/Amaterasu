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

export const StreamTagBuilder: React.FC<StreamTagBuilderProps> = ({ 
  label, 
  prefix,
  items, 
  onChange,
  addButtonText = "Add Tag",
  valuePlaceholder = "Value (e.g. title=English)",
  valueOptions
}) => {
  // Filter items that belong to this prefix
  const localItems = items.filter(item => item.key.startsWith(prefix));
  // Items that belong to other prefixes (to preserve them during updates)
  const otherItems = items.filter(item => !item.key.startsWith(prefix));

  const handleAdd = () => {
    // Default to track 0
    onChange([...items, { key: `${prefix}0`, value: '' }]);
  };

  const handleRemove = (localIndex: number) => {
    const newLocalItems = [...localItems];
    newLocalItems.splice(localIndex, 1);
    onChange([...otherItems, ...newLocalItems]);
  };

  const handleChange = (localIndex: number, field: 'key' | 'value', value: string) => {
    const newLocalItems = [...localItems];
    if (field === 'key') {
      newLocalItems[localIndex].key = `${prefix}${value}`;
    } else {
      newLocalItems[localIndex].value = value;
    }
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
            // Extract the track index (e.g., 's:v:0' -> '0')
            const trackIndex = item.key.slice(prefix.length);
            
            return (
              <div key={index} className="flex gap-2 items-start">
                <div className="w-1/3">
                  <select
                    value={trackIndex}
                    onChange={(e) => handleChange(index, 'key', e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 focus:ring-1 focus:ring-[#ff3e3e]/50 appearance-none"
                  >
                    <option value="0">Track 1</option>
                    <option value="1">Track 2</option>
                    <option value="2">Track 3</option>
                    <option value="3">Track 4</option>
                    <option value="4">Track 5</option>
                    <option value="?">All Tracks (?)</option>
                  </select>
                </div>
                <div className="flex-1 flex gap-2">
                  {valueOptions ? (
                    <select
                      value={item.value}
                      onChange={(e) => handleChange(index, 'value', e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-[#ff3e3e]/50 focus:ring-1 focus:ring-[#ff3e3e]/50 appearance-none"
                    >
                      <option value="" disabled className="text-slate-500">{valuePlaceholder}</option>
                      {valueOptions.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      placeholder={valuePlaceholder}
                      value={item.value}
                      onChange={(e) => handleChange(index, 'value', e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-[#ff3e3e]/50 focus:ring-1 focus:ring-[#ff3e3e]/50"
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
