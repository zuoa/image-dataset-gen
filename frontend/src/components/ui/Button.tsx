import { Button as AntButton } from "antd";
import type { ButtonProps as AntButtonProps } from "antd";

interface ButtonProps extends Omit<AntButtonProps, "variant"> {
  variant?: "primary" | "secondary" | "ghost";
}

export function Button({ variant = "primary", ...props }: ButtonProps) {
  const type =
    variant === "primary" ? "primary" : variant === "secondary" ? "default" : "text";
  return <AntButton type={type} {...props} />;
}
