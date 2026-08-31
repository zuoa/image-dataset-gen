import { useEffect, useMemo, useState } from "react";
import { Modal, Tree } from "antd";
import type { DataNode } from "antd/es/tree";
import { Folder } from "lucide-react";

import { childCollections, descendantCollectionIds } from "../../lib/collections";
import type { DatasetCollection } from "../../lib/types";

interface MoveToCollectionModalProps {
  open: boolean;
  title: string;
  collections: DatasetCollection[];
  currentCollectionId?: string | null;
  excludeCollectionIds?: Set<string>;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onConfirm: (collectionId: string | null) => void | Promise<void>;
}

export function MoveToCollectionModal({
  open,
  title,
  collections,
  currentCollectionId = null,
  excludeCollectionIds,
  loading = false,
  error,
  onClose,
  onConfirm,
}: MoveToCollectionModalProps) {
  const [selectedId, setSelectedId] = useState<string | null>(currentCollectionId);

  useEffect(() => {
    if (open) setSelectedId(currentCollectionId ?? null);
  }, [open, currentCollectionId]);

  const treeData = useMemo<DataNode[]>(() => {
    function nodes(parentId: string | null): DataNode[] {
      return childCollections(collections, parentId)
        .filter((collection) => !excludeCollectionIds?.has(collection.id))
        .map((collection) => ({
          key: collection.id,
          title: collection.name,
          icon: <Folder className="h-3.5 w-3.5" />,
          children: nodes(collection.id),
        }));
    }
    return [
      {
        key: "root",
        title: "未分组 / 根目录",
        icon: <Folder className="h-3.5 w-3.5" />,
        children: nodes(null),
      },
    ];
  }, [collections, excludeCollectionIds]);

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      onOk={() => void onConfirm(selectedId)}
      okText="移动"
      cancelText="取消"
      confirmLoading={loading}
      destroyOnClose
    >
      <p className="mb-3 text-sm text-neutral-500">选择要放入的分组。根目录表示不归属任何分组。</p>
      <Tree
        showIcon
        defaultExpandAll
        selectedKeys={[selectedId ?? "root"]}
        treeData={treeData}
        onSelect={(keys) => {
          const key = String(keys[0] ?? "root");
          setSelectedId(key === "root" ? null : key);
        }}
      />
      {error ? <div className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</div> : null}
    </Modal>
  );
}

export function excludedIdsForCollectionMove(
  collections: DatasetCollection[],
  collectionId: string,
) {
  return descendantCollectionIds(collections, collectionId);
}
