import { Card as AntCard } from "antd";
import type { CardProps as AntCardProps } from "antd";

export function Card(props: AntCardProps) {
  return <AntCard {...props} />;
}
