import { Slider as AntSlider } from "antd";
import type { SliderSingleProps } from "antd";

export function Slider(props: SliderSingleProps) {
  return <AntSlider {...props} />;
}
