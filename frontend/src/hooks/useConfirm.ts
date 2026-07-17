import { App } from "antd";
import type { ModalFuncProps } from "antd";
import { useCallback } from "react";

interface ConfirmOptions extends Omit<ModalFuncProps, "onOk" | "onCancel"> {
  okDanger?: boolean;
}

export function useConfirm() {
  const { modal } = App.useApp();

  return useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      const { okDanger, okButtonProps, ...modalOptions } = options;
      modal.confirm({
        ...modalOptions,
        okButtonProps: {
          ...okButtonProps,
          danger: okDanger ?? okButtonProps?.danger,
        },
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  }, [modal]);
}
