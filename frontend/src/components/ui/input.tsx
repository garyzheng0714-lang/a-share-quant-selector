import { forwardRef, type InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  suffix?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  function Input({ label, suffix, className = "", ...props }, ref) {
    return (
      <div className="flex flex-col gap-1.5">
        {label && <label className="text-sm text-ink-secondary">{label}</label>}
        <div className="relative">
          <input
            ref={ref}
            className={`w-full h-10 px-3 bg-inset rounded-xl text-sm text-ink border border-border transition-all duration-150 focus:border-border-focus focus:ring-2 focus:ring-accent/10 placeholder:text-ink-muted ${suffix ? "pr-10" : ""} ${className}`}
            {...props}
          />
          {suffix && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-muted">{suffix}</span>
          )}
        </div>
      </div>
    );
  },
);
