import { Segmented as AntSegmented } from "antd";
import type { SegmentedProps as AntSegmentedProps } from "antd";

export function Segmented<T extends string | number>(props: AntSegmentedProps<T>) {
  return <AntSegmented {...props} />;
}
