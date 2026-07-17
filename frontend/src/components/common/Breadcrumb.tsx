import { Breadcrumb as AntBreadcrumb } from "antd";
import { Link } from "react-router-dom";

interface BreadcrumbItem {
  label: React.ReactNode;
  path?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <AntBreadcrumb
      items={items.map((item) => ({
        title: item.path ? <Link to={item.path}>{item.label}</Link> : item.label,
      }))}
    />
  );
}
