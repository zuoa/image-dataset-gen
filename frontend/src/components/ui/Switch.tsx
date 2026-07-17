import { Switch as AntSwitch } from "antd";
import type { SwitchProps as AntSwitchProps } from "antd";

export function Switch(props: AntSwitchProps) {
  return <AntSwitch {...props} />;
}
