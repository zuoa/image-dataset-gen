import { Loader } from "lucide-react";
import { Empty, Pagination } from "antd";

import { ImageCard } from "./ImageCard";
import type { DatasetImage, SamplePoolSplit } from "../../../lib/types";

const samplePoolSplitOptions: Array<{ value: SamplePoolSplit; label: string }> =
  [
    { value: "train", label: "训练集" },
    { value: "val", label: "验证集" },
    { value: "test", label: "测试集" },
    { value: "unselected", label: "不保留" },
  ];

function samplePoolSourceLabel(sourceType: string) {
  if (sourceType === "generation") return "AI 生成";
  if (sourceType === "augmentation") return "数据增强";
  if (["import", "video", "roboflow"].includes(sourceType)) return "导入";
  return sourceType;
}

function samplePoolSplitLabel(split: SamplePoolSplit) {
  return samplePoolSplitOptions.find((option) => option.value === split)?.label ?? split;
}

function isImageAnnotated(image: DatasetImage) {
  return (
    image.annotationStatus === "annotated" || image.annotationStatus === "empty"
  );
}

function samplePoolAnnotationLabel(image: DatasetImage) {
  if (image.annotationStatus === "empty") return "空标注";
  return isImageAnnotated(image) ? "已标注" : "未标注";
}

interface SamplePoolGridProps {
  images: DatasetImage[];
  imagesTotal: number;
  currentPage: number;
  pageSize: number;
  isLoadingFirstPage: boolean;
  isFetching: boolean;
  deleteSelectionIds: string[];
  deletingImageIds: string[];
  onToggleDeleteSelection: (imageId: string) => void;
  onOpenPreview: (imageId: string) => void;
  onToggleSelection: (image: DatasetImage) => void;
  onDeleteImage: (image: DatasetImage) => void;
  onPageChange: (page: number, pageSize: number) => void;
}

export function SamplePoolGrid({
  images,
  imagesTotal,
  currentPage,
  pageSize,
  isLoadingFirstPage,
  isFetching,
  deleteSelectionIds,
  deletingImageIds,
  onToggleDeleteSelection,
  onOpenPreview,
  onToggleSelection,
  onDeleteImage,
  onPageChange,
}: SamplePoolGridProps) {
  const deleteSelectionIdSet = new Set(deleteSelectionIds);
  const deletingImageIdSet = new Set(deletingImageIds);
  const rangeStart = imagesTotal === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeEnd = Math.min(currentPage * pageSize, imagesTotal);

  if (images.length === 0 && !isLoadingFirstPage) {
    return (
      <Empty
        className="mt-8"
        description={
          <div className="text-neutral-500">当前筛选条件下没有样本。</div>
        }
      />
    );
  }

  if (images.length === 0 && isLoadingFirstPage) {
    return (
      <div className="mt-8 rounded-2xl border border-dashed border-neutral-200 px-5 py-8 text-center text-sm text-neutral-500 dark:border-white/10">
        正在加载样本...
      </div>
    );
  }

  return (
    <>
      <div
        className={`relative mt-6 ${isFetching ? "pointer-events-none" : ""}`}
        aria-busy={isFetching}
      >
        <div
          className={`grid gap-3 transition-opacity sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 ${
            isFetching ? "opacity-45" : "opacity-100"
          }`}
        >
          {images.map((image) => {
            const split = (image.split ??
              (image.selected ? "train" : "unselected")) as SamplePoolSplit;
            const annotated = isImageAnnotated(image);
            return (
              <ImageCard
                key={image.id}
                image={image}
                isQueuedForDelete={deleteSelectionIdSet.has(image.id)}
                isDeleting={deletingImageIdSet.has(image.id)}
                split={samplePoolSplitLabel(split)}
                annotationLabel={samplePoolAnnotationLabel(image)}
                annotationClassName={annotated ? "text-white" : "text-slate-300"}
                sourceLabel={samplePoolSourceLabel(image.sourceType)}
                onOpenPreview={() => onOpenPreview(image.id)}
                onToggleDeleteSelection={() => onToggleDeleteSelection(image.id)}
                onToggleSelection={() => onToggleSelection(image)}
                onDelete={() => onDeleteImage(image)}
              />
            );
          })}
        </div>

        {isFetching ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-3 py-1.5 text-sm text-slate-600 shadow-sm dark:border-white/10 dark:bg-slate-900/95 dark:text-slate-300">
              <Loader className="h-4 w-4 animate-spin" />
              正在更新样本
            </span>
          </div>
        ) : null}
      </div>

      <div className="mt-5 flex flex-col gap-3 border-t border-slate-200 pt-4 dark:border-white/10 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs tabular-nums text-slate-500 dark:text-slate-400">
          本页显示第 {rangeStart}–{rangeEnd} 张，共 {imagesTotal} 张
        </div>
        <div
          className="overflow-x-auto pb-1 sm:pb-0"
        >
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={imagesTotal}
            pageSizeOptions={[20, 50, 100]}
            showSizeChanger={imagesTotal > 20}
            showLessItems
            responsive
            disabled={isFetching}
            onChange={(nextPage, nextPageSize) =>
              onPageChange(
                nextPageSize === pageSize ? nextPage : 1,
                nextPageSize,
              )
            }
            aria-label="样本池分页"
          />
        </div>
      </div>
    </>
  );
}
