import { useState } from "react";
import {
  ArrowUpRight,
  ChevronDown,
  ClipboardList,
  Cpu,
  Download,
  PencilRuler,
  Sparkles,
  Tag,
  Upload,
  Wand2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Divider, Dropdown, Modal } from "antd";
import type { MenuProps } from "antd";

import type { Dataset, TrainingJob } from "../../lib/types";

const activeTrainingStatuses = new Set([
  "queued",
  "assigned",
  "preparing",
  "running",
  "uploading",
]);

type WorkspaceEntry = "generate" | "annotate";

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

interface DatasetActionsProps {
  dataset: Dataset;
  latestTrainingJob?: TrainingJob | null;
  onAugment: () => void;
  onAnnotate: () => void;
  onExport: () => void;
  onImport: () => void;
  onTrain: () => void;
  onTasks: () => void;
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
  isAnyImporting,
}: DatasetActionsProps) {
  const [workspaceEntry, setWorkspaceEntry] = useState<WorkspaceEntry | null>(
    null,
  );
  const annotationRunning = dataset.annotation?.status === "running";
  const trainingRunning = latestTrainingJob
    ? activeTrainingStatuses.has(latestTrainingJob.status)
    : false;

  const processingItems: MenuProps["items"] = [
    {
      key: "augment",
      icon: <Wand2 className="h-4 w-4" />,
      label: "数据增强",
      disabled: dataset.selectedOriginalCount === 0,
    },
    {
      key: "auto-annotate",
      icon: <Tag className="h-4 w-4" />,
      label: annotationRunning ? "自动标注运行中" : "自动标注",
      disabled: dataset.imageCount === 0 || annotationRunning,
    },
    { type: "divider" },
    {
      key: "manual-annotate",
      icon: <PencilRuler className="h-4 w-4" />,
      label: "人工标注",
      disabled: dataset.imageCount === 0,
    },
  ];

  const outputItems: MenuProps["items"] = [
    {
      key: "train",
      icon: <Cpu className="h-4 w-4" />,
      label: latestTrainingJob
        ? `模型训练 · ${
            trainingRunning
              ? "运行中"
              : trainingStatusLabel(latestTrainingJob.status)
          }`
        : "模型训练",
    },
    {
      key: "export",
      icon: <Download className="h-4 w-4" />,
      label: "导出数据集",
      disabled: dataset.selectedCount === 0,
    },
  ];

  function handleProcessingAction({ key }: { key: string }) {
    if (key === "augment") onAugment();
    else if (key === "auto-annotate") onAnnotate();
    else if (key === "manual-annotate") setWorkspaceEntry("annotate");
  }

  function handleOutputAction({ key }: { key: string }) {
    if (key === "train") onTrain();
    else if (key === "export") onExport();
  }

  const workspaceIsGenerate = workspaceEntry === "generate";
  const workspacePath = workspaceIsGenerate
    ? `/datasets/${dataset.id}/generate`
    : `/datasets/${dataset.id}/annotate`;

  return (
    <>
      <div className="mt-6 flex flex-wrap items-center gap-2.5">
        <Button
          type="primary"
          size="large"
          icon={<Sparkles className="h-4 w-4" />}
          onClick={() => setWorkspaceEntry("generate")}
          className="!h-11 !px-5"
        >
          生成样本
        </Button>
        <Button
          size="large"
          icon={<Upload className="h-4 w-4" />}
          onClick={onImport}
          disabled={isAnyImporting}
          className="!h-11 !px-4"
        >
          {isAnyImporting ? "正在导入" : "导入样本"}
        </Button>
        <Dropdown
          menu={{ items: processingItems, onClick: handleProcessingAction }}
          trigger={["click"]}
          placement="bottomLeft"
        >
          <Button size="large" className="!h-11 !px-4">
            处理数据
            <ChevronDown className="ml-1 h-4 w-4" />
          </Button>
        </Dropdown>
        <Dropdown
          menu={{ items: outputItems, onClick: handleOutputAction }}
          trigger={["click"]}
          placement="bottomLeft"
        >
          <Button size="large" className="!h-11 !px-4">
            训练与导出
            <ChevronDown className="ml-1 h-4 w-4" />
          </Button>
        </Dropdown>

        <Divider type="vertical" className="mx-1 hidden !h-6 sm:block" />

        <Button
          type="text"
          size="large"
          icon={<ClipboardList className="h-4 w-4" />}
          onClick={onTasks}
          className="!h-11 !text-slate-600 dark:!text-slate-300"
        >
          任务记录
          <span className="ml-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-500 dark:bg-white/10 dark:text-slate-400">
            {dataset.tasks.length}
          </span>
        </Button>
      </div>

      <Modal
        open={workspaceEntry !== null}
        onCancel={() => setWorkspaceEntry(null)}
        title={workspaceIsGenerate ? "开始生成图片" : "开始人工标注"}
        width={520}
        footer={
          <div className="flex justify-end gap-2">
            <Button onClick={() => setWorkspaceEntry(null)}>取消</Button>
            <Link to={workspacePath}>
              <Button
                type="primary"
                icon={<ArrowUpRight className="h-4 w-4" />}
                onClick={() => setWorkspaceEntry(null)}
              >
                {workspaceIsGenerate ? "继续设置" : "开始标注"}
              </Button>
            </Link>
          </div>
        }
      >
        <div className="py-2">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-white/[0.03]">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--df-color-primary)] text-[var(--df-color-text-light-solid)]">
                {workspaceIsGenerate ? (
                  <Sparkles className="h-5 w-5" />
                ) : (
                  <PencilRuler className="h-5 w-5" />
                )}
              </div>
              <div>
                <div className="font-medium text-slate-900 dark:text-white">
                  {workspaceIsGenerate
                    ? "设置本次要生成的图片"
                    : `逐张检查并编辑 ${dataset.imageCount} 张样本`}
                </div>
                <p className="mb-0 mt-1.5 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {workspaceIsGenerate
                    ? "接下来可以选择图片数量、画面风格、场景和生成模型。"
                    : "接下来可以逐张检查检测框、修改类别并保存标注结果。"}
                </p>
              </div>
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}
