import React from 'react';
import { Tooltip } from './Tooltip';

interface SelectFieldProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  icon?: React.ReactNode;
  tooltip?: string;
  options: { value: string | number; label: string }[];
}

export const SelectField: React.FC<SelectFieldProps> = ({ label, icon, tooltip, options, className = '', ...props }) => {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label className="text-sm font-medium text-slate-300 flex items-center">
        {icon && <span className="text-slate-400 mr-2">{icon}</span>}
        {label}
        {tooltip && <Tooltip content={tooltip} />}
      </label>
      <div className="relative">
        <select
          className="w-full appearance-none bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-slate-100 font-medium focus:outline-none focus:border-[#ff3e3e]/50 focus:ring-1 focus:ring-[#ff3e3e]/50 transition-all disabled:opacity-50"
          {...props}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-[#0f0f0f] text-slate-200">
              {opt.label}
            </option>
          ))}
        </select>
        <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" /></svg>
        </div>
      </div>
    </div>
  );
};
