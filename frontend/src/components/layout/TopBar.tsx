import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Space } from "antd";
import type { RouteObject } from "react-router-dom";
import { Link, matchRoutes, useLocation } from "react-router-dom";

import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";

interface TopBarProps {
  collapsed: boolean;
  onToggle: () => void;
}

interface BreadcrumbHandle {
  title: string;
  to?: string;
}

const breadcrumbRoutes: RouteObject[] = [
  { path: "/", handle: { title: "数据集" } satisfies BreadcrumbHandle },
  {
    path: "/datasets",
    handle: { title: "数据集", to: "/" } satisfies BreadcrumbHandle,
    children: [
      { path: "new", handle: { title: "新建数据集" } satisfies BreadcrumbHandle },
      {
        path: ":datasetId",
        handle: { title: "数据集详情" } satisfies BreadcrumbHandle,
        children: [
          { path: "generate", handle: { title: "生成图片" } satisfies BreadcrumbHandle },
        ],
      },
    ],
  },
  { path: "/models", handle: { title: "模型管理" } satisfies BreadcrumbHandle },
  { path: "/trainers", handle: { title: "训练设备" } satisfies BreadcrumbHandle },
];

export function TopBar({ collapsed, onToggle }: TopBarProps) {
  const location = useLocation();
  const matches = matchRoutes(breadcrumbRoutes, location) ?? [];

  const breadcrumbItems = matches
    .filter((match) => match.route.handle)
    .map((match, index, array) => {
      const handle = match.route.handle as BreadcrumbHandle;
      const isLast = index === array.length - 1;
      return {
        title: isLast ? handle.title : <Link to={handle.to ?? match.pathname}>{handle.title}</Link>,
      };
    });

  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3">
      <div className="flex items-center gap-3">
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={onToggle}
          aria-label={collapsed ? "展开导航" : "收起导航"}
        />
        {breadcrumbItems.length > 0 ? (
          <Breadcrumb items={breadcrumbItems} />
        ) : null}
      </div>
      <Space>
        <ThemeToggle />
        <UserMenu />
      </Space>
    </div>
  );
}
