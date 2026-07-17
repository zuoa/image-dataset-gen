import { Col, Row } from "antd";

import { StatCard } from "../common/DataCard";
import { formatCurrency } from "../../lib/utils";
import type { Dataset } from "../../lib/types";

interface DatasetMetricsProps {
  dataset: Dataset;
}

export function DatasetMetrics({ dataset }: DatasetMetricsProps) {
  const metrics = [
    { label: "样本池", value: dataset.imageCount },
    { label: "保留样本", value: dataset.selectedCount },
    { label: "任务批次", value: dataset.taskCount },
    { label: "累计成本", value: formatCurrency(dataset.spentCost) },
  ];

  return (
    <Row gutter={[12, 12]}>
      {metrics.map((metric) => (
        <Col span={12} key={metric.label}>
          <StatCard label={metric.label} value={metric.value} />
        </Col>
      ))}
    </Row>
  );
}
