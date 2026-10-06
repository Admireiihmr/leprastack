import type { ComponentType, ReactNode } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";
import { inputClass, errorClass } from "./styles";

export function AuthField({
  id,
  type,
  placeholder,
  ariaLabel,
  icon: Icon,
  error,
  disabled,
  autoComplete,
  registration,
  rightSlot,
}: {
  id: string;
  type: string;
  placeholder: string;
  ariaLabel: string;
  icon: ComponentType<{ className?: string }>;
  error?: string;
  disabled?: boolean;
  autoComplete?: string;
  registration: UseFormRegisterReturn;
  rightSlot?: ReactNode;
}) {
  return (
    <div>
      <div className="relative">
        <Icon className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 h-5 w-5 text-black/35" />
        <input
          id={id}
          type={type}
          autoComplete={autoComplete}
          placeholder={placeholder}
          aria-label={ariaLabel}
          className={inputClass}
          disabled={disabled}
          {...registration}
        />
        {rightSlot}
      </div>
      {error && <p className={errorClass}>{error}</p>}
    </div>
  );
}
