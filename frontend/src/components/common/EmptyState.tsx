import { Button, Empty } from "antd";
import type { ReactNode } from "react";

interface EmptyStateProps {
  title?: ReactNode;
  description?: ReactNode;
  action?: {
    label: ReactNode;
    onClick: () => void;
  };
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <Empty
      className="py-12"
      description={
        <div className="text-center">
          {title ? <div className="text-base font-medium">{title}</div> : null}
          {description ? <div className="mt-1 text-sm text-neutral-500">{description}</div> : null}
          {action ? (
            <Button type="primary" className="mt-4" onClick={action.onClick}>
              {action.label}
            </Button>
          ) : null}
        </div>
      }
    />
  );
}
