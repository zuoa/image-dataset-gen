import { PencilRuler, Trash2 } from "lucide-react";
import { Button, Input, Select, Slider, Typography } from "antd";

import { StatusBadge } from "../common/StatusBadge";
import type { Detection } from "../../lib/annotation";
import type { DatasetImage } from "../../lib/types";
import { cn } from "../../lib/utils";

interface AnnotationInspectorPanelProps {
  activeCategory: string;
  activeImage: DatasetImage | null;
  categories: string[];
  categoryColor: (category: string) => string;
  detections: Detection[];
  onAddDetection: () => void;
  onCategoryChange: (category: string) => void;
  onDetectionCategoryChange: (index: number, category: string) => void;
  onDetectionConfidenceChange: (index: number, confidence: number) => void;
  onRemoveDetection: (index: number) => void;
  onSelectDetection: (index: number) => void;
  selectedDetectionIndex: number | null;
  statusLabel: string;
}

export function AnnotationInspectorPanel({
  activeCategory,
  activeImage,
  categories,
  categoryColor,
  detections,
  onAddDetection,
  onCategoryChange,
  onDetectionCategoryChange,
  onDetectionConfidenceChange,
  onRemoveDetection,
  onSelectDetection,
  selectedDetectionIndex,
  statusLabel,
}: AnnotationInspectorPanelProps) {
  const availableCategories = categories.length > 0 ? categories : ["object"];

  return (
    <aside className="flex h-full min-h-0 flex-col bg-white dark:bg-[#11151b]" aria-label="标注检查器">
      <div className="shrink-0 border-b border-[#d7dce3] px-4 py-3 dark:border-white/10">
        <Typography.Text className="block text-xs font-medium text-neutral-500 dark:text-neutral-400">
          当前类别
        </Typography.Text>
        <div className="mt-2 grid grid-cols-2 gap-2">
          {availableCategories.map((category, index) => {
            const active = category === activeCategory;
            return (
              <button
                key={category}
                type="button"
                aria-pressed={active}
                onClick={() => onCategoryChange(category)}
                className={cn(
                  "flex min-h-10 min-w-0 cursor-pointer appearance-none items-center gap-2 rounded-lg border bg-white px-2.5 text-left text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-transparent",
                  active
                    ? "border-blue-600 bg-blue-600 text-white"
                    : "border-neutral-200 hover:border-neutral-300 hover:bg-neutral-50 dark:border-white/10 dark:hover:bg-white/5",
                )}
              >
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: categoryColor(category) }} />
                <span className="truncate"><span className="font-mono text-xs opacity-70">{index + 1}</span> {category}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="shrink-0 border-b border-[#d7dce3] px-4 py-3 dark:border-white/10">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Typography.Text className="block text-xs font-medium text-neutral-500 dark:text-neutral-400">
              当前样本
            </Typography.Text>
            <Typography.Text className="mt-1 block truncate font-mono text-base font-semibold">
              {activeImage ? `#${activeImage.ordinal}` : "—"}
            </Typography.Text>
          </div>
          {activeImage ? <StatusBadge status={activeImage.annotationStatus}>{statusLabel}</StatusBadge> : null}
        </div>
        <Typography.Paragraph className="!mb-0 mt-2 line-clamp-3 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
          {activeImage?.promptText ?? "当前筛选没有图片。"}
        </Typography.Paragraph>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
        <div className="mb-3 flex items-center justify-between gap-3 px-1">
          <div>
            <Typography.Text className="block text-xs font-medium text-neutral-500 dark:text-neutral-400">
              检测对象
            </Typography.Text>
            <Typography.Text className="text-sm font-semibold">{detections.length} 个框</Typography.Text>
          </div>
          <Button
            icon={<PencilRuler aria-hidden="true" className="h-4 w-4" />}
            onClick={onAddDetection}
            disabled={!activeImage}
            aria-label="新增检测框"
          />
        </div>

        <div className="space-y-2">
          {detections.map((detection, index) => {
            const selected = selectedDetectionIndex === index;
            return (
              <section
                key={`${detection.category}-${index}`}
                className={cn(
                  "rounded-lg border bg-white p-3 transition-colors duration-150 dark:bg-black/10",
                  selected ? "border-blue-500 ring-1 ring-blue-500/20" : "border-neutral-200 dark:border-white/10",
                )}
                aria-label={`检测框 ${index + 1}`}
              >
                <div className="mb-3 flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onSelectDetection(index)}
                    className="flex min-w-0 cursor-pointer appearance-none items-center gap-2 rounded border-0 bg-transparent px-1 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: categoryColor(detection.category) }} />
                    <span className="truncate text-sm font-medium">对象 {index + 1}</span>
                  </button>
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<Trash2 aria-hidden="true" className="h-4 w-4" />}
                    onClick={() => onRemoveDetection(index)}
                    aria-label={`删除检测框 ${index + 1}`}
                  />
                </div>

                <div className="grid gap-3">
                  {categories.length > 0 ? (
                    <Select
                      aria-label={`检测框 ${index + 1} 的类别`}
                      value={detection.category}
                      options={categories.map((category) => ({ value: category, label: category }))}
                      onChange={(value) => onDetectionCategoryChange(index, value as string)}
                    />
                  ) : (
                    <Input
                      aria-label={`检测框 ${index + 1} 的类别`}
                      name={`detection-${index + 1}-category`}
                      autoComplete="off"
                      value={detection.category}
                      onChange={(event) => onDetectionCategoryChange(index, event.target.value)}
                    />
                  )}
                  <div>
                    <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
                      <span>置信度</span>
                      <span className="font-mono tabular-nums">{(detection.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <Slider
                      aria-label={`检测框 ${index + 1} 的置信度`}
                      min={0}
                      max={1}
                      step={0.01}
                      value={detection.confidence}
                      onChange={(value) => onDetectionConfidenceChange(index, value as number)}
                      tooltip={{ formatter: (value) => `${((value as number) * 100).toFixed(0)}%` }}
                    />
                  </div>
                </div>
              </section>
            );
          })}

          {detections.length === 0 ? (
            <div className="rounded-lg border border-dashed border-neutral-300 p-4 text-center text-sm leading-6 text-neutral-500 dark:border-white/15 dark:text-neutral-400">
              当前图片没有检测框。可以新增检测框，或标记为空并进入下一张。
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
