import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { authExpiredEvent, sessionExpiredMessage } from "./lib/session";
import { AuthPage } from "./pages/AuthPage";
import { DatasetCreatePage } from "./pages/DatasetCreatePage";
import { DatasetDetailPage } from "./pages/DatasetDetailPage";
import { DatasetListPage } from "./pages/DatasetListPage";
import { GenerationTaskPage } from "./pages/GenerationTaskPage";
import { ModelManagementPage } from "./pages/ModelManagementPage";
import { useAuthStore } from "./store/auth";
import { useThemeStore } from "./store/theme";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token);
  const isLoading = useAuthStore((state) => state.isLoading);
  if (isLoading) {
    return <div className="flex min-h-screen items-center justify-center bg-white text-neutral-500 dark:bg-neutral-950 dark:text-neutral-400">Loading...</div>;
  }
  return token ? <>{children}</> : <Navigate to="/auth" replace />;
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

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route path="models" element={<ModelManagementPage />} />
          <Route index element={<DatasetListPage />} />
          <Route path="datasets/new" element={<DatasetCreatePage />} />
          <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
          <Route path="datasets/:datasetId/generate" element={<GenerationTaskPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
