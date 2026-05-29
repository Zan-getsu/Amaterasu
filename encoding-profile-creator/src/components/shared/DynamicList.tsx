import React from 'react';
import { Plus, Trash2 } from 'lucide-react';

interface KeyValuePair {
  key: string;
  value: string;
}

interface DynamicListProps {
  label: string;
  items: KeyValuePair[];
  onChange: (items: KeyValuePair[]) => void;
  addButtonText?: string;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  valueOptions?: { label: string, value: string }[];
}

export const DynamicList: React.FC<DynamicListProps> = ({ 
  label, 
  items, 
  onChange,
  addButtonText = "Add Entry",
  keyPlaceholder = "Key (e.g. s:v:0)",
  valuePlaceholder = "Value (e.g. title=English)",
  valueOptions
}) => {
  const handleAdd = () => {
    onChange([...items, { key: '', value: '' }]);
  };

  const handleRemove = (index: number) => {
    const newItems = [...items];
    newItems.splice(index, 1);
    onChange(newItems);
  };

  const handleChange = (index: number, field: 'key' | 'value', value: string) => {
    const newItems = [...items];
    newItems[index][field] = value;
    onChange(newItems);
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
      
      {items.length === 0 ? (
        <div className="text-center p-4 rounded-lg bg-black/20 border border-white/5 text-slate-500 text-sm">
          No entries added. Click "{addButtonText}" to add one.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {items.map((item, index) => (
            <div key={index} className="flex gap-2 items-start">
              <div className="w-1/3">
                <input
                  type="text"
                  placeholder={keyPlaceholder}
                  value={item.key}
                  onChange={(e) => handleChange(index, 'key', e.target.value)}
                  className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-[#ff3e3e]/50 focus:ring-1 focus:ring-[#ff3e3e]/50"
                />
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
          ))}
        </div>
      )}
    </div>
  );
};
