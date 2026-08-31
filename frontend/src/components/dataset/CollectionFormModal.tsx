import { useEffect, useState } from "react";
import { Form, Input, Modal } from "antd";

interface CollectionFormModalProps {
  open: boolean;
  title: string;
  confirmText?: string;
  initialName?: string;
  initialDescription?: string;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onSubmit: (payload: { name: string; description: string }) => void | Promise<void>;
}

export function CollectionFormModal({
  open,
  title,
  confirmText = "保存",
  initialName = "",
  initialDescription = "",
  loading = false,
  error,
  onClose,
  onSubmit,
}: CollectionFormModalProps) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);

  useEffect(() => {
    if (!open) return;
    setName(initialName);
    setDescription(initialDescription);
  }, [open, initialName, initialDescription]);

  const trimmedName = name.trim();

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      onOk={() => {
        if (!trimmedName || loading) return;
        void onSubmit({ name: trimmedName, description: description.trim() });
      }}
      okText={confirmText}
      cancelText="取消"
      okButtonProps={{ disabled: !trimmedName }}
      confirmLoading={loading}
      destroyOnClose
    >
      <Form layout="vertical" className="mt-4">
        <Form.Item label="分组名称" required>
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：安全生产"
            maxLength={255}
            autoFocus
          />
        </Form.Item>
        <Form.Item label="说明">
          <Input.TextArea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="可选，记录这个分组覆盖的场景或用途。"
            rows={3}
            maxLength={1000}
          />
        </Form.Item>
        {error ? <div className="text-sm text-red-600 dark:text-red-400">{error}</div> : null}
      </Form>
    </Modal>
  );
}
