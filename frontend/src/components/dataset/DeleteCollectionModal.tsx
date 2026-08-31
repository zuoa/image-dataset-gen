import { useEffect, useState } from "react";
import { Alert, Checkbox, Input, Modal, Typography } from "antd";
import { Trash2 } from "lucide-react";

import type { DatasetCollection } from "../../lib/types";

interface DeleteCollectionModalProps {
  open: boolean;
  collection: DatasetCollection | null;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onConfirm: (cascade: boolean) => void | Promise<void>;
}

export function DeleteCollectionModal({
  open,
  collection,
  loading = false,
  error,
  onClose,
  onConfirm,
}: DeleteCollectionModalProps) {
  const [confirmation, setConfirmation] = useState("");
  const [cascade, setCascade] = useState(false);

  useEffect(() => {
    setConfirmation("");
    setCascade(false);
  }, [collection?.id, open]);

  const hasChildren =
    (collection?.stats.childCollectionCount ?? 0) > 0 ||
    (collection?.stats.directDatasetCount ?? 0) > 0;
  const matches = collection !== null && confirmation === collection.name;
  const canSubmit = matches && (!hasChildren || cascade);

  return (
    <Modal
      title={
        <span className="inline-flex items-center gap-2 text-red-600 dark:text-red-400">
          <Trash2 className="h-4 w-4" />
          删除分组
        </span>
      }
      open={open}
      onCancel={onClose}
      onOk={() => {
        if (canSubmit) void onConfirm(cascade);
      }}
      okText="永久删除"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !canSubmit }}
      confirmLoading={loading}
      closable={!loading}
      maskClosable={!loading}
    >
      {collection ? (
        <div className="space-y-4 py-2">
          <Alert
            type="error"
            showIcon
            message="此操作不可恢复"
            description={
              hasChildren
                ? `「${collection.name}」下有 ${collection.stats.childCollectionCount} 个子分组、${collection.stats.datasetCount} 个数据集。级联删除会同时删除这些数据集及其图片、标注和训练记录。`
                : `将删除空分组「${collection.name}」。`
            }
          />
          {error ? <Alert type="error" showIcon message={error} /> : null}
          {hasChildren ? (
            <Checkbox checked={cascade} onChange={(event) => setCascade(event.target.checked)}>
              同时删除此分组下的全部子分组和数据集
            </Checkbox>
          ) : null}
          <div>
            <Typography.Text className="text-sm text-slate-600 dark:text-slate-300">
              请输入分组名称 <strong>{collection.name}</strong> 以确认：
            </Typography.Text>
            <Input
              className="mt-2"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder={collection.name}
              autoComplete="off"
              disabled={loading}
              onPressEnter={() => {
                if (canSubmit && !loading) void onConfirm(cascade);
              }}
            />
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
