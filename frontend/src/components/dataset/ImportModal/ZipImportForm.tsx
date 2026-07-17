import { useRef } from "react";
import { Loader, Upload } from "lucide-react";
import { Button, Card } from "antd";

interface ZipImportFormProps {
  archiveInputRef: React.RefObject<HTMLInputElement>;
  onArchiveSelect: (file: File) => void;
  isImportingZip: boolean;
  isAnyImporting: boolean;
  archiveImportFile: { name: string; size: number } | null;
}

export function ZipImportForm({
  archiveInputRef,
  onArchiveSelect,
  isImportingZip,
  isAnyImporting,
  archiveImportFile,
}: ZipImportFormProps) {
  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    onArchiveSelect(file);
    event.target.value = "";
  }

  return (
    <Card className="bg-neutral-50 dark:bg-white/[0.03]">
      <input
        ref={archiveInputRef}
        type="file"
        accept=".zip"
        className="hidden"
        onChange={handleFileChange}
      />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Upload className="h-4 w-4 text-neutral-500" />
            本地 ZIP
          </div>
          <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            自动识别 YOLO、COCO、Pascal VOC，也兼容只含图片的 ZIP。
          </p>
        </div>
        <Button
          onClick={() => archiveInputRef.current?.click()}
          disabled={isAnyImporting}
          loading={isImportingZip}
          icon={isImportingZip ? undefined : <Upload className="h-4 w-4" />}
        >
          {isImportingZip ? "导入中..." : "选择 ZIP"}
        </Button>
      </div>

      {isImportingZip && archiveImportFile ? (
        <div
          className="mt-4 flex items-center gap-3 rounded-lg border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-neutral-300"
          role="status"
          aria-live="polite"
        >
          <Loader className="h-4 w-4 shrink-0 animate-spin" />
          <span className="min-w-0 truncate">
            正在上传并解析 {archiveImportFile.name}（
            {(archiveImportFile.size / 1024 / 1024).toLocaleString("zh-CN", {
              maximumFractionDigits: 1,
            })}{" "}
            MB）
          </span>
        </div>
      ) : null}
    </Card>
  );
}
