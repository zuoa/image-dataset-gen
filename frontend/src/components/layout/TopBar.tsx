import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Space } from "antd";
import { Link, useMatches } from "react-router-dom";

import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";

interface TopBarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function TopBar({ collapsed, onToggle }: TopBarProps) {
  const matches = useMatches();

  // Build breadcrumb from matched routes that have a handle title.
  const breadcrumbItems = matches
    .filter((match) => match.handle && typeof match.handle === "object" && "title" in match.handle)
    .map((match, index, array) => {
      const title = (match.handle as { title: string }).title;
      const isLast = index === array.length - 1;
      return {
        title: isLast ? title : <Link to={match.pathname}>{title}</Link>,
      };
    });

  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3">
      <div className="flex items-center gap-3">
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={onToggle}
          className="lg:hidden"
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
