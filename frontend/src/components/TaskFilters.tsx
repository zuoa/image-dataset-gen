import { Search } from "lucide-react";

import { formatProviderLabel } from "../lib/utils";
import { Input } from "./ui/Input";

type TaskFiltersProps = {
  search: string;
  provider: string;
  status: string;
  onSearchChange: (value: string) => void;
  onProviderChange: (value: string) => void;
  onStatusChange: (value: string) => void;
};

export function TaskFilters({
  search,
  provider,
  status,
  onSearchChange,
  onProviderChange,
  onStatusChange,
}: TaskFiltersProps) {
  return (
    <div className="grid gap-3 rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/25 lg:grid-cols-[1.2fr_0.8fr_0.8fr]">
      <div className="relative">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400 dark:text-neutral-500" />
        <Input
          className="pl-11"
          placeholder="搜索任务名、主题或类别"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </div>

      <select
        className="w-full rounded-2xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-900 dark:border-white/10 dark:bg-white/[0.03] dark:text-white"
        value={provider}
        onChange={(event) => onProviderChange(event.target.value)}
      >
        <option value="all">全部 Provider</option>
        <option value="gemini">{formatProviderLabel("gemini")}</option>
        <option value="jimeng">{formatProviderLabel("jimeng")}</option>
        <option value="stability">{formatProviderLabel("stability")}</option>
        <option value="custom">{formatProviderLabel("custom")}</option>
      </select>

      <select
        className="w-full rounded-2xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-900 dark:border-white/10 dark:bg-white/[0.03] dark:text-white"
        value={status}
        onChange={(event) => onStatusChange(event.target.value)}
      >
        <option value="all">全部状态</option>
        <option value="running">Running</option>
        <option value="completed">Completed</option>
        <option value="paused">Paused</option>
        <option value="draft">Draft</option>
      </select>
    </div>
  );
}
