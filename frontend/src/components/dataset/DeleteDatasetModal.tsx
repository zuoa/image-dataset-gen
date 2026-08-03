import { useEffect, useState } from "react";
import { Alert, Input, Modal, Typography } from "antd";
import { Trash2 } from "lucide-react";

import type { Dataset } from "../../lib/types";

interface DeleteDatasetModalProps {
  open: boolean;
  dataset: Dataset | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
}

export function DeleteDatasetModal({
  open,
  dataset,
  loading,
  error,
  onClose,
  onConfirm,
}: DeleteDatasetModalProps) {
  const [confirmation, setConfirmation] = useState("");

  useEffect(() => {
    setConfirmation("");
  }, [dataset?.id, open]);

  const matches = dataset !== null && confirmation === dataset.name;

  return (
    <Modal
      title={
        <span className="inline-flex items-center gap-2 text-red-600 dark:text-red-400">
          <Trash2 className="h-4 w-4" />
          删除数据集
        </span>
      }
      open={open}
      onCancel={onClose}
      onOk={() => void onConfirm()}
      okText="永久删除"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !matches }}
      confirmLoading={loading}
      closable={!loading}
      maskClosable={!loading}
    >
      {dataset ? (
        <div className="space-y-4 py-2">
          <Alert
            type="error"
            showIcon
            message="此操作不可恢复"
            description={`将永久删除 ${dataset.imageCount} 张图片、${dataset.taskCount} 条任务记录，以及关联的标注、导出、训练和质量记录。`}
          />
          {error ? <Alert type="error" showIcon message={error} /> : null}
          <div>
            <Typography.Text className="text-sm text-slate-600 dark:text-slate-300">
              请输入数据集名称 <strong>{dataset.name}</strong> 以确认：
            </Typography.Text>
            <Input
              className="mt-2"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder={dataset.name}
              autoComplete="off"
              disabled={loading}
              onPressEnter={() => {
                if (matches && !loading) void onConfirm();
              }}
            />
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
