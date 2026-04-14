import type { ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "secondary";
};

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition duration-200 disabled:cursor-not-allowed disabled:opacity-40",
        variant === "primary" &&
          "bg-neutral-900 text-white hover:bg-neutral-800 dark:bg-white dark:text-black dark:hover:bg-neutral-200",
        variant === "secondary" &&
          "border border-neutral-200 bg-neutral-100 text-neutral-900 hover:border-neutral-300 hover:bg-neutral-200 dark:border-white/20 dark:bg-white/5 dark:text-white dark:hover:border-white/30 dark:hover:bg-white/10",
        variant === "ghost" && "text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-300 dark:hover:bg-white/5 dark:hover:text-white",
        className,
      )}
      {...props}
    />
  );
}
