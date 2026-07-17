import { useDeferredValue, useMemo, useState } from "react";
import { ArrowRight, FolderPlus, Layers3, ScanSearch } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Card, Col, Empty, Input, List, Row, Tag, Typography } from "antd";

import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { StatCard } from "../components/common/DataCard";
import { LoadingState } from "../components/common/LoadingState";
import { StatusBadge } from "../components/common/StatusBadge";
import { useDatasets } from "../hooks/useDatasets";
import { formatCurrency, formatDate } from "../lib/utils";

const { Title, Text, Paragraph } = Typography;

export function DatasetListPage() {
  const { data, isLoading } = useDatasets();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const summary = data?.summary;
  const datasets = data?.datasets ?? [];

  const filteredDatasets = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((dataset) => {
      const content = [dataset.name, dataset.description, ...dataset.categories].join(" ").toLowerCase();
      return content.includes(needle);
    });
  }, [datasets, deferredSearch]);

  const metrics = [
    { label: "数据集", value: summary?.totalDatasets ?? 0 },
    { label: "批次任务", value: summary?.totalTasks ?? 0 },
    { label: "样本总量", value: summary?.totalImages ?? 0 },
    { label: "累计成本", value: formatCurrency(summary?.costToDate ?? 0) },
  ];

  if (isLoading) {
    return (
      <PageContainer>
        <LoadingState rows={6} />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <Card className="overflow-hidden shadow-panel">
        <Row gutter={[32, 32]} align="middle">
          <Col xs={24} lg={14}>
            <div className="inline-flex items-center gap-2 rounded-full border border-neutral-200 bg-white px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-neutral-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-400">
              <Layers3 className="h-3.5 w-3.5" />
              Dataset Ops
            </div>
            <Title level={2} className="mt-6 !text-3xl !font-medium leading-tight md:!text-4xl">
              用数据集组织生成批次，而不是把任务当成最终容器。
            </Title>
            <Paragraph className="mt-4 max-w-2xl !text-base leading-7 text-neutral-500 dark:text-neutral-400">
              每个数据集统一承载目标类别、样本池、标注状态和导出结果。生成、导入、增强只是数据集内部的批次动作。
            </Paragraph>
            <Link to="/datasets/new" className="mt-6 inline-block">
              <Button type="primary" size="large" icon={<FolderPlus className="h-4 w-4" />}>
                新建数据集
              </Button>
            </Link>
          </Col>
          <Col xs={24} lg={10}>
            <Row gutter={[12, 12]}>
              {metrics.map((metric) => (
                <Col span={12} key={metric.label}>
                  <StatCard label={metric.label} value={metric.value} />
                </Col>
              ))}
            </Row>
          </Col>
        </Row>
      </Card>

      <div className="mt-6">
        <PageHeader
          eyebrow="Datasets"
          title="数据集管理"
          actions={
            <Input.Search
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="按名称、描述或类别过滤"
              allowClear
              className="w-full md:w-80"
            />
          }
        />

        <List
          grid={{ gutter: 16, xs: 1, sm: 1, md: 1, lg: 1, xl: 1, xxl: 1 }}
          dataSource={filteredDatasets}
          locale={{
            emptyText: (
              <Empty
                image={<ScanSearch className="mx-auto h-12 w-12 text-neutral-400" />}
                description={
                  <div className="text-center">
                    <Text className="block text-lg">还没有可用数据集</Text>
                    <Text className="block text-sm text-neutral-500">
                      先创建一个数据集，再在数据集内部添加生成、导入或增强批次。
                    </Text>
                  </div>
                }
              />
            ),
          }}
          renderItem={(dataset) => (
            <List.Item key={dataset.id}>
              <Link to={`/datasets/${dataset.id}`}>
                <Card
                  hoverable
                  className="group transition-colors"
                  styles={{ body: { padding: 0 } }}
                >
                  <div className="p-5">
                    <Row gutter={[16, 16]} align="middle">
                      <Col xs={24} lg={16}>
                        <div className="flex flex-wrap gap-2">
                          <StatusBadge status={dataset.status} />
                          {dataset.latestTask ? (
                            <Tag bordered>{dataset.latestTask.taskType}</Tag>
                          ) : null}
                        </div>
                        <Title level={4} className="mt-3 !mb-2 !text-xl">
                          {dataset.name}
                        </Title>
                        <Paragraph className="!mb-0 max-w-2xl !text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                          {dataset.description || "还没有补充描述，当前以类别和样本池为主组织数据集。"}
                        </Paragraph>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {dataset.categories.map((category) => (
                            <Tag key={category} bordered>{category}</Tag>
                          ))}
                        </div>
                      </Col>
                      <Col xs={24} lg={8}>
                        <Row gutter={[12, 12]}>
                          <Col span={12}>
                            <div className="rounded-xl border border-black/5 bg-white/80 p-3 dark:border-white/10 dark:bg-black/20">
                              <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">样本池</Text>
                              <Text className="mt-1 block text-xl font-medium">{dataset.imageCount}</Text>
                              <Text className="text-xs text-neutral-500">已选 {dataset.selectedCount}</Text>
                            </div>
                          </Col>
                          <Col span={12}>
                            <div className="rounded-xl border border-black/5 bg-white/80 p-3 dark:border-white/10 dark:bg-black/20">
                              <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">批次数</Text>
                              <Text className="mt-1 block text-xl font-medium">{dataset.taskCount}</Text>
                              <Text className="text-xs text-neutral-500">
                                {dataset.latestTask ? `最近 ${dataset.latestTask.taskName}` : "尚未创建任务"}
                              </Text>
                            </div>
                          </Col>
                          <Col span={12}>
                            <div className="rounded-xl border border-black/5 bg-white/80 p-3 dark:border-white/10 dark:bg-black/20">
                              <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">成本</Text>
                              <Text className="mt-1 block text-xl font-medium">{formatCurrency(dataset.spentCost)}</Text>
                              <Text className="text-xs text-neutral-500">聚合全批次成本</Text>
                            </div>
                          </Col>
                          <Col span={12}>
                            <div className="rounded-xl border border-black/5 bg-white/80 p-3 dark:border-white/10 dark:bg-black/20">
                              <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">更新时间</Text>
                              <Text className="mt-1 block text-base font-medium">{formatDate(dataset.updatedAt)}</Text>
                              <Text className="text-xs text-neutral-500">最近活动时间</Text>
                            </div>
                          </Col>
                        </Row>
                      </Col>
                    </Row>
                    <div className="mt-4 flex items-center justify-end text-neutral-400 transition group-hover:text-blue-600 dark:text-neutral-500 dark:group-hover:text-blue-400">
                      <Text className="mr-1 text-sm">查看详情</Text>
                      <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
                    </div>
                  </div>
                </Card>
              </Link>
            </List.Item>
          )}
        />
      </div>
    </PageContainer>
  );
}
