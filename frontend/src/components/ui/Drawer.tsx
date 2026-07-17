import { Drawer as AntDrawer } from "antd";
import type { DrawerProps as AntDrawerProps } from "antd";

export function Drawer(props: AntDrawerProps) {
  return <AntDrawer {...props} />;
}
