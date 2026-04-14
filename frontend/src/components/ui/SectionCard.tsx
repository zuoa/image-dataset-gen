import type { PropsWithChildren } from "react";

import { cn } from "../../lib/utils";

export function SectionCard({
  children,
  className,
}: PropsWithChildren<{ className?: string }>) {
  return (
    <section
      className={cn(
        "rounded-[28px] border border-neutral-200 bg-white p-6 dark:border-white/10 dark:bg-neutral-900/88",
        className,
      )}
    >
      {children}
    </section>
  );
}
