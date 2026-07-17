import { Layout } from "antd";
import { useState } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useMediaQuery } from "../../hooks/useMediaQuery";

const { Sider, Header, Content } = Layout;

export function AppShell() {
  const isMobile = useMediaQuery("(max-width: 1024px)");
  const [collapsed, setCollapsed] = useState(isMobile);

  return (
    <Layout className="min-h-screen">
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        collapsedWidth={isMobile ? 0 : 80}
        width={280}
        breakpoint="lg"
        onBreakpoint={(broken) => setCollapsed(broken)}
        className="!fixed inset-y-0 left-0 z-50 border-r border-neutral-200 bg-white dark:border-white/10 dark:bg-neutral-950 lg:!relative"
      >
        <Sidebar collapsed={collapsed} />
      </Sider>
      <Layout className="transition-all">
        <Header className="sticky top-0 z-40 h-auto border-b border-neutral-200 bg-white/80 backdrop-blur dark:border-white/10 dark:bg-neutral-950/80">
          <TopBar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        </Header>
        <Content className="p-4 md:p-6">
          <div className="mx-auto max-w-[1600px]">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
