import type { InputHTMLAttributes } from "react";

import { cn } from "../../lib/utils";
import { fieldBaseClasses } from "./fieldStyles";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        fieldBaseClasses,
        className,
      )}
      {...props}
    />
  );
}
