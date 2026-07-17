import { Boxes, Cpu, Server, Sparkles } from "lucide-react";
import { Menu, Typography } from "antd";
import type { MenuProps } from "antd";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../../store/auth";

type MenuItem = Required<MenuProps>["items"][number];

const navItems: MenuItem[] = [
  { key: "/", icon: <Boxes className="h-4 w-4" />, label: "数据集" },
  { key: "/datasets/new", icon: <Sparkles className="h-4 w-4" />, label: "新建数据集" },
  { key: "/models", icon: <Cpu className="h-4 w-4" />, label: "模型管理" },
  { key: "/trainers", icon: <Server className="h-4 w-4" />, label: "训练节点" },
];

interface SidebarProps {
  collapsed?: boolean;
}

export function Sidebar({ collapsed }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);

  const selectedKeys = [location.pathname];

  return (
    <div className="flex h-full flex-col p-4">
      <div className="px-2 py-4">
        <Typography.Text className="block text-[10px] uppercase tracking-[0.2em] text-neutral-400 dark:text-neutral-500">
          Synthetic Vision Ops Platform
        </Typography.Text>
        <Typography.Title level={4} className="!m-0 !text-xl">
          Dataset Forge
        </Typography.Title>
        {!collapsed ? (
          <Typography.Text className="mt-2 block text-xs leading-5 text-neutral-500 dark:text-neutral-400">
            用数据集管理统一组织样本池、批次任务和导出结果。
          </Typography.Text>
        ) : null}
      </div>

      <Menu
        mode="inline"
        theme="light"
        selectedKeys={selectedKeys}
        items={navItems}
        inlineCollapsed={collapsed}
        onClick={({ key }) => navigate(key)}
        className="flex-1 border-none bg-transparent dark:[&_.ant-menu-item-selected]:bg-white/10"
      />

      <div className="border-t border-neutral-200 pt-4 dark:border-white/10">
        <Typography.Text className="block px-2 text-[10px] uppercase tracking-[0.2em] text-neutral-400 dark:text-neutral-500">
          Workspace
        </Typography.Text>
        <div className="mt-2 px-2 text-sm">{user?.username}</div>
        <div className="px-2 text-xs text-neutral-500">{user?.plan ?? "pro"}</div>
      </div>
    </div>
  );
}
