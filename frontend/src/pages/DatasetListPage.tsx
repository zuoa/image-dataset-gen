import { useDeferredValue, useMemo, useState } from "react";
import { ArrowRight, FolderPlus, Layers3, ScanSearch, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Card, Col, Empty, Input, List, Row, Tag, Typography } from "antd";
import { useQueryClient } from "@tanstack/react-query";

import { deleteDataset } from "../api/datasets";
import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { StatCard } from "../components/common/DataCard";
import { LoadingState } from "../components/common/LoadingState";
import { StatusBadge } from "../components/common/StatusBadge";
import { DeleteDatasetModal } from "../components/dataset/DeleteDatasetModal";
import { useDatasets } from "../hooks/useDatasets";
import type { DatasetListItem } from "../lib/types";
import { formatCurrency, formatDate } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const { Title, Text, Paragraph } = Typography;

export function DatasetListPage() {
  const token = useAuthStore((state) => state.token);
  const queryClient = useQueryClient();
  const { data, isLoading } = useDatasets();
  const [search, setSearch] = useState("");
  const [datasetToDelete, setDatasetToDelete] = useState<DatasetListItem | null>(null);
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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
    { label: "任务记录", value: summary?.totalTasks ?? 0 },
    { label: "图片总数", value: summary?.totalImages ?? 0 },
    { label: "累计成本", value: formatCurrency(summary?.costToDate ?? 0) },
  ];

  function openDeleteDataset(dataset: DatasetListItem) {
    setDeleteError(null);
    setDatasetToDelete(dataset);
  }

  async function removeDataset() {
    if (!token || !datasetToDelete) return;
    setDeletingDatasetId(datasetToDelete.id);
    setDeleteError(null);
    try {
      await deleteDataset(datasetToDelete.id, token);
      setDatasetToDelete(null);
      await queryClient.invalidateQueries({ queryKey: ["datasets", token] });
    } catch (error) {
      setDeleteError((error as Error).message);
    } finally {
      setDeletingDatasetId(null);
    }
  }

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
              数据集总览
            </div>
            <Title level={2} className="mt-6 !text-3xl !font-medium leading-tight md:!text-4xl">
              集中管理图片、标注和导出结果
            </Title>
            <Paragraph className="mt-4 max-w-2xl !text-base leading-7 text-neutral-500 dark:text-neutral-400">
              创建数据集后，可以继续生成或导入图片，并完成筛选、标注、训练和导出。
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
          eyebrow="全部数据集"
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
                    <Text className="block text-lg">
                      {search.trim() ? "没有找到匹配的数据集" : "还没有数据集"}
                    </Text>
                    <Text className="block text-sm text-neutral-500">
                      {search.trim()
                        ? "请尝试缩短关键词，或按其他名称、说明和类别搜索。"
                        : "创建第一个数据集，然后添加图片、标注并导出训练数据。"}
                    </Text>
                  </div>
                }
              />
            ),
          }}
          renderItem={(dataset) => (
            <List.Item key={dataset.id}>
              <Card
                hoverable
                className="group w-full transition-colors"
                styles={{ body: { padding: 0 } }}
              >
                <div className="p-5">
                    <Row gutter={[16, 16]} align="middle">
                      <Col xs={24} lg={16}>
                        <div className="flex flex-wrap gap-2">
                          <StatusBadge status={dataset.status} />
                          {dataset.latestTask ? (
                            <StatusBadge status={dataset.latestTask.taskType} />
                          ) : null}
                        </div>
                        <Link to={`/datasets/${dataset.id}`}>
                          <Title level={4} className="mt-3 !mb-2 !text-xl hover:!text-[var(--df-color-primary)]">
                            {dataset.name}
                          </Title>
                        </Link>
                        <Paragraph className="!mb-0 max-w-2xl !text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                          {dataset.description || "尚未填写说明。"}
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
                              <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">图片</Text>
                              <Text className="mt-1 block text-xl font-medium">{dataset.imageCount}</Text>
                              <Text className="text-xs text-neutral-500">已选 {dataset.selectedCount}</Text>
                            </div>
                          </Col>
                          <Col span={12}>
                            <div className="rounded-xl border border-black/5 bg-white/80 p-3 dark:border-white/10 dark:bg-black/20">
                              <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">任务数</Text>
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
                              <Text className="text-xs text-neutral-500">所有生成任务合计</Text>
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
                    <div className="mt-4 flex items-center justify-between gap-3">
                      <Button
                        type="text"
                        danger
                        icon={<Trash2 className="h-4 w-4" />}
                        onClick={() => openDeleteDataset(dataset)}
                      >
                        删除
                      </Button>
                      <Link
                        to={`/datasets/${dataset.id}`}
                        className="flex items-center text-neutral-400 transition group-hover:text-[var(--df-color-primary)] dark:text-neutral-500 dark:group-hover:text-[var(--df-color-primary-text-hover)]"
                      >
                        <Text className="mr-1 text-sm">查看详情</Text>
                        <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
                      </Link>
                    </div>
                </div>
              </Card>
            </List.Item>
          )}
        />
      </div>

      <DeleteDatasetModal
        open={datasetToDelete !== null}
        dataset={datasetToDelete}
        loading={deletingDatasetId === datasetToDelete?.id}
        error={deleteError}
        onClose={() => {
          if (!deletingDatasetId) setDatasetToDelete(null);
        }}
        onConfirm={removeDataset}
      />
    </PageContainer>
  );
}
