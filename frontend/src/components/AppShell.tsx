import { BarChart3, Cpu, LogOut, Sparkles } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuthStore } from "../store/auth";
import { cn } from "../lib/utils";

const navItems = [
  { to: "/", label: "控制台", icon: BarChart3 },
  { to: "/tasks/new", label: "新建任务", icon: Sparkles },
  { to: "/models", label: "模型管理", icon: Cpu },
];

export function AppShell() {
  const user = useAuthStore((state) => state.user);
  const signOut = useAuthStore((state) => state.signOut);

  return (
    <div className="min-h-screen bg-white text-neutral-900 dark:bg-neutral-950 dark:text-white">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(0,0,0,0.025),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(0,0,0,0.015),transparent_28%)] dark:bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.045),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(255,255,255,0.03),transparent_28%)]" />
      <div className="pointer-events-none fixed inset-0 bg-grid-fade bg-[size:24px_24px] opacity-[0.05] dark:opacity-[0.025]" />
      <div className="relative mx-auto grid min-h-screen max-w-[1600px] grid-cols-1 xl:grid-cols-[280px_1fr]">
        <aside className="flex flex-col border-b border-neutral-200 p-6 dark:border-white/12 xl:border-b-0 xl:border-r">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-400 dark:text-neutral-500">Synthetic Vision Ops Platform</div>
            <h1 className="mt-1 text-xl font-medium leading-tight text-neutral-900 dark:text-white">Dataset Forge</h1>
            <p className="mt-2 text-xs leading-5 text-neutral-500 dark:text-neutral-400">
              用结构化工作流压缩图像数据集生产周期。
            </p>
          </div>

          <nav className="mt-8 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm transition",
                      isActive
                        ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950"
                        : "text-neutral-500 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-white/[0.06] dark:hover:text-white",
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </NavLink>
              );
            })}
          </nav>

          <div className="mt-auto border-t border-neutral-200 pt-6 dark:border-white/12">
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-400 dark:text-neutral-500">Workspace</div>
            <div className="mt-3 text-sm text-neutral-900 dark:text-white">{user?.email}</div>
            <div className="mt-1 text-xs text-neutral-500">{user?.plan ?? "pro"}</div>
            <div className="mt-4 flex items-center gap-3">
              <button
                className="inline-flex items-center gap-2 text-xs text-neutral-500 transition hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white"
                onClick={() => signOut()}
              >
                <LogOut className="h-4 w-4" />
                退出登录
              </button>
            </div>
          </div>
        </aside>

        <main className="p-4 md:p-6 xl:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
