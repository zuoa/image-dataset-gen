import { App as AntApp, ConfigProvider, Spin } from "antd";
import { useEffect, useMemo, Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { authExpiredEvent, authTokenRefreshedEvent, sessionExpiredMessage } from "./lib/session";
import { getAntTheme } from "./lib/theme";
import { AuthPage } from "./pages/AuthPage";
import { DatasetListPage } from "./pages/DatasetListPage";
import { useAuthStore } from "./store/auth";
import { useThemeStore } from "./store/theme";

const DatasetCreatePage = lazy(() =>
  import("./pages/DatasetCreatePage").then((m) => ({ default: m.DatasetCreatePage })),
);
const DatasetDetailPage = lazy(() =>
  import("./pages/DatasetDetailPage").then((m) => ({ default: m.DatasetDetailPage })),
);
const DatasetAnnotatePage = lazy(() =>
  import("./pages/DatasetAnnotatePage").then((m) => ({ default: m.DatasetAnnotatePage })),
);
const GenerationTaskPage = lazy(() =>
  import("./pages/GenerationTaskPage").then((m) => ({ default: m.GenerationTaskPage })),
);
const ModelManagementPage = lazy(() =>
  import("./pages/ModelManagementPage").then((m) => ({ default: m.ModelManagementPage })),
);
const TrainerFleetPage = lazy(() =>
  import("./pages/TrainerFleetPage").then((m) => ({ default: m.TrainerFleetPage })),
);

function PageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spin tip="加载页面…" />
    </div>
  );
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();
  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-neutral-500 dark:text-neutral-400">
        正在恢复登录状态…
      </div>
    );
  }
  return status === "authenticated" ? (
    <>{children}</>
  ) : (
    <Navigate
      to="/auth"
      replace
      state={{ from: `${location.pathname}${location.search}${location.hash}` }}
    />
  );
}

function AppContent() {
  const hydrate = useAuthStore((state) => state.hydrate);
  const signOut = useAuthStore((state) => state.signOut);
  const initTheme = useThemeStore((state) => state.init);

  useEffect(() => {
    initTheme();
  }, [initTheme]);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  useEffect(() => {
    const handleAuthExpired = (event: Event) => {
      const detail = (event as CustomEvent<{ message?: string }>).detail;
      signOut(detail?.message || sessionExpiredMessage);
    };

    window.addEventListener(authExpiredEvent, handleAuthExpired);
    return () => window.removeEventListener(authExpiredEvent, handleAuthExpired);
  }, [signOut]);

  useEffect(() => {
    const handleTokenRefresh = (event: Event) => {
      const detail = (event as CustomEvent<{ token?: string }>).detail;
      if (detail?.token) useAuthStore.setState({ token: detail.token });
    };
    window.addEventListener(authTokenRefreshedEvent, handleTokenRefresh);
    return () => window.removeEventListener(authTokenRefreshedEvent, handleTokenRefresh);
  }, []);

  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route
            path="/datasets/:datasetId/annotate"
            element={
              <ProtectedRoute>
                <DatasetAnnotatePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route path="models" element={<ModelManagementPage />} />
            <Route path="trainers" element={<TrainerFleetPage />} />
            <Route index element={<DatasetListPage />} />
            <Route path="datasets/new" element={<DatasetCreatePage />} />
            <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
            <Route path="datasets/:datasetId/generate" element={<GenerationTaskPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default function App() {
  const resolved = useThemeStore((state) => state.resolved);
  const antTheme = useMemo(() => getAntTheme(resolved), [resolved]);

  return (
    <ConfigProvider theme={antTheme}>
      <AntApp>
        <AppContent />
      </AntApp>
    </ConfigProvider>
  );
}
