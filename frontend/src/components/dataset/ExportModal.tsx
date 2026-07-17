import { Download, X } from "lucide-react";
import { Button, Card, Modal, Space } from "antd";

import type { Dataset, DatasetExport } from "../../lib/types";
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
  latestExport?: DatasetExport | null;
  isCreatingExport: boolean;
  onCreate: () => void;
}

export function ExportModal({
  open,
  onClose,
  dataset,
  exportFormat,
  onExportFormatChange,
  latestExport,
  isCreatingExport,
  onCreate,
}: ExportModalProps) {
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
      width={600}
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
    </Modal>
  );
}
