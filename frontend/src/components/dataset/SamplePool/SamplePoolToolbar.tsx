import {
  CheckSquare,
  FlipHorizontal2,
  ListChecks,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { Button, Space } from "antd";

import { confirm } from "../../../hooks/useConfirm";
import type { Dataset } from "../../../lib/types";

interface SamplePoolToolbarProps {
  dataset: Dataset;
  filteredImagesCount: number;
  deleteSelectionCount: number;
  unretainedUnannotatedImageCount: number;
  isDeletingImages: boolean;
  isAnyImporting: boolean;
  onRetainAll: () => void;
  onRetainInvert: () => void;
  onRetainNone: () => void;
  onRetainUnannotated: () => void;
  onSelectFilteredForDelete: () => void;
  onClearDeleteSelection: () => void;
  onRemoveDeleteSelection: () => void;
}

export function SamplePoolToolbar({
  dataset,
  filteredImagesCount,
  deleteSelectionCount,
  unretainedUnannotatedImageCount,
  isDeletingImages,
  isAnyImporting,
  onRetainAll,
  onRetainInvert,
  onRetainNone,
  onRetainUnannotated,
  onSelectFilteredForDelete,
  onClearDeleteSelection,
  onRemoveDeleteSelection,
}: SamplePoolToolbarProps) {
  const imageCount = dataset.imageCount;
  const retainedImageCount = dataset.selectedCount;
  const unretainedImageCount = Math.max(0, imageCount - retainedImageCount);

  async function handleRetainAll() {
    if (
      !(await confirm({
        title: "全部保留",
        content: `确认将全部 ${imageCount} 张样本标记为保留？当前有 ${unretainedImageCount} 张会从不保留变为保留。`,
      }))
    )
      return;
    onRetainAll();
  }

  async function handleRetainInvert() {
    if (
      !(await confirm({
        title: "反向保留",
        content: `确认反转全部 ${imageCount} 张样本的保留状态？当前 ${retainedImageCount} 张会变为不保留，${unretainedImageCount} 张会变为保留。`,
      }))
    )
      return;
    onRetainInvert();
  }

  async function handleRetainNone() {
    if (
      !(await confirm({
        title: "全部不保留",
        content: `确认将全部 ${imageCount} 张样本标记为不保留？当前 ${retainedImageCount} 张保留样本会被移出训练和导出。`,
      }))
    )
      return;
    onRetainNone();
  }

  async function handleRetainUnannotated() {
    if (unretainedUnannotatedImageCount === 0) return;
    if (
      !(await confirm({
        title: "保留未标注样本",
        content: `确认将 ${unretainedUnannotatedImageCount} 张未标注且当前不保留的样本标记为保留？`,
      }))
    )
      return;
    onRetainUnannotated();
  }

  async function handleRemoveDeleteSelection() {
    if (deleteSelectionCount === 0) return;
    if (
      !(await confirm({
        title: "删除勾选样本",
        content: `删除已勾选的 ${deleteSelectionCount} 张样本？图片文件和标注也会一起移除。`,
        okDanger: true,
      }))
    )
      return;
    onRemoveDeleteSelection();
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Space wrap className="items-center">
        <span className="text-xs text-neutral-500">保留状态</span>
        <Button
          icon={<CheckSquare className="h-4 w-4" />}
          onClick={handleRetainAll}
          disabled={imageCount === 0 || unretainedImageCount === 0}
        >
          全部保留
        </Button>
        <Button
          icon={<FlipHorizontal2 className="h-4 w-4" />}
          onClick={handleRetainInvert}
          disabled={imageCount === 0}
        >
          反向保留
        </Button>
        <Button
          icon={<Square className="h-4 w-4" />}
          onClick={handleRetainNone}
          disabled={imageCount === 0 || retainedImageCount === 0}
        >
          全部不保留
        </Button>
        <Button
          icon={<ListChecks className="h-4 w-4" />}
          onClick={handleRetainUnannotated}
          disabled={unretainedUnannotatedImageCount === 0}
        >
          保留未标注 {unretainedUnannotatedImageCount}
        </Button>
      </Space>

      <Space wrap className="items-center">
        <span className="text-xs text-red-600 dark:text-red-200">删除勾选</span>
        <Button
          icon={<CheckSquare className="h-4 w-4" />}
          onClick={onSelectFilteredForDelete}
          disabled={filteredImagesCount === 0 || isAnyImporting || isDeletingImages}
        >
          勾选当前
        </Button>
        <Button
          icon={<X className="h-4 w-4" />}
          onClick={onClearDeleteSelection}
          disabled={deleteSelectionCount === 0 || isDeletingImages}
        >
          清除勾选
        </Button>
        <Button
          danger
          icon={<Trash2 className="h-4 w-4" />}
          onClick={handleRemoveDeleteSelection}
          disabled={deleteSelectionCount === 0 || isDeletingImages}
        >
          {isDeletingImages ? "删除中..." : `删除勾选 ${deleteSelectionCount}`}
        </Button>
      </Space>
    </div>
  );
}
