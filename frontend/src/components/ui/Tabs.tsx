import { Tabs as AntTabs } from "antd";
import type { TabsProps as AntTabsProps } from "antd";

export function Tabs(props: AntTabsProps) {
  return <AntTabs {...props} />;
}

Tabs.TabPane = AntTabs.TabPane;
