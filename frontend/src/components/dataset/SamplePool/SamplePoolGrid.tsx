import { Loader } from "lucide-react";
import { Empty } from "antd";

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
  isLoadingFirstPage: boolean;
  isLoadingMore: boolean;
  hasMoreImages: boolean;
  deleteSelectionIds: string[];
  deletingImageIds: string[];
  onToggleDeleteSelection: (imageId: string) => void;
  onOpenPreview: (imageId: string) => void;
  onToggleSelection: (image: DatasetImage) => void;
  onDeleteImage: (image: DatasetImage) => void;
  sentinelRef: React.RefObject<HTMLDivElement>;
}

export function SamplePoolGrid({
  images,
  imagesTotal,
  isLoadingFirstPage,
  isLoadingMore,
  hasMoreImages,
  deleteSelectionIds,
  deletingImageIds,
  onToggleDeleteSelection,
  onOpenPreview,
  onToggleSelection,
  onDeleteImage,
  sentinelRef,
}: SamplePoolGridProps) {
  const deleteSelectionIdSet = new Set(deleteSelectionIds);
  const deletingImageIdSet = new Set(deletingImageIds);

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
    <div className="mt-6 grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
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
            annotationClassName={annotated ? "text-lime-200" : "text-amber-200"}
            sourceLabel={samplePoolSourceLabel(image.sourceType)}
            onOpenPreview={() => onOpenPreview(image.id)}
            onToggleDeleteSelection={() => onToggleDeleteSelection(image.id)}
            onToggleSelection={() => onToggleSelection(image)}
            onDelete={() => onDeleteImage(image)}
          />
        );
      })}

      {hasMoreImages ? (
        <div
          ref={sentinelRef}
          className="col-span-full flex items-center justify-center gap-2 py-4 text-sm text-neutral-500"
        >
          {isLoadingMore ? <Loader className="h-4 w-4 animate-spin" /> : null}
          {isLoadingMore ? "加载更多..." : "向下滚动加载更多"}
        </div>
      ) : images.length > 0 ? (
        <div className="col-span-full py-3 text-center text-xs text-neutral-400">
          已加载全部 {images.length} / {imagesTotal} 张
        </div>
      ) : null}
    </div>
  );
}
