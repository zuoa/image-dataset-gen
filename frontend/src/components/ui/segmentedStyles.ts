import { cn } from "../../lib/utils";

export const segmentedGroupClasses =
  "inline-flex items-center gap-1 rounded-full border border-neutral-200 bg-neutral-100/95 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)] dark:border-white/12 dark:bg-neutral-900/85 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]";

export function segmentedButtonClasses(active: boolean, className?: string) {
  return cn(
    "inline-flex items-center justify-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-[background-color,color,box-shadow] duration-200",
    active
      ? "bg-neutral-900 text-white shadow-[0_8px_20px_rgba(17,24,39,0.12)] dark:bg-neutral-100 dark:text-neutral-950 dark:shadow-[0_10px_24px_rgba(0,0,0,0.28)]"
      : "text-neutral-500 hover:bg-white hover:text-neutral-900 dark:text-neutral-300 dark:hover:bg-white/[0.06] dark:hover:text-white",
    className,
  );
}
