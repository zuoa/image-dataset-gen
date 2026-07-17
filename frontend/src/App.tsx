import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { authExpiredEvent, authTokenRefreshedEvent, sessionExpiredMessage } from "./lib/session";
import { AuthPage } from "./pages/AuthPage";
import { DatasetAnnotatePage } from "./pages/DatasetAnnotatePage";
import { DatasetCreatePage } from "./pages/DatasetCreatePage";
import { DatasetDetailPage } from "./pages/DatasetDetailPage";
import { DatasetListPage } from "./pages/DatasetListPage";
import { GenerationTaskPage } from "./pages/GenerationTaskPage";
import { ModelManagementPage } from "./pages/ModelManagementPage";
import { TrainerFleetPage } from "./pages/TrainerFleetPage";
import { useAuthStore } from "./store/auth";
import { useThemeStore } from "./store/theme";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();
  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white text-sm text-neutral-500 dark:bg-neutral-950 dark:text-neutral-400">
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

export default function App() {
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
    </BrowserRouter>
  );
}
