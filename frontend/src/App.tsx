import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { authExpiredEvent, sessionExpiredMessage } from "./lib/session";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ModelManagementPage } from "./pages/ModelManagementPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { TaskWizardPage } from "./pages/TaskWizardPage";
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
          <Route index element={<DashboardPage />} />
          <Route path="models" element={<ModelManagementPage />} />
          <Route path="tasks/new" element={<TaskWizardPage />} />
          <Route path="tasks/:taskId" element={<TaskDetailPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
