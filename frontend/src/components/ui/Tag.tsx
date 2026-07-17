import { Tag as AntTag } from "antd";
import type { TagProps as AntTagProps } from "antd";

export function Tag(props: AntTagProps) {
  return <AntTag {...props} />;
}
