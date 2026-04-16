import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../../lib/utils";

export function SectionCard({
  children,
  className,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLElement>>) {
  return (
    <section
      className={cn(
        "rounded-[28px] border border-neutral-200 bg-white p-6 shadow-[0_20px_60px_rgba(15,23,42,0.05)] dark:border-white/12 dark:bg-[#111317]/92 dark:shadow-[0_24px_80px_rgba(0,0,0,0.42)]",
        className,
      )}
      {...props}
    >
      {children}
    </section>
  );
}
