import { Download, Trash2 } from "lucide-react";
import { Button, Card, Progress, Space, Tag } from "antd";

import type { TrainingArtifact, TrainingJob } from "../../../lib/types";

const activeTrainingStatuses = new Set([
  "queued",
  "assigned",
  "preparing",
  "running",
  "uploading",
]);

function trainingStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    assigned: "已分配",
    preparing: "准备数据",
    running: "训练中",
    uploading: "保存结果",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status] ?? status;
}

function formatMetric(value: unknown) {
  if (typeof value !== "number") return "—";
  return value <= 1 ? value.toFixed(3) : String(value);
}

interface TrainingJobCardProps {
  job: TrainingJob | null;
  deletingJobId?: string | null;
  onRemove: (job: TrainingJob) => void;
  onDownloadArtifact: (artifact: TrainingArtifact) => void;
}

export function TrainingJobCard({
  job,
  deletingJobId,
  onRemove,
  onDownloadArtifact,
}: TrainingJobCardProps) {
  if (!job) {
    return (
      <Card className="bg-neutral-50 dark:bg-white/[0.03]">
        <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
          最新训练
        </div>
        <div className="mt-2 text-lg">暂无训练作业</div>
        <div className="mt-4 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
          设置训练参数并开始训练，系统会自动选择可用的训练设备。
        </div>
      </Card>
    );
  }

  const trainingRunning = activeTrainingStatuses.has(job.status);
  const metrics = job.metrics ?? {};

  return (
    <Card className="bg-neutral-50 dark:bg-white/[0.03]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
            最新训练
          </div>
          <div className="mt-2 text-lg">{trainingStatusLabel(job.status)}</div>
        </div>
        <Tag color={trainingRunning ? "processing" : "default"}>
          {job.progressPercent}%
        </Tag>
      </div>

      <Progress
        percent={job.progressPercent}
        showInfo={false}
        className="mt-4"
        strokeColor={trainingRunning ? undefined : "#737373"}
      />

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <Metric label="mAP50" value={metrics.mAP50} />
        <Metric label="mAP50-95" value={metrics.mAP50_95} />
        <Metric label="精确率" value={metrics.precision} />
        <Metric label="召回率" value={metrics.recall} />
      </div>

      {job.error ? (
        <div className="mt-4 text-sm text-red-600 dark:text-red-300">{job.error}</div>
      ) : null}

      {job.artifacts.length > 0 ? (
        <Space wrap className="mt-4">
          {job.artifacts.map((artifact) => (
            <Button
              key={artifact.id}
              icon={<Download className="h-4 w-4" />}
              onClick={() => onDownloadArtifact(artifact)}
            >
              <span className="truncate">{artifact.filename}</span>
            </Button>
          ))}
        </Space>
      ) : null}

      <div className="mt-4 flex justify-end border-t border-neutral-200 pt-4 dark:border-white/10">
        <Button
          danger
          icon={<Trash2 className="h-4 w-4" />}
          loading={deletingJobId === job.id}
          disabled={deletingJobId === job.id}
          onClick={() => onRemove(job)}
        >
          {deletingJobId === job.id ? "删除中…" : "删除任务"}
        </Button>
      </div>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-xl bg-white p-3 dark:bg-black/20">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-lg tabular-nums">{formatMetric(value)}</div>
    </div>
  );
}
