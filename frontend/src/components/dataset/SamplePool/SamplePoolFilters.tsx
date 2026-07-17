import { Button, Space, Tag } from "antd";

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
    { value: "augmentation", label: "数据增强" },
  ];

const samplePoolSplitOptions: Array<{ value: SamplePoolSplit; label: string }> =
  [
    { value: "train", label: "训练集" },
    { value: "val", label: "验证集" },
    { value: "test", label: "测试集" },
    { value: "unselected", label: "不保留" },
  ];

const samplePoolAnnotationOptions: Array<{
  value: Exclude<SamplePoolAnnotationFilter, "" >;
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

  return (
    <div className="mt-5 space-y-4">
      <FilterGroup label="来源">
        <FilterButton
          active={sourceFilter === ""}
          onClick={() => onSourceFilterChange("")}
          label={`全部 ${totalImages}`}
        />
        {samplePoolSourceOptions.map((option) => (
          <FilterButton
            key={option.value}
            active={sourceFilter === option.value}
            onClick={() => onSourceFilterChange(option.value)}
            label={`${option.label} ${samplePoolSourceCounts[option.value] ?? 0}`}
          />
        ))}
      </FilterGroup>

      <FilterGroup label="Class">
        <FilterButton
          active={classFilter === ""}
          onClick={() => onClassFilterChange("")}
          label={`全部 ${totalImages}`}
        />
        {dataset.categories.map((category) => (
          <FilterButton
            key={category}
            active={classFilter === category}
            onClick={() => onClassFilterChange(category)}
            label={`${category} ${samplePoolClassCounts[category] ?? 0}`}
          />
        ))}
      </FilterGroup>

      <FilterGroup label="Split">
        <FilterButton
          active={splitFilter === ""}
          onClick={() => onSplitFilterChange("")}
          label={`全部 ${totalImages}`}
        />
        {samplePoolSplitOptions.map((option) => (
          <FilterButton
            key={option.value}
            active={splitFilter === option.value}
            onClick={() => onSplitFilterChange(option.value)}
            label={`${option.label} ${samplePoolSplitCounts[option.value] ?? 0}`}
          />
        ))}
      </FilterGroup>

      <FilterGroup label="Annotation">
        <FilterButton
          active={annotationFilter === ""}
          onClick={() => onAnnotationFilterChange("")}
          label={`全部 ${totalImages}`}
        />
        {samplePoolAnnotationOptions.map((option) => (
          <FilterButton
            key={option.value}
            active={annotationFilter === option.value}
            onClick={() => onAnnotationFilterChange(option.value)}
            label={`${option.label} ${samplePoolAnnotationCounts[option.value] ?? 0}`}
          />
        ))}
      </FilterGroup>
    </div>
  );
}

function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500 dark:text-neutral-400">
        {label}
      </div>
      <Space wrap size="small">{children}</Space>
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return active ? (
    <Tag color="default" className="cursor-pointer px-3 py-1 text-sm">
      {label}
    </Tag>
  ) : (
    <Button size="small" onClick={onClick}>{label}</Button>
  );
}
