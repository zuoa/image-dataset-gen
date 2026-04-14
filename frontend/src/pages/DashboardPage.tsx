import { useEffect, useMemo, useState } from "react";
import { ArrowRight, LayoutGrid, List, Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { listTasks, retryTask } from "../api/tasks";
import { TaskFilters } from "../components/TaskFilters";
import { TaskTable } from "../components/TaskTable";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { SectionCard } from "../components/ui/SectionCard";
import { segmentedButtonClasses, segmentedGroupClasses } from "../components/ui/segmentedStyles";
import type { DashboardSummary, Task } from "../lib/types";
import { formatCurrency, formatDate, formatProviderLabel } from "../lib/utils";
import { useAuthStore } from "../store/auth";

export function DashboardPage() {
  const token = useAuthStore((state) => state.token);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [sortKey, setSortKey] = useState<"updatedAt" | "spentCost" | "progressPercent" | "status">(
    "updatedAt",
  );
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    if (!token) return;
    void listTasks(token)
      .then((taskList) => {
        setSummary(taskList.summary);
        setTasks(taskList.tasks);
      })
      .catch(() => {
        setSummary(null);
        setTasks([]);
      });
  }, [token]);

  const metrics = summary
    ? [
        { label: "总任务", value: summary.totalTasks.toString() },
        { label: "进行中", value: summary.runningTasks.toString() },
        { label: "累计图片", value: summary.totalImages.toString() },
        { label: "累计成本", value: formatCurrency(summary.costToDate) },
      ]
    : [];

  const filteredTasks = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const base = tasks.filter((task) => {
      const matchesProvider = providerFilter === "all" || task.apiProvider === providerFilter;
      const matchesStatus = statusFilter === "all" || task.status === statusFilter;
      const matchesSearch =
        needle.length === 0 ||
        task.subject.toLowerCase().includes(needle) ||
        task.categories.some((category) => category.toLowerCase().includes(needle));
      return matchesProvider && matchesStatus && matchesSearch;
    });

    const sorted = [...base].sort((left, right) => {
      let leftValue: number | string = "";
      let rightValue: number | string = "";

      if (sortKey === "updatedAt") {
        leftValue = new Date(left.updatedAt ?? left.createdAt ?? 0).getTime();
        rightValue = new Date(right.updatedAt ?? right.createdAt ?? 0).getTime();
      } else if (sortKey === "spentCost") {
        leftValue = left.spentCost;
        rightValue = right.spentCost;
      } else if (sortKey === "progressPercent") {
        leftValue = left.progressPercent;
        rightValue = right.progressPercent;
      } else {
        leftValue = left.status;
        rightValue = right.status;
      }

      if (leftValue < rightValue) return sortDirection === "asc" ? -1 : 1;
      if (leftValue > rightValue) return sortDirection === "asc" ? 1 : -1;
      return 0;
    });

    return sorted;
  }, [providerFilter, search, sortDirection, sortKey, statusFilter, tasks]);

  function handleSortChange(
    nextKey: "updatedAt" | "spentCost" | "progressPercent" | "status",
  ) {
    if (sortKey === nextKey) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection("desc");
  }

  return (
    <div className="space-y-6">
      <SectionCard className="overflow-hidden">
        <div className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-neutral-400 dark:text-neutral-500">
              Synthetic Vision Ops Platform
            </div>
            <h2 className="mt-6 max-w-3xl text-4xl font-medium leading-tight text-neutral-900 dark:text-white">
              Dataset Forge
            </h2>
            <p className="mt-4 max-w-2xl text-xl leading-9 text-neutral-700 dark:text-neutral-200">
              用结构化工作流压缩图像数据集生产周期。
            </p>
            <p className="mt-6 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              当前实现覆盖任务配置、Prompt 生成、模拟图像产出、增强/标注/导出工作流，便于继续替换真实 API 与推理服务。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/tasks/new">
                <Button>
                  <Plus className="mr-2 h-4 w-4" />
                  新建数据集任务
                </Button>
              </Link>
              <Button variant="secondary">查看 API 适配层</Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {metrics.map((metric) => (
              <div
                key={metric.label}
                className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] dark:border-white/12 dark:bg-neutral-900 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
              >
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">{metric.label}</div>
                <div className="mt-3 text-3xl text-neutral-900 dark:text-white">{metric.value}</div>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Recent Tasks</div>
            <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">最近任务</h3>
          </div>
          <div className="flex items-center gap-3">
            <div className={segmentedGroupClasses}>
              <button
                className={segmentedButtonClasses(viewMode === "cards", "px-3 py-2")}
                onClick={() => setViewMode("cards")}
                type="button"
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                className={segmentedButtonClasses(viewMode === "table", "px-3 py-2")}
                onClick={() => setViewMode("table")}
                type="button"
              >
                <List className="h-4 w-4" />
              </button>
            </div>
            <Link to="/tasks/new" className="text-sm text-neutral-500 transition hover:text-neutral-900 dark:text-neutral-300 dark:hover:text-white">
              新建任务
            </Link>
          </div>
        </div>

        <TaskFilters
          search={search}
          provider={providerFilter}
          status={statusFilter}
          onSearchChange={setSearch}
          onProviderChange={setProviderFilter}
          onStatusChange={setStatusFilter}
        />

        <div className="mt-4 space-y-3">
          {viewMode === "cards"
            ? filteredTasks.map((task) => (
                <div
                  key={task.id}
                  className="flex flex-col gap-4 rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 transition hover:border-neutral-300 hover:bg-neutral-200 dark:border-white/12 dark:bg-neutral-900 dark:hover:border-white/20 dark:hover:bg-neutral-800 lg:flex-row lg:items-center lg:justify-between"
                >
                  <Link to={`/tasks/${task.id}`} className="min-w-0 flex-1">
                    <div className="text-lg text-neutral-900 dark:text-white">{task.subject}</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge>{formatProviderLabel(task.apiProvider)}</Badge>
                      {task.categories.map((category) => (
                        <Badge key={category}>{category}</Badge>
                      ))}
                    </div>
                  </Link>
                  <div className="flex items-center gap-6 text-sm text-neutral-500 dark:text-neutral-400 lg:gap-8">
                    <div>
                      <div>当前样本数</div>
                      <div className="mt-1 text-neutral-900 dark:text-white">{task.sampleCount} 张</div>
                    </div>
                    <div>
                      <div>状态</div>
                      <div className="mt-1 text-neutral-900 dark:text-white">{task.status}</div>
                    </div>
                    <div>
                      <div>进度</div>
                      <div className="mt-1 text-neutral-900 dark:text-white">{task.progressPercent}%</div>
                    </div>
                    <div>
                      <div>更新</div>
                      <div className="mt-1 text-neutral-900 dark:text-white">{formatDate(task.updatedAt)}</div>
                    </div>
                    {task.status !== "completed" && task.progressPercent < 100 ? (
                      <Button
                        variant="secondary"
                        onClick={() => {
                          if (!token) return;
                          void retryTask(task.id, token).then(() => {
                            void listTasks(token).then((taskList) => {
                              setSummary(taskList.summary);
                              setTasks(taskList.tasks);
                            });
                          });
                        }}
                      >
                        {task.status === "running" ? "重新开始" : "继续生成"}
                      </Button>
                    ) : (
                      <Link to={`/tasks/${task.id}`}>
                        <ArrowRight className="h-4 w-4 text-neutral-400 dark:text-neutral-500" />
                      </Link>
                    )}
                  </div>
                </div>
              ))
            : null}

          {viewMode === "table" && filteredTasks.length > 0 ? (
            <TaskTable
              tasks={filteredTasks}
              sortKey={sortKey}
              sortDirection={sortDirection}
              onSortChange={handleSortChange}
            />
          ) : null}

          {filteredTasks.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-neutral-200 p-8 text-center text-sm text-neutral-500 dark:border-white/12 dark:bg-neutral-900/60 dark:text-neutral-400">
              当前筛选条件下没有任务。
            </div>
          ) : null}
        </div>
      </SectionCard>
    </div>
  );
}
