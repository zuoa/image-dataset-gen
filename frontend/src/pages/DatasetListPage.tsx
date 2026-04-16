import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { ArrowRight, FolderPlus, Layers3, ScanSearch } from "lucide-react";
import { Link } from "react-router-dom";

import { listDatasets } from "../api/datasets";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { SectionCard } from "../components/ui/SectionCard";
import type { Dataset, DatasetSummary } from "../lib/types";
import { formatCurrency, formatDate } from "../lib/utils";
import { useAuthStore } from "../store/auth";

function metricCards(summary: DatasetSummary | null) {
  if (!summary) return [];
  return [
    { label: "数据集", value: String(summary.totalDatasets) },
    { label: "批次任务", value: String(summary.totalTasks) },
    { label: "样本总量", value: String(summary.totalImages) },
    { label: "累计成本", value: formatCurrency(summary.costToDate) },
  ];
}

export function DatasetListPage() {
  const token = useAuthStore((state) => state.token);
  const [summary, setSummary] = useState<DatasetSummary | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  useEffect(() => {
    if (!token) return;
    void listDatasets(token)
      .then((response) => {
        setSummary(response.summary);
        setDatasets(response.datasets);
      })
      .catch(() => {
        setSummary(null);
        setDatasets([]);
      });
  }, [token]);

  const filteredDatasets = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((dataset) => {
      const content = [dataset.name, dataset.description, ...dataset.categories].join(" ").toLowerCase();
      return content.includes(needle);
    });
  }, [datasets, deferredSearch]);

  return (
    <div className="space-y-6">
      <SectionCard className="overflow-hidden">
        <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-neutral-200 bg-white px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-neutral-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-400">
              <Layers3 className="h-3.5 w-3.5" />
              Dataset Ops
            </div>
            <h2 className="mt-6 max-w-3xl text-4xl font-medium leading-tight text-neutral-900 dark:text-white">
              用数据集组织生成批次，而不是把任务当成最终容器。
            </h2>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              每个数据集统一承载目标类别、样本池、标注状态和导出结果。生成、导入、增强只是数据集内部的批次动作。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/datasets/new">
                <Button>
                  <FolderPlus className="mr-2 h-4 w-4" />
                  新建数据集
                </Button>
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {metricCards(summary).map((metric) => (
              <div
                key={metric.label}
                className="rounded-[24px] border border-neutral-200 bg-[linear-gradient(180deg,#fafaf9,white)] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)] dark:border-white/12 dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0.02))]"
              >
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">{metric.label}</div>
                <div className="mt-3 text-3xl text-neutral-900 dark:text-white">{metric.value}</div>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Datasets</div>
            <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">数据集管理</h3>
          </div>
          <div className="w-full max-w-sm">
            <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">搜索</div>
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按名称、描述或类别过滤" />
          </div>
        </div>

        <div className="mt-6 space-y-3">
          {filteredDatasets.map((dataset) => (
            <Link
              key={dataset.id}
              to={`/datasets/${dataset.id}`}
              className="group block rounded-[26px] border border-neutral-200 bg-[linear-gradient(135deg,rgba(246,245,240,0.9),white_45%,rgba(244,244,243,0.88))] p-5 transition hover:border-neutral-300 hover:shadow-[0_24px_60px_-32px_rgba(15,23,42,0.28)] dark:border-white/10 dark:bg-[linear-gradient(135deg,rgba(255,255,255,0.05),rgba(255,255,255,0.02))]"
            >
              <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap gap-2">
                    <Badge>{dataset.status}</Badge>
                    {dataset.latestTask ? <Badge>{dataset.latestTask.taskType}</Badge> : null}
                  </div>
                  <div className="mt-4 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="truncate text-2xl text-neutral-900 dark:text-white">{dataset.name}</div>
                      <p className="mt-2 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                        {dataset.description || "还没有补充描述，当前以类别和样本池为主组织数据集。"}
                      </p>
                    </div>
                    <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-neutral-400 transition group-hover:translate-x-1 dark:text-neutral-500" />
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {dataset.categories.map((category) => (
                      <Badge key={category}>{category}</Badge>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 lg:min-w-[340px]">
                  <div className="rounded-[20px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
                    <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">样本池</div>
                    <div className="mt-2 text-xl text-neutral-900 dark:text-white">{dataset.imageCount}</div>
                    <div className="mt-1 text-xs text-neutral-500">已选 {dataset.selectedCount}</div>
                  </div>
                  <div className="rounded-[20px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
                    <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">批次数</div>
                    <div className="mt-2 text-xl text-neutral-900 dark:text-white">{dataset.taskCount}</div>
                    <div className="mt-1 text-xs text-neutral-500">
                      {dataset.latestTask ? `最近 ${dataset.latestTask.taskName}` : "尚未创建任务"}
                    </div>
                  </div>
                  <div className="rounded-[20px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
                    <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">成本</div>
                    <div className="mt-2 text-xl text-neutral-900 dark:text-white">{formatCurrency(dataset.spentCost)}</div>
                    <div className="mt-1 text-xs text-neutral-500">聚合全批次成本</div>
                  </div>
                  <div className="rounded-[20px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
                    <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">更新时间</div>
                    <div className="mt-2 text-base text-neutral-900 dark:text-white">{formatDate(dataset.updatedAt)}</div>
                    <div className="mt-1 text-xs text-neutral-500">最近活动时间</div>
                  </div>
                </div>
              </div>
            </Link>
          ))}

          {filteredDatasets.length === 0 ? (
            <div className="rounded-[26px] border border-dashed border-neutral-200 px-6 py-12 text-center dark:border-white/10">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full border border-neutral-200 bg-neutral-100 dark:border-white/10 dark:bg-white/[0.03]">
                <ScanSearch className="h-6 w-6 text-neutral-500" />
              </div>
              <div className="mt-4 text-lg text-neutral-900 dark:text-white">还没有可用数据集</div>
              <div className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
                先创建一个数据集，再在数据集内部添加生成、导入或增强批次。
              </div>
            </div>
          ) : null}
        </div>
      </SectionCard>
    </div>
  );
}
