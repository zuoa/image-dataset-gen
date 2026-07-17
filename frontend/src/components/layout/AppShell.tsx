import { Drawer, Layout } from "antd";
import { useState } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useMediaQuery } from "../../hooks/useMediaQuery";

const { Sider, Header, Content } = Layout;

export function AppShell() {
  const isMobile = useMediaQuery("(max-width: 1024px)");
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <Layout className="min-h-screen bg-[#f6f7f9] dark:bg-[#0b0f14]">
      <a
        href="#main-content"
        className="fixed left-3 top-3 z-[100] -translate-y-20 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-transform focus:translate-y-0"
      >
        跳到主要内容
      </a>

      {!isMobile ? (
        <Sider
          trigger={null}
          collapsible
          collapsed={desktopCollapsed}
          collapsedWidth={72}
          width={240}
          className="border-r border-[#d7dce3] bg-white dark:border-white/10 dark:bg-[#11151b]"
        >
          <Sidebar collapsed={desktopCollapsed} />
        </Sider>
      ) : null}

      {isMobile ? (
        <Drawer
          aria-label="主导航"
          placement="left"
          width={280}
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          closable={false}
          styles={{ body: { padding: 0 } }}
        >
          <Sidebar onClose={() => setMobileOpen(false)} onNavigate={() => setMobileOpen(false)} />
        </Drawer>
      ) : null}

      <Layout className="min-w-0 bg-transparent">
        <Header className="sticky top-0 z-40 h-auto border-b border-[#d7dce3] bg-white/90 backdrop-blur dark:border-white/10 dark:bg-[#11151b]/90">
          <TopBar
            collapsed={isMobile ? !mobileOpen : desktopCollapsed}
            onToggle={() => {
              if (isMobile) setMobileOpen((current) => !current);
              else setDesktopCollapsed((current) => !current);
            }}
          />
        </Header>
        <Content id="main-content" className="p-4 md:p-6">
          <div className="mx-auto max-w-[1600px]">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
