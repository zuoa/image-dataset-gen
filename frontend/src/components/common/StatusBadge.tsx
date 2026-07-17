import { Tag } from "antd";
import type { TagProps } from "antd";

type Status =
  | "pending"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "draft"
  | "online"
  | "offline"
  | "idle"
  | "busy"
  | "annotated"
  | "unannotated"
  | "empty"
  | string;

const statusColorMap: Record<string, TagProps["color"]> = {
  pending: "default",
  draft: "default",
  running: "processing",
  busy: "processing",
  paused: "warning",
  completed: "success",
  online: "success",
  idle: "success",
  annotated: "success",
  failed: "error",
  offline: "error",
  unannotated: "warning",
  empty: "default",
};

interface StatusBadgeProps extends Omit<TagProps, "color"> {
  status: Status;
}

export function StatusBadge({ status, children, ...props }: StatusBadgeProps) {
  const color = statusColorMap[status] || "default";
  return (
    <Tag color={color} {...props}>
      {children ?? status}
    </Tag>
  );
}
