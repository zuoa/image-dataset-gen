import { Filter, RotateCcw } from "lucide-react";
import { Button, Segmented, Select } from "antd";

import type {
  Dataset,
  SamplePoolSource,
  SamplePoolSplit,
} from "../../../lib/types";

type SamplePoolAnnotationFilter = "" | "annotated" | "unannotated";
type SamplePoolSourceFilter = "" | SamplePoolSource;
type SamplePoolSplitFilter = "" | SamplePoolSplit;

const samplePoolSourceOptions: Array<{ value: SamplePoolSource; label: string }> =
  [
    { value: "generation", label: "AI 生成" },
    { value: "imported", label: "导入" },
    { value: "augmentation", label: "增强" },
  ];

const samplePoolSplitOptions: Array<{ value: SamplePoolSplit; label: string }> =
  [
    { value: "train", label: "训练集" },
    { value: "val", label: "验证集" },
    { value: "test", label: "测试集" },
    { value: "unselected", label: "不保留" },
  ];

const samplePoolAnnotationOptions: Array<{
  value: Exclude<SamplePoolAnnotationFilter, "">;
  label: string;
}> = [
  { value: "annotated", label: "已标注" },
  { value: "unannotated", label: "未标注" },
];

interface SamplePoolFiltersProps {
  dataset: Dataset;
  classFilter: string;
  splitFilter: SamplePoolSplitFilter;
  annotationFilter: SamplePoolAnnotationFilter;
  sourceFilter: SamplePoolSourceFilter;
  onClassFilterChange: (value: string) => void;
  onSplitFilterChange: (value: SamplePoolSplitFilter) => void;
  onAnnotationFilterChange: (value: SamplePoolAnnotationFilter) => void;
  onSourceFilterChange: (value: SamplePoolSourceFilter) => void;
}

function CountLabel({ label, count }: { label: string; count: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span>{label}</span>
      <span className="hidden text-[11px] tabular-nums opacity-60 2xl:inline">
        {count}
      </span>
    </span>
  );
}

export function SamplePoolFilters({
  dataset,
  classFilter,
  splitFilter,
  annotationFilter,
  sourceFilter,
  onClassFilterChange,
  onSplitFilterChange,
  onAnnotationFilterChange,
  onSourceFilterChange,
}: SamplePoolFiltersProps) {
  const samplePoolClassCounts = dataset.imageClassCounts ?? {};
  const samplePoolSplitCounts = dataset.imageSplitCounts ?? {
    train: 0,
    val: 0,
    test: 0,
    unselected: 0,
  };
  const samplePoolAnnotationCounts = dataset.imageAnnotationCounts ?? {
    annotated: 0,
    unannotated: 0,
  };
  const samplePoolSourceCounts = dataset.imageSourceCounts ?? {
    generation: 0,
    imported: 0,
    augmentation: 0,
  };
  const totalImages = dataset.imageCount;
  const activeFilterCount = [
    classFilter,
    splitFilter,
    annotationFilter,
    sourceFilter,
  ].filter(Boolean).length;

  function resetFilters() {
    onClassFilterChange("");
    onSplitFilterChange("");
    onAnnotationFilterChange("");
    onSourceFilterChange("");
  }

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/80 p-3 dark:border-white/10 dark:bg-white/[0.025] md:p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <Filter className="h-4 w-4 text-[var(--df-color-primary)]" />
          筛选样本
          {activeFilterCount > 0 ? (
            <span className="rounded-full bg-[var(--df-color-primary-bg)] px-2 py-0.5 text-xs tabular-nums text-[var(--df-color-primary-text)]">
              {activeFilterCount}
            </span>
          ) : null}
        </div>
        <Button
          type="text"
          size="small"
          icon={<RotateCcw className="h-3.5 w-3.5" />}
          onClick={resetFilters}
          disabled={activeFilterCount === 0}
        >
          重置
        </Button>
      </div>

      <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-[1.35fr_1fr_0.9fr_0.9fr]">
        <FilterField label="来源">
          <Segmented<SamplePoolSourceFilter>
            block
            value={sourceFilter}
            onChange={onSourceFilterChange}
            options={[
              {
                value: "",
                label: <CountLabel label="全部" count={totalImages} />,
              },
              ...samplePoolSourceOptions.map((option) => ({
                value: option.value,
                label: (
                  <CountLabel
                    label={option.label}
                    count={samplePoolSourceCounts[option.value] ?? 0}
                  />
                ),
              })),
            ]}
            aria-label="按样本来源筛选"
          />
        </FilterField>

        <FilterField label="标注状态">
          <Segmented<SamplePoolAnnotationFilter>
            block
            value={annotationFilter}
            onChange={onAnnotationFilterChange}
            options={[
              {
                value: "",
                label: <CountLabel label="全部" count={totalImages} />,
              },
              ...samplePoolAnnotationOptions.map((option) => ({
                value: option.value,
                label: (
                  <CountLabel
                    label={option.label}
                    count={samplePoolAnnotationCounts[option.value] ?? 0}
                  />
                ),
              })),
            ]}
            aria-label="按标注状态筛选"
          />
        </FilterField>

        <FilterField label="类别">
          <Select
            value={classFilter}
            onChange={onClassFilterChange}
            className="w-full"
            aria-label="按类别筛选"
            options={[
              { value: "", label: `全部类别 · ${totalImages}` },
              ...dataset.categories.map((category) => ({
                value: category,
                label: `${category} · ${samplePoolClassCounts[category] ?? 0}`,
              })),
            ]}
          />
        </FilterField>

        <FilterField label="数据划分">
          <Select
            value={splitFilter}
            onChange={onSplitFilterChange}
            className="w-full"
            aria-label="按数据划分筛选"
            options={[
              { value: "", label: `全部划分 · ${totalImages}` },
              ...samplePoolSplitOptions.map((option) => ({
                value: option.value,
                label: `${option.label} · ${samplePoolSplitCounts[option.value] ?? 0}`,
              })),
            ]}
          />
        </FilterField>
      </div>
    </div>
  );
}

function FilterField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="min-w-0">
      <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}
