import { Download, History, X } from "lucide-react";
import { Button, Card, Modal, Space } from "antd";

import { StatusBadge } from "../common/StatusBadge";
import type { Dataset, DatasetExport } from "../../lib/types";
import { formatDate } from "../../lib/utils";
import type { ExportFormat } from "./types";

const exportFormatOptions: Array<{ value: ExportFormat; label: string }> = [
  { value: "yolo", label: "YOLO" },
  { value: "coco", label: "COCO" },
  { value: "voc", label: "VOC" },
  { value: "csv", label: "CSV" },
];

interface ExportModalProps {
  open: boolean;
  onClose: () => void;
  dataset: Dataset;
  exportFormat: ExportFormat;
  onExportFormatChange: (format: ExportFormat) => void;
  isCreatingExport: boolean;
  downloadingExportId: string | null;
  onCreate: () => void;
  onDownload: (datasetExport: DatasetExport) => void | Promise<void>;
}

export function ExportModal({
  open,
  onClose,
  dataset,
  exportFormat,
  onExportFormatChange,
  isCreatingExport,
  downloadingExportId,
  onCreate,
  onDownload,
}: ExportModalProps) {
  const latestExport = dataset.exports[0];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closeIcon={<X className="h-5 w-5 text-neutral-500" />}
      title={
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            <Download className="h-4 w-4" />
            Export
          </div>
          <div className="mt-2 text-xl">导出</div>
        </div>
      }
      width={720}
    >
      <p className="mb-4 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
        选择导出格式后创建数据集压缩包，导出范围基于当前保留的样本。
      </p>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            导出格式
          </div>
          <Space wrap size="small">
            {exportFormatOptions.map((option) => (
              <Button
                key={option.value}
                type={exportFormat === option.value ? "primary" : "default"}
                onClick={() => onExportFormatChange(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </Space>
        </div>

        <Card className="bg-neutral-50 dark:bg-white/[0.03]">
          <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">导出范围</div>
          <div className="mt-2 text-lg">{dataset.selectedCount} 张保留样本</div>
          <div className="mt-1 text-sm text-neutral-500">
            最近导出：{latestExport ? `v${latestExport.version}` : "暂无"}
          </div>
        </Card>
      </div>

      <Space className="mt-6">
        <Button onClick={onClose} disabled={isCreatingExport}>取消</Button>
        <Button
          type="primary"
          icon={<Download className="h-4 w-4" />}
          onClick={() => void onCreate()}
          loading={isCreatingExport}
          disabled={isCreatingExport || dataset.selectedCount === 0}
        >
          导出
        </Button>
      </Space>

      <section className="mt-6 border-t border-neutral-200 pt-5 dark:border-white/10">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-neutral-500" />
            <div className="text-sm font-medium text-neutral-900 dark:text-white">导出历史</div>
          </div>
          <span className="text-xs tabular-nums text-neutral-500">{dataset.exports.length} 个版本</span>
        </div>

        {dataset.exports.length > 0 ? (
          <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
            {dataset.exports.map((datasetExport) => {
              const imageCount = summaryNumber(datasetExport.summary, "imageCount");
              const estimatedSizeMb = summaryNumber(datasetExport.summary, "estimatedSizeMb");
              const ready = datasetExport.status === "ready";
              return (
                <div
                  key={datasetExport.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-3 dark:border-white/10 dark:bg-white/[0.03]"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-medium text-neutral-900 dark:text-white">
                        v{datasetExport.version}
                      </span>
                      <span className="text-xs font-medium uppercase text-neutral-500">
                        {datasetExport.exportFormat}
                      </span>
                      <StatusBadge status={ready ? "completed" : datasetExport.status} className="m-0">
                        {exportStatusLabel(datasetExport.status)}
                      </StatusBadge>
                    </div>
                    <div className="mt-1 truncate font-mono text-[11px] text-neutral-500" title={datasetExport.filename}>
                      {datasetExport.filename || `dataset-export-v${datasetExport.version}.zip`}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-neutral-500">
                      <span>{formatDate(datasetExport.createdAt)}</span>
                      {imageCount !== null ? <span>{imageCount} 张样本</span> : null}
                      {estimatedSizeMb !== null ? <span>{estimatedSizeMb} MB</span> : null}
                    </div>
                  </div>
                  <Button
                    size="small"
                    icon={<Download className="h-3.5 w-3.5" />}
                    disabled={!ready || downloadingExportId !== null}
                    loading={downloadingExportId === datasetExport.id}
                    aria-label={`下载导出版本 v${datasetExport.version}`}
                    onClick={() => void onDownload(datasetExport)}
                  >
                    下载
                  </Button>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="mt-3 rounded-xl border border-dashed border-neutral-200 px-4 py-6 text-center text-sm text-neutral-500 dark:border-white/10">
            暂无导出记录
          </div>
        )}
      </section>
    </Modal>
  );
}

function summaryNumber(summary: Record<string, unknown>, key: string) {
  const value = summary[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function exportStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "等待生成",
    running: "生成中",
    ready: "可下载",
    failed: "生成失败",
  };
  return labels[status] ?? status;
}
