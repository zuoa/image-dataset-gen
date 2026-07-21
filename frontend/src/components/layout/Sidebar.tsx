import { Boxes, Cpu, Plus, Server, X } from "lucide-react";
import { Button, Menu, Typography } from "antd";
import type { MenuProps } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../../store/auth";

type MenuItem = Required<MenuProps>["items"][number];

const navItems: MenuItem[] = [
  { key: "/", icon: <Boxes aria-hidden="true" className="h-4 w-4" />, label: "数据集" },
  { key: "/models", icon: <Cpu aria-hidden="true" className="h-4 w-4" />, label: "模型配置" },
  { key: "/trainers", icon: <Server aria-hidden="true" className="h-4 w-4" />, label: "训练设备" },
];

interface SidebarProps {
  collapsed?: boolean;
  onClose?: () => void;
  onNavigate?: () => void;
}

export function Sidebar({ collapsed, onClose, onNavigate }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);

  const selectedKey = location.pathname.startsWith("/models")
    ? "/models"
    : location.pathname.startsWith("/trainers")
      ? "/trainers"
      : "/";

  return (
    <div className="flex h-full flex-col bg-[var(--df-color-bg-container)] p-3">
      <div className="flex min-h-16 items-center px-2 py-3">
        {collapsed ? (
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--df-color-text)] font-mono text-xs font-semibold text-[var(--df-color-bg-container)]">
            DF
          </div>
        ) : (
          <div className="flex w-full min-w-0 items-center justify-between gap-3">
            <div className="min-w-0">
              <Typography.Title level={4} className="truncate !m-0 !text-lg !font-semibold">
                Dataset Forge
              </Typography.Title>
              <Typography.Text className="mt-0.5 block truncate text-xs text-neutral-500 dark:text-neutral-400">
                视觉数据工作台
              </Typography.Text>
            </div>
            {onClose ? (
              <Button
                type="text"
                icon={<X aria-hidden="true" className="h-4 w-4" />}
                onClick={onClose}
                aria-label="关闭导航"
              />
            ) : null}
          </div>
        )}
      </div>

      <Button
        type="primary"
        block
        icon={<Plus aria-hidden="true" className="h-4 w-4" />}
        onClick={() => {
          navigate("/datasets/new");
          onNavigate?.();
        }}
        aria-label={collapsed ? "新建数据集" : undefined}
        className="mb-3"
      >
        {collapsed ? null : "新建数据集"}
      </Button>

      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        items={navItems}
        inlineCollapsed={collapsed}
        onClick={({ key }) => {
          navigate(key);
          onNavigate?.();
        }}
        className="flex-1 border-none bg-transparent dark:[&_.ant-menu-item-selected]:bg-white/10"
      />

      {!collapsed ? (
        <div className="border-t border-neutral-200 px-2 pt-4 dark:border-white/10">
          <Typography.Text className="block text-xs text-neutral-500 dark:text-neutral-400">当前账户</Typography.Text>
          <div className="mt-1 truncate text-sm font-medium">{user?.username}</div>
          <div className="truncate text-xs text-neutral-500">{user?.plan ?? "pro"}</div>
        </div>
      ) : null}
    </div>
  );
}
