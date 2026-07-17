import { Modal } from "antd";
import type { ModalFuncProps } from "antd";
import { useCallback } from "react";

interface ConfirmOptions extends Omit<ModalFuncProps, "onOk" | "onCancel"> {
  okDanger?: boolean;
}

export function useConfirm() {
  return useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      Modal.confirm({
        ...options,
        okButtonProps: {
          ...options.okButtonProps,
          danger: options.okDanger,
        },
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  }, []);
}

export async function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      ...options,
      okButtonProps: {
        ...options.okButtonProps,
        danger: options.okDanger,
      },
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}
