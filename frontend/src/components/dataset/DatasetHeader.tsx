import { Database, Layers3 } from "lucide-react";
import { Tag, Typography } from "antd";

import { StatusBadge } from "../common/StatusBadge";
import type { Dataset } from "../../lib/types";

interface DatasetHeaderProps {
  dataset: Dataset;
}

export function DatasetHeader({ dataset }: DatasetHeaderProps) {
  return (
    <div className="relative">
      <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-2 uppercase tracking-[0.18em]">
          <Database className="h-4 w-4 text-[var(--df-color-primary)]" />
          Dataset workspace
        </span>
        <span className="text-slate-300 dark:text-slate-700">/</span>
        <StatusBadge status={dataset.status} />
      </div>
      <Typography.Title
        level={1}
        className="mt-4 !mb-0 !text-3xl !font-semibold !tracking-[-0.025em] md:!text-4xl"
      >
        {dataset.name}
      </Typography.Title>
      <Typography.Text className="mt-3 block max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300 md:text-base">
        {dataset.description || "这个数据集还没有填写说明，可以先从生成或导入样本开始。"}
      </Typography.Text>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="mr-1 inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <Layers3 className="h-3.5 w-3.5" />
          {dataset.categories.length} 个类别
        </span>
        {dataset.categories.map((category) => (
          <Tag
            key={category}
            bordered={false}
            className="!m-0 !rounded-full !bg-slate-100 !px-2.5 !py-0.5 !text-slate-600 dark:!bg-white/[0.07] dark:!text-slate-300"
          >
            {category}
          </Tag>
        ))}
      </div>
    </div>
  );
}
