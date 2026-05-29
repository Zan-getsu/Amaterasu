import React from 'react';
import { Tooltip } from './Tooltip';

interface SliderFieldProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string;
  icon?: React.ReactNode;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  formatValue?: (val: number) => string;
  tooltip?: string;
}

export const SliderField: React.FC<SliderFieldProps> = ({ 
  label, 
  icon, 
  value, 
  min, 
  max, 
  step = 1,
  onChange,
  formatValue = (v) => v.toString(),
  className = '', 
  tooltip,
  ...props 
}) => {
  const percentage = ((value - min) / (max - min)) * 100;
  
  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-slate-300 flex items-center gap-2">
          {icon && <span className="text-slate-400">{icon}</span>}
          {label}
          {tooltip && <Tooltip content={tooltip} />}
        </label>
        <span className="bg-white/10 px-2 py-0.5 rounded text-xs font-mono text-[#ff3e3e] font-semibold border border-[#ff3e3e]/20">
          {formatValue(value)}
        </span>
      </div>
      <div className="relative pt-1 pb-2">
        <div className="absolute top-1/2 left-0 w-full h-1.5 -translate-y-1/2 bg-white/10 rounded-full overflow-hidden pointer-events-none">
          <div 
            className="h-full bg-gradient-to-r from-[#ff3e3e] to-[#ff7a00]" 
            style={{ width: `${percentage}%` }}
          />
        </div>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={onChange}
          className="relative w-full h-1.5 opacity-0 cursor-pointer z-10"
          {...props}
        />
        {/* Custom thumb for visual only */}
        <div 
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-white border-2 border-[#ff3e3e] shadow-[0_0_10px_rgba(255,62,62,0.5)] pointer-events-none transition-transform"
          style={{ left: `calc(${percentage}% - 8px)` }}
        />
      </div>
    </div>
  );
};
