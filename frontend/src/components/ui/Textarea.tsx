import type { TextareaHTMLAttributes } from "react";

import { cn } from "../../lib/utils";
import { fieldBaseClasses } from "./fieldStyles";

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        `${fieldBaseClasses} min-h-28 rounded-3xl`,
        className,
      )}
      {...props}
    />
  );
}
