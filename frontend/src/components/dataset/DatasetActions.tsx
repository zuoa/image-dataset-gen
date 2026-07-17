import {
  ClipboardList,
  Cpu,
  Download,
  Layers,
  PencilRuler,
  Sparkles,
  Tag,
  Upload,
  Wand2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Space } from "antd";

import type { Dataset, TrainingJob } from "../../lib/types";

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
    uploading: "上传产物",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status] ?? status;
}

interface DatasetActionsProps {
  dataset: Dataset;
  latestTrainingJob?: TrainingJob | null;
  onAugment: () => void;
  onAnnotate: () => void;
  onExport: () => void;
  onImport: () => void;
  onTrain: () => void;
  onTasks: () => void;
  onTools: () => void;
  isAnyImporting?: boolean;
}

export function DatasetActions({
  dataset,
  latestTrainingJob,
  onAugment,
  onAnnotate,
  onExport,
  onImport,
  onTrain,
  onTasks,
  onTools,
  isAnyImporting,
}: DatasetActionsProps) {
  const annotationRunning = dataset.annotation?.status === "running";
  const trainingRunning = latestTrainingJob
    ? activeTrainingStatuses.has(latestTrainingJob.status)
    : false;

  return (
    <Space wrap className="mt-6">
      <Link to={`/datasets/${dataset.id}/generate`}>
        <Button type="primary" icon={<Sparkles className="h-4 w-4" />}>
          生成
        </Button>
      </Link>
      <Button
        icon={<Wand2 className="h-4 w-4" />}
        onClick={onAugment}
        disabled={dataset.selectedOriginalCount === 0}
      >
        增强
      </Button>
      <Button
        icon={<Tag className="h-4 w-4" />}
        onClick={onAnnotate}
        disabled={dataset.imageCount === 0 || annotationRunning}
      >
        自动标注
      </Button>
      <Link
        to={`/datasets/${dataset.id}/annotate`}
        className={dataset.imageCount === 0 ? "pointer-events-none" : undefined}
      >
        <Button disabled={dataset.imageCount === 0} icon={<PencilRuler className="h-4 w-4" />}>
          标注模式
        </Button>
      </Link>
      <Button
        icon={<Download className="h-4 w-4" />}
        onClick={onExport}
        disabled={dataset.selectedCount === 0}
      >
        导出
      </Button>
      <Button
        icon={<Upload className="h-4 w-4" />}
        onClick={onImport}
        disabled={isAnyImporting}
      >
        导入
      </Button>
      <Button icon={<Cpu className="h-4 w-4" />} onClick={onTrain}>
        训练
        {latestTrainingJob ? (
          <span className="ml-1.5 text-xs text-neutral-400">
            {trainingRunning ? "运行中" : trainingStatusLabel(latestTrainingJob.status)}
          </span>
        ) : null}
      </Button>
      <Button icon={<ClipboardList className="h-4 w-4" />} onClick={onTasks}>
        批次任务
        <span className="ml-1.5 text-xs text-neutral-400">{dataset.tasks.length}</span>
      </Button>
      <Button icon={<Layers className="h-4 w-4" />} onClick={onTools}>
        数据集功能
      </Button>
    </Space>
  );
}
