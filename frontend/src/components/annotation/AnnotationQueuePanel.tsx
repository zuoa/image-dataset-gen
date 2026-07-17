import { CheckCircle2, ListFilter, Loader2 } from "lucide-react";
import { Segmented, Typography } from "antd";
import type { MutableRefObject } from "react";

import { AuthImage } from "../AuthImage";
import type { DatasetImage } from "../../lib/types";
import { cn } from "../../lib/utils";
import type { AnnotationFilter } from "./types";

interface AnnotationQueuePanelProps {
  activeImageId: string | null;
  annotatedTotal: number;
  annotationFilter: AnnotationFilter;
  hasMoreImages: boolean;
  images: DatasetImage[];
  imagesTotal: number;
  isLoadingFirstPage: boolean;
  isLoadingMore: boolean;
  onFilterChange: (filter: AnnotationFilter) => void;
  onSelectImage: (imageId: string) => void;
  queueScrollRef: MutableRefObject<HTMLDivElement | null>;
  sentinelRef: MutableRefObject<HTMLDivElement | null>;
  totalImageCount: number;
  unannotatedTotal: number;
}

const filterOptions: Array<{ value: AnnotationFilter; label: string }> = [
  { value: "", label: "全部" },
  { value: "unannotated", label: "待处理" },
  { value: "annotated", label: "已完成" },
];

function annotationStatusLabel(status: string) {
  if (status === "annotated") return "已标注";
  if (status === "empty") return "空标注";
  return "待处理";
}

export function AnnotationQueuePanel({
  activeImageId,
  annotatedTotal,
  annotationFilter,
  hasMoreImages,
  images,
  imagesTotal,
  isLoadingFirstPage,
  isLoadingMore,
  onFilterChange,
  onSelectImage,
  queueScrollRef,
  sentinelRef,
  totalImageCount,
  unannotatedTotal,
}: AnnotationQueuePanelProps) {
  const queueLabel =
    annotationFilter === "unannotated"
      ? `${imagesTotal} 张待处理`
      : annotationFilter === "annotated"
        ? `${imagesTotal} 张已完成`
        : `${imagesTotal} 张样本`;

  const options = filterOptions.map((option) => {
    const count =
      option.value === "unannotated"
        ? unannotatedTotal
        : option.value === "annotated"
          ? annotatedTotal
          : totalImageCount;
    return {
      value: option.value,
      label: (
        <span className="flex items-center justify-center gap-1.5 whitespace-nowrap">
          <span>{option.label}</span>
          <span className="font-mono text-[10px] tabular-nums opacity-60">{count}</span>
        </span>
      ),
    };
  });

  return (
    <section className="flex h-full min-h-0 flex-col bg-white dark:bg-[#11151b]" aria-label="标注队列">
      <div className="shrink-0 border-b border-[#d7dce3] px-3 py-3 dark:border-white/10">
        <div className="flex items-center justify-between gap-3">
          <div>
            <Typography.Text className="block text-xs font-medium text-neutral-500 dark:text-neutral-400">
              标注队列
            </Typography.Text>
            <Typography.Text className="mt-0.5 block text-sm font-semibold">{queueLabel}</Typography.Text>
          </div>
          <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-neutral-400" />
        </div>
        <div className="mt-3 flex min-w-0 items-center gap-2">
          <ListFilter aria-hidden="true" className="h-4 w-4 shrink-0 text-neutral-400" />
          <Segmented
            aria-label="筛选标注队列"
            block
            className="min-w-0 flex-1"
            size="small"
            value={annotationFilter}
            onChange={(value) => onFilterChange(value as AnnotationFilter)}
            options={options}
          />
        </div>
      </div>

      <div ref={queueScrollRef} className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2 overscroll-contain">
        {images.map((image, index) => {
          const active = image.id === activeImageId;
          const processed = image.annotationStatus === "annotated" || image.annotationStatus === "empty";
          return (
            <button
              key={image.id}
              type="button"
              aria-current={active ? "true" : undefined}
              onClick={() => onSelectImage(image.id)}
              className={cn(
                "grid w-full cursor-pointer appearance-none grid-cols-[48px_minmax(0,1fr)] gap-2.5 rounded-lg border bg-transparent px-2 py-2 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 dark:focus-visible:ring-offset-[#11151b]",
                active
                  ? "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-400/10"
                  : "border-transparent hover:border-neutral-200 hover:bg-neutral-50 dark:hover:border-white/10 dark:hover:bg-white/[0.04]",
              )}
            >
              <span className="relative aspect-square overflow-hidden rounded-md bg-neutral-200 dark:bg-neutral-800">
                <AuthImage
                  src={image.previewSvg}
                  alt=""
                  width={48}
                  height={48}
                  loading={index > 8 ? "lazy" : undefined}
                  className="h-full w-full object-cover"
                />
                <span className="absolute left-1 top-1 rounded bg-black/75 px-1 py-0.5 font-mono text-[9px] text-white">
                  {index + 1}
                </span>
              </span>
              <span className="min-w-0 self-center">
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">#{image.ordinal}</span>
                  <span className="font-mono text-[10px] tabular-nums text-neutral-500">{image.detections.length}</span>
                </span>
                <span className="mt-0.5 flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                  <span
                    aria-hidden="true"
                    className={cn("h-1.5 w-1.5 rounded-full", processed ? "bg-emerald-500" : "bg-amber-500")}
                  />
                  {annotationStatusLabel(image.annotationStatus)}
                </span>
                <span className="mt-0.5 block truncate text-[10px] text-neutral-400">
                  {image.selected ? "已保留" : image.sourceType}
                </span>
              </span>
            </button>
          );
        })}

        {images.length === 0 && !isLoadingFirstPage ? (
          <div className="m-2 rounded-lg border border-dashed border-neutral-300 p-4 text-center text-sm text-neutral-500 dark:border-white/15 dark:text-neutral-400">
            当前筛选没有图片。
          </div>
        ) : hasMoreImages ? (
          <div ref={sentinelRef} className="flex items-center justify-center gap-2 py-3 text-xs text-neutral-500">
            {isLoadingMore ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : null}
            {isLoadingMore ? "正在加载…" : "继续滚动加载"}
          </div>
        ) : images.length > 0 ? (
          <div className="py-3 text-center font-mono text-[10px] text-neutral-400">已加载全部 {imagesTotal} 张</div>
        ) : null}
      </div>
    </section>
  );
}
