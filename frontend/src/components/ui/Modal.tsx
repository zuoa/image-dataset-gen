import { Modal as AntModal } from "antd";
import type { ModalProps as AntModalProps } from "antd";

export function Modal(props: AntModalProps) {
  return <AntModal {...props} />;
}

Modal.confirm = AntModal.confirm;
Modal.info = AntModal.info;
Modal.success = AntModal.success;
Modal.error = AntModal.error;
Modal.warning = AntModal.warning;
