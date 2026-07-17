import { useMemo, useState } from "react";
import { Activity, Cpu, RefreshCw, Server, Wifi, WifiOff, Zap } from "lucide-react";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  List,
  Row,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";

import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { useWorkers } from "../hooks/useWorkers";
import type { TrainingWorker, TrainingWorkerSummary } from "../lib/types";
import { cn, formatDate } from "../lib/utils";

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
    return { label: "离线", color: "error" as const, dot: "bg-rose-400" };
  }
  if (worker.status === "busy") {
    return { label: "工作中", color: "warning" as const, dot: "bg-amber-400" };
  }
  return { label: "空闲", color: "success" as const, dot: "bg-emerald-400" };
}

function WorkerCard({ worker }: { worker: TrainingWorker }) {
  const state = workerState(worker);
  const frameworks = stringList(worker.capabilities.frameworks);
  const tasks = stringList(worker.capabilities.tasks);
  const runtime =
    typeof worker.capabilities.runtime === "string" ? worker.capabilities.runtime : "未上报";

  return (
    <Card className="transition hover:border-neutral-300 dark:hover:border-white/20">
      <Row gutter={[24, 24]} align="middle">
        <Col xs={24} lg={10}>
          <div className="flex items-start gap-4">
            <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-neutral-200 bg-white dark:border-white/10 dark:bg-white/[0.04]">
              <Server className="h-5 w-5" />
              <span
                className={cn(
                  "absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full border-[3px] border-white dark:border-[#111317]",
                  state.dot,
                )}
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Typography.Text className="truncate text-lg font-medium">{worker.name}</Typography.Text>
                <Tag color={state.color}>{state.label}</Tag>
              </div>
              <Typography.Text className="mt-1 block truncate font-mono text-xs text-neutral-500">
                {worker.id}
              </Typography.Text>
              <div className="mt-3 flex flex-wrap gap-2">
                {[...frameworks, ...tasks].map((capability) => (
                  <Tag key={capability} bordered>{capability}</Tag>
                ))}
                {frameworks.length + tasks.length === 0 ? (
                  <Typography.Text className="text-xs text-neutral-400">未声明训练能力</Typography.Text>
                ) : null}
              </div>
            </div>
          </div>
        </Col>

        <Col xs={24} lg={8}>
          <Row gutter={[16, 16]}>
            <Col span={12}>
              <Typography.Text className="block text-xs text-neutral-400">运行环境</Typography.Text>
              <Typography.Text className="mt-1 block font-mono text-sm">{runtime}</Typography.Text>
            </Col>
            <Col span={12}>
              <Typography.Text className="block text-xs text-neutral-400">Trainer 版本</Typography.Text>
              <Typography.Text className="mt-1 block font-mono text-sm">{worker.version || "未知"}</Typography.Text>
            </Col>
            <Col span={24}>
              <Typography.Text className="block text-xs text-neutral-400">当前训练任务</Typography.Text>
              <Typography.Text className="mt-1 block truncate font-mono text-sm">
                {worker.currentJobId || (worker.isOnline ? "无" : "状态未知")}
              </Typography.Text>
            </Col>
          </Row>
        </Col>

        <Col xs={24} lg={6}>
          <div className="border-t border-neutral-200 pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0 dark:border-white/10">
            <div className="flex items-center gap-2 text-xs text-neutral-500">
              {worker.isOnline ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
              最近心跳
            </div>
            <Typography.Text className="mt-2 block text-sm font-medium">
              {heartbeatLabel(worker)}
            </Typography.Text>
            <Typography.Text className="block text-xs text-neutral-400">
              {formatDate(worker.lastHeartbeatAt)}
            </Typography.Text>
          </div>
        </Col>
      </Row>
    </Card>
  );
}

export function TrainerFleetPage() {
  const { data, isLoading, error, refetch, isFetching } = useWorkers();
  const [filter, setFilter] = useState<WorkerFilter>("all");

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

  const filters = [
    { value: "all", label: "全部", count: summary.total },
    { value: "online", label: "在线", count: summary.online },
    { value: "busy", label: "工作中", count: summary.busy },
    { value: "offline", label: "离线", count: summary.offline },
  ];

  return (
    <PageContainer>
      <Card className="overflow-hidden shadow-panel">
        <PageHeader
          eyebrow={
            <span className="inline-flex items-center gap-2">
              <Activity className="h-3.5 w-3.5" /> Trainer Fleet
            </span>
          }
          title="训练节点"
          description="查看已连接到 Forge 的 trainer、当前工作状态和最近心跳。页面每 10 秒自动更新。"
          actions={
            <Button
              icon={<RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />}
              loading={isFetching}
              onClick={() => void refetch()}
            >
              刷新状态
            </Button>
          }
        />

        <div className="relative mt-4 overflow-hidden rounded-2xl bg-[#13181f] px-5 py-5 text-white shadow-[0_28px_70px_-36px_rgba(13,148,136,0.75)] sm:px-6">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[size:22px_22px]" />
          <Row gutter={[24, 24]} className="relative" align="middle">
            <Col xs={24} lg={6}>
              <Typography.Text className="block font-mono text-[11px] uppercase tracking-[0.22em] text-emerald-300/70">
                Live signal
              </Typography.Text>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-4xl">{summary.online}</span>
                <span className="text-sm text-white/45">/ {summary.total} 在线</span>
              </div>
              <Typography.Text className="block text-xs text-white/45">
                {summary.busy} 个工作中 · {summary.idle} 个空闲
              </Typography.Text>
            </Col>

            <Col xs={24} lg={18}>
              <div className="space-y-2.5" aria-label="Trainer 心跳信号">
                {workers.slice(0, 8).map((worker) => {
                  const state = workerState(worker);
                  return (
                    <div key={worker.id} className="grid grid-cols-[minmax(90px,160px)_1fr_auto] items-center gap-3">
                      <Typography.Text className="truncate font-mono text-[11px] text-white/60">
                        {worker.name}
                      </Typography.Text>
                      <div className="relative h-px bg-white/10">
                        <span className={cn("absolute -top-1 left-0 h-2 w-2 rounded-full", state.dot)} />
                        {worker.isOnline ? (
                          <span
                            className={cn(
                              "absolute -top-1 left-0 h-2 w-2 animate-ping rounded-full opacity-50 motion-reduce:animate-none",
                              state.dot,
                            )}
                          />
                        ) : null}
                      </div>
                      <Typography.Text className="w-12 text-right font-mono text-[10px] uppercase text-white/40">
                        {state.label}
                      </Typography.Text>
                    </div>
                  );
                })}
                {workers.length === 0 ? (
                  <div className="flex h-16 items-center justify-center rounded-2xl border border-dashed border-white/10 text-sm text-white/40">
                    等待第一个 trainer 注册
                  </div>
                ) : null}
              </div>
            </Col>
          </Row>
        </div>
      </Card>

      <Card className="mt-6 shadow-panel">
        <PageHeader
          eyebrow="Registry"
          title="已注册节点"
          description={
            data
              ? `离线判定：超过 ${data.offlineAfterSeconds} 秒未收到心跳${data?.observedAt ? ` · 更新于 ${formatDate(data.observedAt)}` : ""}`
              : "正在读取心跳状态"
          }
          actions={
            <Segmented
              value={filter}
              onChange={(value) => setFilter(value as WorkerFilter)}
              options={filters.map((item) => ({
                value: item.value,
                label: `${item.label} ${item.count}`,
              }))}
            />
          }
        />

        {error ? (
          <Alert
            className="mb-4"
            message={`无法更新 trainer 状态：${error.message}`}
            type="error"
            showIcon
          />
        ) : null}

        <List
          dataSource={isLoading ? [] : filteredWorkers}
          locale={{
            emptyText: (
              <Empty
                image={workers.length === 0 ? <Cpu className="mx-auto h-12 w-12 text-neutral-400" /> : <Zap className="mx-auto h-12 w-12 text-neutral-400" />}
                description={
                  <div className="text-center">
                    <Typography.Text className="block text-lg">
                      {workers.length === 0 ? "还没有 trainer 注册" : "这个状态下没有 trainer"}
                    </Typography.Text>
                    <Typography.Text className="mx-auto mt-2 block max-w-md text-sm text-neutral-500">
                      {workers.length === 0
                        ? "启动 trainer 并连接到当前 Forge API 后，节点会自动出现在这里。"
                        : "切换筛选条件查看其他已注册节点。"}
                    </Typography.Text>
                  </div>
                }
              />
            ),
          }}
          renderItem={(worker) => (
            <List.Item className="!px-0 !py-2">
              <WorkerCard worker={worker} />
            </List.Item>
          )}
        />

        {isLoading ? (
          <Space direction="vertical" className="w-full" size="middle">
            <Skeleton active paragraph={{ rows: 4 }} />
            <Skeleton active paragraph={{ rows: 4 }} />
          </Space>
        ) : null}
      </Card>
    </PageContainer>
  );
}
