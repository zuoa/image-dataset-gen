import { Checkbox, Button } from "antd";

import { Check, Trash2 } from "lucide-react";
import { AuthImage } from "../../AuthImage";
import type { DatasetImage } from "../../../lib/types";

interface ImageCardProps {
  image: DatasetImage;
  isQueuedForDelete: boolean;
  isDeleting: boolean;
  split: string;
  annotationLabel: string;
  annotationClassName?: string;
  sourceLabel: string;
  onOpenPreview: () => void;
  onToggleDeleteSelection: () => void;
  onToggleSelection: () => void;
  onDelete: () => void;
}

export function ImageCard({
  image,
  isQueuedForDelete,
  isDeleting,
  split,
  annotationLabel,
  annotationClassName,
  sourceLabel,
  onOpenPreview,
  onToggleDeleteSelection,
  onToggleSelection,
  onDelete,
}: ImageCardProps) {
  return (
    <article
      className={`group overflow-hidden rounded-xl border text-left shadow-sm transition-[border-color,box-shadow,opacity] duration-200 hover:shadow-md ${
        isQueuedForDelete
          ? "border-red-400 bg-red-50 ring-2 ring-red-100 dark:border-red-400/60 dark:bg-red-500/10 dark:ring-red-500/10"
          : "border-transparent bg-[var(--df-color-bg-container)]"
      } ${isDeleting ? "opacity-50" : ""}`}
    >
      <div className="relative aspect-[4/3] overflow-hidden">
        <button
          type="button"
          aria-label={`查看样本 #${image.ordinal} 详情`}
          className="absolute inset-0 text-left"
          onClick={onOpenPreview}
          disabled={isDeleting}
        >
          <AuthImage
            src={image.previewSvg}
            alt={image.promptText}
            className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(2,6,23,0.04)_25%,rgba(2,6,23,0.82)_100%)]" />
          <div className="absolute bottom-3 left-3 right-3 text-white">
            <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em]">
              <span>{sourceLabel}</span>
              <span>{split}</span>
              <span>#{image.ordinal}</span>
              <span className={annotationClassName}>{annotationLabel}</span>
            </div>
            <div className="mt-2 line-clamp-2 text-sm">{image.promptText}</div>
          </div>
        </button>

        <label
          className={`absolute left-3 top-3 z-10 flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg border shadow-sm transition-colors ${
            isQueuedForDelete
              ? "border-red-300 bg-red-600 text-white"
              : "border-white/60 bg-slate-950/55 text-white backdrop-blur-sm hover:bg-slate-950/75"
          }`}
        >
          <Checkbox
            checked={isQueuedForDelete}
            onChange={onToggleDeleteSelection}
            disabled={isDeleting}
            aria-label={`勾选删除样本 #${image.ordinal}`}
            className="text-white"
          />
        </label>

        <Button
          type={image.selected ? "primary" : "default"}
          size="small"
          icon={image.selected ? <Check className="h-3.5 w-3.5" /> : undefined}
          className={`absolute right-3 top-3 z-10 !h-10 !rounded-lg !border-white/60 !px-3 !text-xs !shadow-sm !backdrop-blur-sm ${
            image.selected
              ? "!border-[var(--df-color-primary)]"
              : "!bg-slate-950/60 !text-white hover:!bg-slate-950/80"
          }`}
          onClick={onToggleSelection}
          disabled={isDeleting}
        >
          {image.selected ? "已保留" : "不保留"}
        </Button>

        <button
          type="button"
          onClick={onDelete}
          disabled={isDeleting}
          aria-label={`删除样本 #${image.ordinal}`}
          className="absolute right-3 top-[3.75rem] z-10 flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg border border-white/20 bg-slate-950/60 text-white shadow-sm backdrop-blur-sm transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </article>
  );
}
