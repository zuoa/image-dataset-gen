import { Space, Typography } from "antd";
import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions, breadcrumb }: PageHeaderProps) {
  return (
    <div className="mb-6">
      {breadcrumb ? <div className="mb-4">{breadcrumb}</div> : null}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex-1">
          {eyebrow ? (
            <Typography.Text className="mb-2 block text-xs uppercase tracking-[0.2em] text-neutral-500 dark:text-neutral-400">
              {eyebrow}
            </Typography.Text>
          ) : null}
          {title ? (
            <Typography.Title level={2} className="!mb-2 !text-2xl !font-medium">
              {title}
            </Typography.Title>
          ) : null}
          {description ? (
            <Typography.Text className="block max-w-2xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
              {description}
            </Typography.Text>
          ) : null}
        </div>
        {actions ? <Space wrap className="lg:pt-1">{actions}</Space> : null}
      </div>
    </div>
  );
}
