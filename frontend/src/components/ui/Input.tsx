import { Input as AntInput } from "antd";
import type { InputProps as AntInputProps } from "antd";

export function Input(props: AntInputProps) {
  return <AntInput {...props} />;
}
