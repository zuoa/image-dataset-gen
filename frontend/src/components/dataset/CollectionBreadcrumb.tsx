import { Breadcrumb } from "antd";
import { Link } from "react-router-dom";

import type { DatasetCollection, DatasetCollectionPathItem } from "../../lib/types";

interface CollectionBreadcrumbProps {
  items?: Array<DatasetCollection | DatasetCollectionPathItem>;
  currentLabel?: string;
}

export function CollectionBreadcrumb({ items = [], currentLabel }: CollectionBreadcrumbProps) {
  const crumbs = [
    { title: <Link to="/">全部数据集</Link> },
    ...items.map((item) => ({
      title: <Link to={`/?collection=${item.id}`}>{item.name}</Link>,
    })),
  ];
  if (currentLabel) {
    crumbs.push({ title: <span>{currentLabel}</span> });
  }
  return <Breadcrumb items={crumbs} />;
}
