import { ArrowUpDown } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "./ui/Badge";
import type { Task } from "../lib/types";
import { cn, formatCurrency, formatDate, formatProviderLabel } from "../lib/utils";

type SortKey = "updatedAt" | "spentCost" | "progressPercent" | "status";

type TaskTableProps = {
  tasks: Task[];
  sortKey: SortKey;
  sortDirection: "asc" | "desc";
  onSortChange: (key: SortKey) => void;
};

const headers: Array<{ key: SortKey; label: string }> = [
  { key: "updatedAt", label: "更新时间" },
  { key: "progressPercent", label: "进度" },
  { key: "spentCost", label: "成本" },
  { key: "status", label: "状态" },
];

export function TaskTable({
  tasks,
  sortKey,
  sortDirection,
  onSortChange,
}: TaskTableProps) {
  return (
    <div className="overflow-hidden rounded-[24px] border border-neutral-200 dark:border-white/10">
      <div className="hidden grid-cols-[1.8fr_0.9fr_0.9fr_0.8fr] gap-4 border-b border-neutral-200 bg-white px-5 py-4 text-xs uppercase tracking-[0.24em] text-neutral-500 dark:border-white/10 dark:bg-white/[0.03] lg:grid">
        {headers.map((header) => (
          <button
            key={header.key}
            className={cn(
              "inline-flex items-center gap-2 text-left transition hover:text-neutral-900 dark:hover:text-white",
              sortKey === header.key && "text-neutral-900 dark:text-white",
            )}
            onClick={() => onSortChange(header.key)}
            type="button"
          >
            {header.label}
            <ArrowUpDown className="h-3.5 w-3.5" />
            {sortKey === header.key ? (
              <span className="text-[10px] text-neutral-400">{sortDirection}</span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="divide-y divide-neutral-200 dark:divide-white/10">
        {tasks.map((task) => (
          <Link
            key={task.id}
            to={`/tasks/${task.id}`}
            className="grid gap-4 px-5 py-4 transition hover:bg-neutral-100 dark:hover:bg-white/[0.03] lg:grid-cols-[1.8fr_0.9fr_0.9fr_0.8fr] lg:items-center"
          >
            <div>
              <div className="text-base text-neutral-900 dark:text-white">{task.taskName}</div>
              <div className="mt-1 text-xs text-neutral-500">数据集数量 {task.imageCount} 张</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge>{formatProviderLabel(task.apiProvider)}</Badge>
                {task.categories.slice(0, 3).map((category) => (
                  <Badge key={category}>{category}</Badge>
                ))}
              </div>
            </div>
            <div className="text-sm text-neutral-600 dark:text-neutral-300">{task.progressPercent}%</div>
            <div className="text-sm text-neutral-600 dark:text-neutral-300">
              <div>{formatCurrency(task.spentCost)}</div>
              <div className="mt-1 text-xs text-neutral-500">{formatDate(task.updatedAt)}</div>
            </div>
            <div className="text-sm text-neutral-600 dark:text-neutral-300">{task.status}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
