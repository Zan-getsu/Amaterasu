import React from 'react';
import { Tooltip } from './Tooltip';

interface TextFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  icon?: React.ReactNode;
  tooltip?: string;
}

export const TextField: React.FC<TextFieldProps> = ({ label, icon, tooltip, className = '', ...props }) => {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <label className="text-sm font-medium text-slate-300 flex items-center gap-2">
          {icon && <span className="text-slate-400">{icon}</span>}
          {label}
          {tooltip && <Tooltip content={tooltip} />}
        </label>
      )}
      <input
        className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-slate-100 placeholder:text-slate-500 font-medium focus:outline-none focus:border-[#ff3e3e]/50 focus:ring-1 focus:ring-[#ff3e3e]/50 transition-all disabled:opacity-50"
        {...props}
      />
    </div>
  );
};
