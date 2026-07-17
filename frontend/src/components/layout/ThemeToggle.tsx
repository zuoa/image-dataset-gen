import { Moon, Sun, Monitor } from "lucide-react";
import { Button, Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";

import { useThemeStore } from "../../store/theme";
import type { ThemeMode } from "../../lib/theme";

const modes: { key: ThemeMode; label: string; icon: React.ElementType }[] = [
  { key: "light", label: "浅色", icon: Sun },
  { key: "dark", label: "深色", icon: Moon },
  { key: "system", label: "跟随系统", icon: Monitor },
];

export function ThemeToggle() {
  const mode = useThemeStore((state) => state.mode);
  const setMode = useThemeStore((state) => state.setMode);

  const active = modes.find((m) => m.key === mode) ?? modes[0];
  const Icon = active.icon;

  const items: MenuProps["items"] = modes.map((m) => ({
    key: m.key,
    label: m.label,
    icon: <m.icon className="h-4 w-4" />,
  }));

  return (
    <Dropdown
      menu={{
        items,
        selectable: true,
        selectedKeys: [mode],
        onClick: ({ key }) => setMode(key as ThemeMode),
      }}
      placement="bottomRight"
      trigger={["click"]}
    >
      <Tooltip title="切换主题">
        <Button type="text" icon={<Icon className="h-4 w-4" />} />
      </Tooltip>
    </Dropdown>
  );
}
