import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Cpu, RefreshCw, Server, Wifi, WifiOff, Zap } from "lucide-react";

import { listTrainingWorkers } from "../api/training";
import { Button } from "../components/ui/Button";
import { SectionCard } from "../components/ui/SectionCard";
import type { TrainingWorker, TrainingWorkerList, TrainingWorkerSummary } from "../lib/types";
import { cn, formatDate } from "../lib/utils";
import { useAuthStore } from "../store/auth";

type WorkerFilter = "all" | "online" | "busy" | "offline";

const emptySummary: TrainingWorkerSummary = {
  total: 0,
  online: 0,
  idle: 0,
  busy: 0,
  offline: 0,
};

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function heartbeatLabel(worker: TrainingWorker) {
  if (!worker.lastHeartbeatAt || worker.heartbeatAgeSeconds == null) return "从未收到心跳";
  const seconds = Math.max(0, worker.heartbeatAgeSeconds);
  if (seconds < 5) return "刚刚收到";
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function workerState(worker: TrainingWorker) {
  if (!worker.isOnline) {
    return {
      label: "离线",
      dot: "bg-rose-400",
      badge: "border-rose-400/20 bg-rose-400/10 text-rose-700 dark:text-rose-300",
    };
  }
  if (worker.status === "busy") {
    return {
      label: "工作中",
      dot: "bg-amber-400",
      badge: "border-amber-400/25 bg-amber-400/10 text-amber-700 dark:text-amber-300",
    };
  }
  return {
    label: "空闲",
    dot: "bg-emerald-400",
    badge: "border-emerald-400/25 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300",
  };
}

function WorkerCard({ worker }: { worker: TrainingWorker }) {
  const state = workerState(worker);
  const frameworks = stringList(worker.capabilities.frameworks);
  const tasks = stringList(worker.capabilities.tasks);
  const runtime =
    typeof worker.capabilities.runtime === "string" ? worker.capabilities.runtime : "未上报";

  return (
    <article className="group rounded-[24px] border border-neutral-200 bg-neutral-50/70 p-5 transition hover:border-neutral-300 hover:bg-white dark:border-white/10 dark:bg-black/20 dark:hover:border-white/20 dark:hover:bg-black/30">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,0.8fr)_220px] lg:items-center">
        <div className="flex min-w-0 items-start gap-4">
          <div className="relative mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-neutral-200 bg-white dark:border-white/10 dark:bg-white/[0.04]">
            <Server className="h-5 w-5 text-neutral-700 dark:text-neutral-200" />
            <span className={cn("absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full border-[3px] border-white dark:border-[#111317]", state.dot)} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="truncate text-lg font-medium text-neutral-900 dark:text-white">{worker.name}</h3>
              <span className={cn("rounded-full border px-2.5 py-1 text-[11px] font-medium", state.badge)}>
                {state.label}
              </span>
            </div>
            <div className="mt-1 truncate font-mono text-xs text-neutral-500">{worker.id}</div>
            <div className="mt-4 flex flex-wrap gap-2">
              {[...frameworks, ...tasks].map((capability) => (
                <span
                  key={capability}
                  className="rounded-full border border-neutral-200 bg-white px-2.5 py-1 text-[11px] text-neutral-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-neutral-300"
                >
                  {capability}
                </span>
              ))}
              {frameworks.length + tasks.length === 0 ? (
                <span className="text-xs text-neutral-400">未声明训练能力</span>
              ) : null}
            </div>
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-5 gap-y-3 text-xs">
          <div>
            <dt className="text-neutral-400">运行环境</dt>
            <dd className="mt-1 font-mono text-neutral-800 dark:text-neutral-200">{runtime}</dd>
          </div>
          <div>
            <dt className="text-neutral-400">Trainer 版本</dt>
            <dd className="mt-1 font-mono text-neutral-800 dark:text-neutral-200">{worker.version || "未知"}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-neutral-400">当前训练任务</dt>
            <dd className="mt-1 truncate font-mono text-neutral-800 dark:text-neutral-200">
              {worker.currentJobId || (worker.isOnline ? "无" : "状态未知")}
            </dd>
          </div>
        </dl>

        <div className="border-t border-neutral-200 pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0 dark:border-white/10">
          <div className="flex items-center gap-2 text-xs text-neutral-500">
            {worker.isOnline ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
            最近心跳
          </div>
          <div className="mt-2 text-sm font-medium text-neutral-900 dark:text-white">
            {heartbeatLabel(worker)}
          </div>
          <div className="mt-1 text-xs text-neutral-400">{formatDate(worker.lastHeartbeatAt)}</div>
        </div>
      </div>
    </article>
  );
}

export function TrainerFleetPage() {
  const token = useAuthStore((state) => state.token);
  const requestRef = useRef<AbortController | null>(null);
  const [data, setData] = useState<TrainingWorkerList | null>(null);
  const [filter, setFilter] = useState<WorkerFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadWorkers = useCallback(
    async (quiet = false) => {
      if (!token) return;
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      if (!quiet) setIsRefreshing(true);
      setError(null);
      try {
        const response = await listTrainingWorkers(token, controller.signal);
        if (!controller.signal.aborted) setData(response);
      } catch (nextError) {
        if (!controller.signal.aborted) setError((nextError as Error).message);
      } finally {
        if (requestRef.current === controller) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    [token],
  );

  useEffect(() => {
    void loadWorkers();
    const timer = window.setInterval(() => void loadWorkers(true), 10_000);
    return () => {
      window.clearInterval(timer);
      requestRef.current?.abort();
    };
  }, [loadWorkers]);

  const workers = data?.workers ?? [];
  const summary = data?.summary ?? emptySummary;
  const filteredWorkers = useMemo(
    () =>
      workers.filter((worker) => {
        if (filter === "online") return worker.isOnline;
        if (filter === "busy") return worker.isOnline && worker.status === "busy";
        if (filter === "offline") return !worker.isOnline;
        return true;
      }),
    [filter, workers],
  );

  const filters: Array<{ id: WorkerFilter; label: string; count: number }> = [
    { id: "all", label: "全部", count: summary.total },
    { id: "online", label: "在线", count: summary.online },
    { id: "busy", label: "工作中", count: summary.busy },
    { id: "offline", label: "离线", count: summary.offline },
  ];

  return (
    <div className="space-y-6">
      <SectionCard className="overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-neutral-500">
              <Activity className="h-3.5 w-3.5" />
              Trainer Fleet
            </div>
            <h2 className="mt-3 text-3xl font-medium text-neutral-900 dark:text-white">训练节点</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              查看已连接到 Forge 的 trainer、当前工作状态和最近心跳。页面每 10 秒自动更新。
            </p>
          </div>
          <Button
            type="button"
            variant="secondary"
            disabled={isRefreshing}
            onClick={() => void loadWorkers()}
          >
            <RefreshCw className={cn("mr-2 h-4 w-4", isRefreshing && "animate-spin motion-reduce:animate-none")} />
            刷新状态
          </Button>
        </div>

        <div className="relative mt-7 overflow-hidden rounded-[24px] bg-[#13181f] px-5 py-5 text-white shadow-[0_28px_70px_-36px_rgba(13,148,136,0.75)] sm:px-6">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[size:22px_22px]" />
          <div className="relative grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)] lg:items-center">
            <div>
              <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-emerald-300/70">Live signal</div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-4xl">{summary.online}</span>
                <span className="text-sm text-white/45">/ {summary.total} 在线</span>
              </div>
              <div className="mt-2 text-xs text-white/45">
                {summary.busy} 个工作中 · {summary.idle} 个空闲
              </div>
            </div>

            <div className="space-y-2.5" aria-label="Trainer 心跳信号">
              {workers.slice(0, 8).map((worker) => {
                const state = workerState(worker);
                return (
                  <div key={worker.id} className="grid grid-cols-[minmax(90px,160px)_1fr_auto] items-center gap-3">
                    <div className="truncate font-mono text-[11px] text-white/60">{worker.name}</div>
                    <div className="relative h-px bg-white/10">
                      <span className={cn("absolute -top-1 left-0 h-2 w-2 rounded-full", state.dot)} />
                      {worker.isOnline ? (
                        <span className={cn("absolute -top-1 left-0 h-2 w-2 animate-ping rounded-full opacity-50 motion-reduce:animate-none", state.dot)} />
                      ) : null}
                    </div>
                    <div className="w-12 text-right font-mono text-[10px] uppercase text-white/40">{state.label}</div>
                  </div>
                );
              })}
              {workers.length === 0 ? (
                <div className="flex h-16 items-center justify-center rounded-2xl border border-dashed border-white/10 text-sm text-white/40">
                  等待第一个 trainer 注册
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Registry</div>
            <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">已注册节点</h3>
            <div className="mt-2 text-xs text-neutral-500">
              {data ? `离线判定：超过 ${data.offlineAfterSeconds} 秒未收到心跳` : "正在读取心跳状态"}
              {data?.observedAt ? ` · 更新于 ${formatDate(data.observedAt)}` : ""}
            </div>
          </div>
          <div className="flex flex-wrap rounded-full border border-neutral-200 bg-neutral-100 p-1 dark:border-white/10 dark:bg-black/20">
            {filters.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={filter === item.id}
                onClick={() => setFilter(item.id)}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-neutral-950",
                  filter === item.id
                    ? "bg-white text-neutral-900 shadow-sm dark:bg-neutral-100 dark:text-neutral-950"
                    : "text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white",
                )}
              >
                {item.label} <span className="ml-1 font-mono opacity-60">{item.count}</span>
              </button>
            ))}
          </div>
        </div>

        {error ? (
          <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200" role="alert">
            无法更新 trainer 状态：{error}
          </div>
        ) : null}

        <div className="mt-6 space-y-3" aria-live="polite">
          {filteredWorkers.map((worker) => (
            <WorkerCard key={worker.id} worker={worker} />
          ))}

          {!isLoading && filteredWorkers.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-neutral-200 px-6 py-12 text-center dark:border-white/10">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-neutral-200 bg-neutral-100 dark:border-white/10 dark:bg-white/[0.03]">
                {workers.length === 0 ? <Cpu className="h-6 w-6 text-neutral-500" /> : <Zap className="h-6 w-6 text-neutral-500" />}
              </div>
              <div className="mt-4 text-lg text-neutral-900 dark:text-white">
                {workers.length === 0 ? "还没有 trainer 注册" : "这个状态下没有 trainer"}
              </div>
              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                {workers.length === 0
                  ? "启动 trainer 并连接到当前 Forge API 后，节点会自动出现在这里。"
                  : "切换筛选条件查看其他已注册节点。"}
              </p>
            </div>
          ) : null}

          {isLoading ? (
            <div className="space-y-3" aria-label="正在加载 trainer">
              {[0, 1].map((item) => (
                <div key={item} className="h-32 animate-pulse rounded-[24px] bg-neutral-100 motion-reduce:animate-none dark:bg-white/[0.04]" />
              ))}
            </div>
          ) : null}
        </div>
      </SectionCard>
    </div>
  );
}
