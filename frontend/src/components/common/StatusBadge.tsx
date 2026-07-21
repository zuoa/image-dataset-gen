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

const statusLabelMap: Record<string, string> = {
  pending: "等待中",
  draft: "草稿",
  ready: "可用",
  running: "进行中",
  busy: "工作中",
  paused: "已暂停",
  completed: "已完成",
  online: "在线",
  offline: "离线",
  idle: "空闲",
  annotated: "已标注",
  unannotated: "未标注",
  empty: "空标注",
  failed: "失败",
  generation: "图片生成",
  augmentation: "数据增强",
  import: "数据导入",
  video: "视频导入",
  roboflow: "Roboflow 导入",
};

interface StatusBadgeProps extends Omit<TagProps, "color"> {
  status: Status;
}

export function StatusBadge({ status, children, ...props }: StatusBadgeProps) {
  const color = statusColorMap[status] || "default";
  return (
    <Tag color={color} {...props}>
      {children ?? statusLabelMap[status] ?? "未知状态"}
    </Tag>
  );
}
