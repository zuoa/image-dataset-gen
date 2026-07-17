import {
  CheckSquare,
  ChevronDown,
  FlipHorizontal2,
  ListChecks,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { Button, Dropdown } from "antd";
import type { MenuProps } from "antd";

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

  function handleRemoveDeleteSelection() {
    if (deleteSelectionCount === 0) return;
    onRemoveDeleteSelection();
  }

  const retentionItems: MenuProps["items"] = [
    {
      key: "all",
      icon: <CheckSquare className="h-4 w-4" />,
      label: (
        <MenuLabel
          title="全部保留"
          description={`${unretainedImageCount} 张将变为保留`}
        />
      ),
      disabled: imageCount === 0 || unretainedImageCount === 0,
    },
    {
      key: "invert",
      icon: <FlipHorizontal2 className="h-4 w-4" />,
      label: <MenuLabel title="反向保留" description="交换全部样本的保留状态" />,
      disabled: imageCount === 0,
    },
    {
      key: "none",
      icon: <Square className="h-4 w-4" />,
      label: (
        <MenuLabel
          title="全部不保留"
          description={`${retainedImageCount} 张将移出训练与导出`}
        />
      ),
      disabled: imageCount === 0 || retainedImageCount === 0,
    },
    { type: "divider" },
    {
      key: "unannotated",
      icon: <ListChecks className="h-4 w-4" />,
      label: (
        <MenuLabel
          title="保留未标注样本"
          description={`${unretainedUnannotatedImageCount} 张可处理`}
        />
      ),
      disabled: unretainedUnannotatedImageCount === 0,
    },
  ];

  function handleRetentionAction({ key }: { key: string }) {
    if (key === "all") void handleRetainAll();
    else if (key === "invert") void handleRetainInvert();
    else if (key === "none") void handleRetainNone();
    else if (key === "unannotated") void handleRetainUnannotated();
  }

  return (
    <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-white/10 dark:bg-white/[0.025]">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <div className="min-w-36">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
            批量管理
          </div>
          <div className="mt-0.5 text-sm text-slate-700 dark:text-slate-200">
            已保留 {retainedImageCount} / {imageCount}
          </div>
        </div>
        <Dropdown
          menu={{ items: retentionItems, onClick: handleRetentionAction }}
          trigger={["click"]}
          placement="bottomLeft"
        >
          <Button icon={<ListChecks className="h-4 w-4" />}>
            设置保留状态
            <ChevronDown className="ml-1 h-3.5 w-3.5" />
          </Button>
        </Dropdown>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          icon={<CheckSquare className="h-4 w-4" />}
          onClick={onSelectFilteredForDelete}
          disabled={
            filteredImagesCount === 0 || isAnyImporting || isDeletingImages
          }
        >
          选择当前结果
        </Button>
        {deleteSelectionCount > 0 ? (
          <Button
            icon={<X className="h-4 w-4" />}
            onClick={onClearDeleteSelection}
            disabled={isDeletingImages}
          >
            取消选择
          </Button>
        ) : null}
        <Button
          danger
          icon={<Trash2 className="h-4 w-4" />}
          onClick={handleRemoveDeleteSelection}
          disabled={deleteSelectionCount === 0 || isDeletingImages}
          loading={isDeletingImages}
        >
          {isDeletingImages ? "删除中" : `删除所选 ${deleteSelectionCount}`}
        </Button>
      </div>
    </div>
  );
}

function MenuLabel({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="min-w-48 py-0.5">
      <div className="text-sm">{title}</div>
      <div className="mt-0.5 text-xs text-slate-400">{description}</div>
    </div>
  );
}
