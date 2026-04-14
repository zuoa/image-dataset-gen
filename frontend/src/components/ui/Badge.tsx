import type { PropsWithChildren } from "react";

import { cn } from "../../lib/utils";

export function Badge({
  children,
  className,
}: PropsWithChildren<{ className?: string }>) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border border-neutral-200 bg-neutral-100 px-3 py-1 text-xs uppercase tracking-[0.24em] text-neutral-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-neutral-300",
        className,
      )}
    >
      {children}
    </span>
  );
}
