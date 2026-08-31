import { useDeferredValue, useMemo, useState } from "react";
import {
  ArrowRight,
  Folder,
  FolderPlus,
  Layers3,
  MoreHorizontal,
  ScanSearch,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button, Card, Col, Dropdown, Empty, Input, List, Row, Segmented, Tag, Tree, Typography } from "antd";
import type { DataNode } from "antd/es/tree";
import type { MenuProps as DropdownMenuProps } from "antd";
import { useQueryClient } from "@tanstack/react-query";

import { deleteDataset, updateDataset } from "../api/datasets";
import {
  createDatasetCollection,
  deleteDatasetCollection,
  updateDatasetCollection,
} from "../api/collections";
import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { StatCard } from "../components/common/DataCard";
import { LoadingState } from "../components/common/LoadingState";
import { StatusBadge } from "../components/common/StatusBadge";
import { CollectionBreadcrumb } from "../components/dataset/CollectionBreadcrumb";
import { CollectionFormModal } from "../components/dataset/CollectionFormModal";
import { DeleteCollectionModal } from "../components/dataset/DeleteCollectionModal";
import { DeleteDatasetModal } from "../components/dataset/DeleteDatasetModal";
import {
  excludedIdsForCollectionMove,
  MoveToCollectionModal,
} from "../components/dataset/MoveToCollectionModal";
import { useDatasets } from "../hooks/useDatasets";
import { useIsMobile } from "../hooks/useMediaQuery";
import {
  childCollections,
  collectionBreadcrumb,
  datasetsInCollection,
} from "../lib/collections";
import type { DatasetCollection, DatasetListItem } from "../lib/types";
import { formatCurrency, formatDate } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const { Title, Text, Paragraph } = Typography;

function DatasetCard({
  dataset,
  onDelete,
  onMove,
}: {
  dataset: DatasetListItem;
  onDelete: (dataset: DatasetListItem) => void;
  onMove: (dataset: DatasetListItem) => void;
}) {
  return (
    <Card hoverable className="group w-full transition-colors" styles={{ body: { padding: 0 } }}>
      <div className="p-5">
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} lg={16}>
            <div className="flex flex-wrap gap-2">
              <StatusBadge status={dataset.status} />
              {dataset.latestTask ? <StatusBadge status={dataset.latestTask.taskType} /> : null}
            </div>
            <Link to={`/datasets/${dataset.id}`}>
              <Title level={4} className="mt-3 !mb-2 !text-xl hover:!text-[var(--df-color-primary)]">
                {dataset.name}
              </Title>
            </Link>
            <Paragraph className="!mb-0 max-w-2xl !text-sm leading-6 text-neutral-500 dark:text-neutral-400">
              {dataset.description || "尚未填写说明。"}
            </Paragraph>
            {dataset.collectionPath && dataset.collectionPath.length > 0 ? (
              <Text className="mt-2 block text-xs text-neutral-400">
                {dataset.collectionPath.map((item) => item.name).join(" / ")}
              </Text>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2">
              {dataset.categories.map((category) => (
                <Tag key={category} bordered>
                  {category}
                </Tag>
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
          <div className="flex items-center gap-1">
            <Button type="text" onClick={() => onMove(dataset)}>
              移动
            </Button>
            <Button type="text" danger icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(dataset)}>
              删除
            </Button>
          </div>
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
  );
}

function CollectionCard({
  collection,
  onOpen,
  menuItems,
}: {
  collection: DatasetCollection;
  onOpen: () => void;
  menuItems: DropdownMenuProps["items"];
}) {
  return (
    <Card hoverable className="group w-full transition-colors" styles={{ body: { padding: 0 } }}>
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <button type="button" className="flex min-w-0 flex-1 items-start gap-3 text-left" onClick={onOpen}>
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-neutral-900 text-white dark:bg-white dark:text-neutral-950">
              <Folder className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <Title level={4} className="!mb-1 !text-xl group-hover:!text-[var(--df-color-primary)]">
                {collection.name}
              </Title>
              <Paragraph className="!mb-0 !text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                {collection.description || "分组，用于组织子数据集。"}
              </Paragraph>
            </div>
          </button>
          <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
            <Button type="text" icon={<MoreHorizontal className="h-4 w-4" />} aria-label={`${collection.name} 操作`} />
          </Dropdown>
        </div>
        <Row gutter={[12, 12]} className="mt-4">
          <Col span={8}>
            <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">数据集</Text>
            <Text className="mt-1 block text-xl font-medium">{collection.stats.datasetCount}</Text>
          </Col>
          <Col span={8}>
            <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">图片</Text>
            <Text className="mt-1 block text-xl font-medium">{collection.stats.imageCount}</Text>
          </Col>
          <Col span={8}>
            <Text className="block text-[11px] uppercase tracking-[0.2em] text-neutral-500">成本</Text>
            <Text className="mt-1 block text-xl font-medium">{formatCurrency(collection.stats.spentCost)}</Text>
          </Col>
        </Row>
      </div>
    </Card>
  );
}

export function DatasetListPage() {
  const token = useAuthStore((state) => state.token);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { data, isLoading } = useDatasets();
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [datasetToDelete, setDatasetToDelete] = useState<DatasetListItem | null>(null);
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [collectionForm, setCollectionForm] = useState<{
    mode: "create" | "rename";
    collection?: DatasetCollection;
    parentId?: string | null;
  } | null>(null);
  const [collectionFormLoading, setCollectionFormLoading] = useState(false);
  const [collectionFormError, setCollectionFormError] = useState<string | null>(null);
  const [collectionToDelete, setCollectionToDelete] = useState<DatasetCollection | null>(null);
  const [deletingCollection, setDeletingCollection] = useState(false);
  const [deleteCollectionError, setDeleteCollectionError] = useState<string | null>(null);
  const [movingCollection, setMovingCollection] = useState<DatasetCollection | null>(null);
  const [movingDataset, setMovingDataset] = useState<DatasetListItem | null>(null);
  const [moveLoading, setMoveLoading] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);
  const deferredSearch = useDeferredValue(search);

  const summary = data?.summary;
  const datasets = data?.datasets ?? [];
  const collections = data?.collections ?? [];
  const requestedCollectionId = searchParams.get("collection");
  const flatView = searchParams.get("view") === "flat";
  const currentCollection = collections.find((item) => item.id === requestedCollectionId) ?? null;
  const currentCollectionId = currentCollection?.id ?? null;
  const crumbs = collectionBreadcrumb(collections, currentCollection?.id ?? null);

  const filteredDatasets = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((dataset) => {
      const content = [
        dataset.name,
        dataset.description,
        ...dataset.categories,
        ...(dataset.collectionPath ?? []).map((item) => item.name),
      ]
        .join(" ")
        .toLowerCase();
      return content.includes(needle);
    });
  }, [datasets, deferredSearch]);

  const filteredCollections = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase();
    if (!needle) return collections;
    return collections.filter((collection) => {
      const content = [collection.name, collection.description].join(" ").toLowerCase();
      return content.includes(needle);
    });
  }, [collections, deferredSearch]);

  const visibleCollections = useMemo(() => {
    if (flatView) return [];
    if (deferredSearch.trim()) return filteredCollections;
    return childCollections(filteredCollections, currentCollectionId);
  }, [currentCollectionId, deferredSearch, filteredCollections, flatView]);

  const visibleDatasets = useMemo(() => {
    if (deferredSearch.trim() || flatView) return filteredDatasets;
    return datasetsInCollection(filteredDatasets, currentCollectionId);
  }, [currentCollectionId, deferredSearch, filteredDatasets, flatView]);

  const treeData = useMemo<DataNode[]>(() => {
    function nodes(parentId: string | null): DataNode[] {
      const folderNodes = childCollections(collections, parentId).map((collection) => ({
        key: `collection:${collection.id}`,
        title: collection.name,
        children: [
          ...nodes(collection.id),
          ...datasetsInCollection(datasets, collection.id).map((dataset) => ({
            key: `dataset:${dataset.id}`,
            title: dataset.name,
            isLeaf: true,
          })),
        ],
      }));
      if (parentId === null) {
        return [
          ...folderNodes,
          ...datasetsInCollection(datasets, null).map((dataset) => ({
            key: `dataset:${dataset.id}`,
            title: dataset.name,
            isLeaf: true,
          })),
        ];
      }
      return folderNodes;
    }
    return [{ key: "root", title: "全部数据集", children: nodes(null) }];
  }, [collections, datasets]);

  const metrics = [
    { label: "数据集", value: summary?.totalDatasets ?? 0 },
    { label: "分组", value: summary?.totalCollections ?? collections.length },
    { label: "图片总数", value: summary?.totalImages ?? 0 },
    { label: "累计成本", value: formatCurrency(summary?.costToDate ?? 0) },
  ];

  function setCollectionParam(collectionId: string | null, view?: string | null) {
    const next = new URLSearchParams(searchParams);
    if (collectionId) next.set("collection", collectionId);
    else next.delete("collection");
    if (view === "flat") next.set("view", "flat");
    else next.delete("view");
    setSearchParams(next, { replace: true });
  }

  async function invalidateDatasets() {
    await queryClient.invalidateQueries({ queryKey: ["datasets", token] });
  }

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
      await invalidateDatasets();
    } catch (error) {
      setDeleteError((error as Error).message);
    } finally {
      setDeletingDatasetId(null);
    }
  }

  async function submitCollectionForm(payload: { name: string; description: string }) {
    if (!token || !collectionForm) return;
    setCollectionFormLoading(true);
    setCollectionFormError(null);
    try {
      if (collectionForm.mode === "create") {
        await createDatasetCollection(
          {
            name: payload.name,
            description: payload.description,
            parentId: collectionForm.parentId ?? currentCollection?.id ?? null,
          },
          token,
        );
      } else if (collectionForm.collection) {
        await updateDatasetCollection(
          collectionForm.collection.id,
          { name: payload.name, description: payload.description },
          token,
        );
      }
      setCollectionForm(null);
      await invalidateDatasets();
    } catch (error) {
      setCollectionFormError((error as Error).message);
    } finally {
      setCollectionFormLoading(false);
    }
  }

  async function removeCollection(cascade: boolean) {
    if (!token || !collectionToDelete) return;
    setDeletingCollection(true);
    setDeleteCollectionError(null);
    try {
      await deleteDatasetCollection(collectionToDelete.id, token, cascade);
      if (currentCollectionId === collectionToDelete.id) {
        setCollectionParam(collectionToDelete.parentId ?? null, flatView ? "flat" : null);
      }
      setCollectionToDelete(null);
      await invalidateDatasets();
    } catch (error) {
      setDeleteCollectionError((error as Error).message);
    } finally {
      setDeletingCollection(false);
    }
  }

  async function moveCollection(parentId: string | null) {
    if (!token || !movingCollection) return;
    setMoveLoading(true);
    setMoveError(null);
    try {
      await updateDatasetCollection(movingCollection.id, { parentId }, token);
      setMovingCollection(null);
      await invalidateDatasets();
    } catch (error) {
      setMoveError((error as Error).message);
    } finally {
      setMoveLoading(false);
    }
  }

  async function moveDataset(collectionId: string | null) {
    if (!token || !movingDataset) return;
    setMoveLoading(true);
    setMoveError(null);
    try {
      await updateDataset(movingDataset.id, { collectionId }, token);
      setMovingDataset(null);
      await invalidateDatasets();
    } catch (error) {
      setMoveError((error as Error).message);
    } finally {
      setMoveLoading(false);
    }
  }

  function collectionMenu(collection: DatasetCollection): DropdownMenuProps["items"] {
    return [
      { key: "open", label: "打开" },
      { key: "rename", label: "重命名" },
      { key: "move", label: "移动" },
      { key: "child", label: "新建子分组" },
      { type: "divider" },
      { key: "delete", label: "删除", danger: true },
    ];
  }

  function handleCollectionMenu(collection: DatasetCollection, key: string) {
    if (key === "open") setCollectionParam(collection.id);
    if (key === "rename") {
      setCollectionFormError(null);
      setCollectionForm({ mode: "rename", collection });
    }
    if (key === "move") {
      setMoveError(null);
      setMovingCollection(collection);
    }
    if (key === "child") {
      setCollectionParam(collection.id);
      setCollectionFormError(null);
      setCollectionForm({ mode: "create", parentId: collection.id });
    }
    if (key === "delete") {
      setDeleteCollectionError(null);
      setCollectionToDelete(collection);
    }
  }

  if (isLoading) {
    return (
      <PageContainer>
        <LoadingState rows={6} />
      </PageContainer>
    );
  }

  const searching = Boolean(deferredSearch.trim());
  const createDatasetTo = currentCollection
    ? `/datasets/new?collection=${currentCollection.id}`
    : "/datasets/new";
  const emptyTitle = searching
    ? "没有找到匹配的数据集或分组"
    : currentCollection
      ? "这个分组还是空的"
      : "还没有数据集";
  const emptyDescription = searching
    ? "请尝试缩短关键词，或按其他名称、说明和类别搜索。"
    : currentCollection
      ? "可以在此新建子分组，或创建真正用于生成、标注和训练的数据集。"
      : "创建第一个数据集，或先建分组来组织安全生产等业务场景。";

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
              用分组管理场景，叶子数据集负责训练
            </Title>
            <Paragraph className="mt-4 max-w-2xl !text-base leading-7 text-neutral-500 dark:text-neutral-400">
              例如「安全生产 / 人员劳动防护 / 安全帽」。中间层只用于导航，图片和标注仍在叶子数据集里完成。
            </Paragraph>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to={createDatasetTo}>
                <Button type="primary" size="large" icon={<FolderPlus className="h-4 w-4" />}>
                  新建数据集
                </Button>
              </Link>
              <Button
                size="large"
                icon={<Folder className="h-4 w-4" />}
                onClick={() => {
                  setCollectionFormError(null);
                  setCollectionForm({ mode: "create", parentId: currentCollection?.id ?? null });
                }}
              >
                新建分组
              </Button>
            </div>
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
          breadcrumb={<CollectionBreadcrumb items={crumbs} currentLabel={searching ? "搜索结果" : undefined} />}
          eyebrow={currentCollection ? "分组" : "全部数据集"}
          title={currentCollection?.name ?? "数据集管理"}
          description={
            currentCollection?.description ||
            (flatView ? "按完整列表查看全部数据集。" : "进入分组查看子数据集，或切换到全部扁平列表。")
          }
          actions={
            <div className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
              <Segmented
                value={flatView ? "flat" : "tree"}
                onChange={(value) => setCollectionParam(value === "flat" ? null : currentCollection?.id ?? null, value === "flat" ? "flat" : null)}
                options={[
                  { label: "分组浏览", value: "tree" },
                  { label: "全部扁平", value: "flat" },
                ]}
              />
              <Input.Search
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="按名称、描述、类别或路径过滤"
                allowClear
                className="w-full md:w-80"
              />
            </div>
          }
        />

        <div className="flex gap-6">
          {isMobile || flatView || searching ? null : (
            <Card className="hidden w-72 shrink-0 lg:block" styles={{ body: { padding: 12 } }}>
              <Tree
                defaultExpandAll
                selectedKeys={[
                  currentCollection ? `collection:${currentCollection.id}` : "root",
                ]}
                treeData={treeData}
                onSelect={(keys) => {
                  const key = String(keys[0] ?? "root");
                  if (key === "root") {
                    setCollectionParam(null);
                    return;
                  }
                  if (key.startsWith("collection:")) {
                    setCollectionParam(key.slice("collection:".length));
                    return;
                  }
                  if (key.startsWith("dataset:")) {
                    navigate(`/datasets/${key.slice("dataset:".length)}`);
                  }
                }}
              />
            </Card>
          )}

          <div className="min-w-0 flex-1">
            {visibleCollections.length > 0 && !flatView ? (
              <List
                className="mb-4"
                grid={{ gutter: 16, xs: 1, sm: 1, md: 1, lg: 1, xl: 1, xxl: 1 }}
                dataSource={visibleCollections}
                renderItem={(collection) => (
                  <List.Item key={collection.id}>
                    <CollectionCard
                      collection={collection}
                      onOpen={() => setCollectionParam(collection.id)}
                      menuItems={collectionMenu(collection)?.map((item) =>
                        item && "key" in item
                          ? {
                              ...item,
                              onClick: () => handleCollectionMenu(collection, String(item.key)),
                            }
                          : item,
                      )}
                    />
                  </List.Item>
                )}
              />
            ) : null}

            <List
              grid={{ gutter: 16, xs: 1, sm: 1, md: 1, lg: 1, xl: 1, xxl: 1 }}
              dataSource={visibleDatasets}
              locale={{
                emptyText:
                  visibleCollections.length > 0 ? (
                    <span />
                  ) : (
                    <Empty
                      image={<ScanSearch className="mx-auto h-12 w-12 text-neutral-400" />}
                      description={
                        <div className="text-center">
                          <Text className="block text-lg">{emptyTitle}</Text>
                          <Text className="block text-sm text-neutral-500">{emptyDescription}</Text>
                        </div>
                      }
                    />
                  ),
              }}
              renderItem={(dataset) => (
                <List.Item key={dataset.id}>
                  <DatasetCard
                    dataset={dataset}
                    onDelete={openDeleteDataset}
                    onMove={(item) => {
                      setMoveError(null);
                      setMovingDataset(item);
                    }}
                  />
                </List.Item>
              )}
            />
          </div>
        </div>
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
      <CollectionFormModal
        open={collectionForm !== null}
        title={collectionForm?.mode === "rename" ? "重命名分组" : "新建分组"}
        confirmText={collectionForm?.mode === "rename" ? "保存" : "创建"}
        initialName={collectionForm?.collection?.name ?? ""}
        initialDescription={collectionForm?.collection?.description ?? ""}
        loading={collectionFormLoading}
        error={collectionFormError}
        onClose={() => {
          if (!collectionFormLoading) setCollectionForm(null);
        }}
        onSubmit={submitCollectionForm}
      />
      <DeleteCollectionModal
        open={collectionToDelete !== null}
        collection={collectionToDelete}
        loading={deletingCollection}
        error={deleteCollectionError}
        onClose={() => {
          if (!deletingCollection) setCollectionToDelete(null);
        }}
        onConfirm={removeCollection}
      />
      <MoveToCollectionModal
        open={movingCollection !== null}
        title="移动分组"
        collections={collections}
        currentCollectionId={movingCollection?.parentId ?? null}
        excludeCollectionIds={
          movingCollection ? excludedIdsForCollectionMove(collections, movingCollection.id) : undefined
        }
        loading={moveLoading}
        error={moveError}
        onClose={() => {
          if (!moveLoading) setMovingCollection(null);
        }}
        onConfirm={moveCollection}
      />
      <MoveToCollectionModal
        open={movingDataset !== null}
        title="移动数据集"
        collections={collections}
        currentCollectionId={movingDataset?.collectionId ?? null}
        loading={moveLoading}
        error={moveError}
        onClose={() => {
          if (!moveLoading) setMovingDataset(null);
        }}
        onConfirm={moveDataset}
      />
    </PageContainer>
  );
}
