import { Card as AntCard } from "antd";
import type { CardProps as AntCardProps } from "antd";

interface SectionCardProps extends AntCardProps {}

export function SectionCard({ children, ...props }: SectionCardProps) {
  return <AntCard {...props}>{children}</AntCard>;
}
