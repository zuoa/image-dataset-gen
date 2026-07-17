import { LogOut, User } from "lucide-react";
import { Avatar, Button, Dropdown } from "antd";
import type { MenuProps } from "antd";

import { useAuthStore } from "../../store/auth";

export function UserMenu() {
  const user = useAuthStore((state) => state.user);
  const signOut = useAuthStore((state) => state.signOut);

  const items: MenuProps["items"] = [
    {
      key: "profile",
      label: (
        <div className="py-1">
          <div className="font-medium">{user?.username}</div>
          <div className="text-xs text-neutral-500">{user?.plan ?? "pro"}</div>
        </div>
      ),
      disabled: true,
    },
    { type: "divider" },
    {
      key: "logout",
      label: "退出登录",
      icon: <LogOut className="h-4 w-4" />,
      danger: true,
      onClick: () => signOut(),
    },
  ];

  return (
    <Dropdown menu={{ items }} placement="bottomRight" trigger={["click"]}>
      <Button type="text" icon={<Avatar size="small" icon={<User className="h-4 w-4" />} />}>
        <span className="hidden md:inline">{user?.username}</span>
      </Button>
    </Dropdown>
  );
}
