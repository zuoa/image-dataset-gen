import { formatCurrency } from "../../lib/utils";
import type { Dataset } from "../../lib/types";

interface DatasetMetricsProps {
  dataset: Dataset;
}

export function DatasetMetrics({ dataset }: DatasetMetricsProps) {
  const retainedPercent = dataset.imageCount
    ? Math.round((dataset.selectedCount / dataset.imageCount) * 100)
    : 0;
  const metrics = [
    { label: "全部样本", value: dataset.imageCount, hint: "当前样本池" },
    {
      label: "保留样本",
      value: dataset.selectedCount,
      hint: `${retainedPercent}% 可用于训练`,
    },
    { label: "批次任务", value: dataset.taskCount, hint: "累计运行" },
    { label: "累计成本", value: formatCurrency(dataset.spentCost), hint: "生成消耗" },
  ];

  return (
    <div className="grid grid-cols-2 border-t border-slate-200/80 bg-slate-50/70 dark:border-white/10 dark:bg-black/10 md:grid-cols-4">
      {metrics.map((metric, index) => (
        <div
          key={metric.label}
          className={`px-5 py-4 md:px-6 ${
            index % 2 === 0 ? "border-r border-slate-200/80 dark:border-white/10" : ""
          } ${index > 1 ? "border-t border-slate-200/80 dark:border-white/10 md:border-t-0" : ""} ${
            index === 1 ? "md:border-r" : ""
          } ${index === 2 ? "md:border-r" : ""}`}
        >
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {metric.label}
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
              {metric.value}
            </span>
            <span className="hidden text-xs text-slate-400 sm:inline dark:text-slate-500">
              {metric.hint}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
