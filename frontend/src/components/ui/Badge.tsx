import { Tag as AntTag } from "antd";
import type { TagProps as AntTagProps } from "antd";

interface BadgeProps extends AntTagProps {}

export function Badge({ children, ...props }: BadgeProps) {
  return (
    <AntTag bordered {...props}>
      {children}
    </AntTag>
  );
}
