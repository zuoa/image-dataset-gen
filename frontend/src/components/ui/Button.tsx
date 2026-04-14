import type { ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "secondary";
};

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-200 disabled:cursor-not-allowed disabled:opacity-40",
        variant === "primary" &&
          "border border-neutral-900 bg-neutral-900 text-white shadow-[0_10px_24px_rgba(23,23,23,0.12)] hover:bg-neutral-800 dark:border-white/10 dark:bg-neutral-100 dark:text-neutral-950 dark:shadow-[0_12px_28px_rgba(0,0,0,0.3)] dark:hover:bg-white",
        variant === "secondary" &&
          "border border-neutral-200 bg-neutral-100 text-neutral-900 hover:border-neutral-300 hover:bg-neutral-200 dark:border-white/12 dark:bg-neutral-900 dark:text-neutral-100 dark:hover:border-white/20 dark:hover:bg-neutral-800",
        variant === "ghost" && "text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-300 dark:hover:bg-white/[0.06] dark:hover:text-white",
        className,
      )}
      {...props}
    />
  );
}
