import { Input as AntInput } from "antd";
import type { TextAreaProps as AntTextAreaProps } from "antd/es/input";

export function Textarea(props: AntTextAreaProps) {
  return <AntInput.TextArea {...props} />;
}
