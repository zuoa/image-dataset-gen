import { Tag, Typography } from "antd";

import { StatusBadge } from "../common/StatusBadge";
import type { Dataset } from "../../lib/types";

interface DatasetHeaderProps {
  dataset: Dataset;
}

export function DatasetHeader({ dataset }: DatasetHeaderProps) {
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={dataset.status} />
        {dataset.categories.map((category) => (
          <Tag key={category} bordered>
            {category}
          </Tag>
        ))}
      </div>
      <Typography.Title level={2} className="mt-4 !text-3xl !font-medium">
        {dataset.name}
      </Typography.Title>
      <Typography.Text className="block max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
        {dataset.description || "这个数据集还没有填写说明。"}
      </Typography.Text>
    </div>
  );
}
