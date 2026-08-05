import { TextInput } from "@astryxdesign/core/TextInput";
import { forwardRef, type InputHTMLAttributes } from "react";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "size" | "value" | "type"> {
  label?: string;
  suffix?: string;
  type?: "text" | "email" | "password";
  value?: string;
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
}

/** Compatibility adapter. The rendered field is Astryx TextInput. */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  function Input({ label, suffix: _suffix, value = "", onChange, disabled, type = "text", ...props }, ref) {
    void _suffix;
    const accessibleLabel = label || props["aria-label"] || "输入";
    return (
      <TextInput
        ref={ref}
        {...props}
        type={type}
        label={accessibleLabel}
        isLabelHidden={!label}
        value={value}
        onChange={(_nextValue, event) => onChange?.(event)}
        isDisabled={disabled}
      />
    );
  },
);
