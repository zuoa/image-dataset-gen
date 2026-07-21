import { Loader, Upload } from "lucide-react";
import { Button, Card } from "antd";

interface ImageImportFormProps {
  imageInputRef: React.RefObject<HTMLInputElement>;
  onImageSelect: (files: File[]) => void;
  isImportingImages: boolean;
  isAnyImporting: boolean;
  pendingImageFiles: { name: string; size: number }[];
}

function formatSize(size: number) {
  return (size / 1024 / 1024).toLocaleString("zh-CN", {
    maximumFractionDigits: 1,
  });
}

export function ImageImportForm({
  imageInputRef,
  onImageSelect,
  isImportingImages,
  isAnyImporting,
  pendingImageFiles,
}: ImageImportFormProps) {
  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const fileList = event.target.files;
    if (!fileList || fileList.length === 0) return;
    onImageSelect(Array.from(fileList));
    event.target.value = "";
  }

  const totalSize = pendingImageFiles.reduce((sum, file) => sum + file.size, 0);

  return (
    <Card className="bg-neutral-50 dark:bg-white/[0.03]">
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={handleFileChange}
      />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Upload className="h-4 w-4 text-neutral-500" />
            图片上传
          </div>
          <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            支持 PNG、JPG、WEBP、GIF、BMP、TIFF，可一次选择多张图片直接入库。
          </p>
        </div>
        <Button
          onClick={() => imageInputRef.current?.click()}
          disabled={isAnyImporting}
          loading={isImportingImages}
          icon={isImportingImages ? undefined : <Upload className="h-4 w-4" />}
        >
          {isImportingImages ? "正在上传…" : "选择图片"}
        </Button>
      </div>

      {isImportingImages && pendingImageFiles.length > 0 ? (
        <div
          className="mt-4 flex items-center gap-3 rounded-lg border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-neutral-300"
          role="status"
          aria-live="polite"
        >
          <Loader className="h-4 w-4 shrink-0 animate-spin" />
          <span className="min-w-0 truncate">
            正在上传 {pendingImageFiles.length} 张图片
            {pendingImageFiles.length > 1 ? `（${formatSize(totalSize)} MB）` : ""}
            ：{pendingImageFiles.map((file) => file.name).join("、")}
          </span>
        </div>
      ) : null}
    </Card>
  );
}
