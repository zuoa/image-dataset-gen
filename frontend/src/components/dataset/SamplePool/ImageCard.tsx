import { Checkbox, Button } from "antd";

import { Trash2 } from "lucide-react";
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
      className={`group overflow-hidden rounded-2xl border text-left transition ${
        isQueuedForDelete
          ? "border-red-300 bg-red-50 dark:border-red-300/50 dark:bg-red-500/10"
          : image.selected
            ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.03]"
            : "border-neutral-200 bg-white opacity-80 dark:border-white/10 dark:bg-black/20"
      } ${isDeleting ? "opacity-50" : ""}`}
    >
      <div className="relative aspect-square overflow-hidden">
        <button
          type="button"
          className="absolute inset-0 text-left"
          onClick={onOpenPreview}
          disabled={isDeleting}
        >
          <AuthImage
            src={image.previewSvg}
            alt={image.promptText}
            className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_35%,rgba(10,10,10,0.72))]" />
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
          className={`absolute left-3 top-3 z-10 flex h-9 w-9 items-center justify-center rounded-full border transition ${
            isQueuedForDelete
              ? "border-red-300 bg-red-600 text-white"
              : "border-white/60 bg-black/45 text-white hover:bg-black/65"
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
          size="small"
          type={image.selected ? "default" : "primary"}
          className={`absolute right-3 top-3 z-10 rounded-full px-3 py-1 text-xs ${
            image.selected
              ? "bg-white text-neutral-900 hover:bg-neutral-100"
              : "bg-black/65 text-white hover:bg-black/80"
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
          className="absolute right-3 top-12 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-red-600 text-white shadow-lg transition hover:bg-red-500 disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </article>
  );
}
