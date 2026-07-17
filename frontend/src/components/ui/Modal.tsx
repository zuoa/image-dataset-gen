import { Modal as AntModal } from "antd";
import type { ModalProps as AntModalProps } from "antd";

export function Modal(props: AntModalProps) {
  return <AntModal {...props} />;
}
