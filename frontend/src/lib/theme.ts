import type { ThemeConfig } from "antd";
import { theme as antTheme } from "antd";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "dataset-forge-theme";

export function resolveThemeMode(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") {
    if (typeof window === "undefined") return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return mode;
}

export function readSavedThemeMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  return "system";
}

export function saveThemeMode(mode: ThemeMode): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, mode);
}

export function applyThemeClass(resolved: "light" | "dark"): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (resolved === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
  root.style.colorScheme = resolved;
}

export function getAntTheme(resolved: "light" | "dark"): ThemeConfig {
  const isDark = resolved === "dark";
  return {
    algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    token: {
      fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      fontFamilyCode: "'IBM Plex Mono', monospace",
      borderRadius: 12,
      borderRadiusLG: 16,
      borderRadiusSM: 8,
      borderRadiusXS: 4,
      colorPrimary: "#2563eb",
      colorInfo: "#2563eb",
      colorSuccess: "#16a34a",
      colorWarning: "#d97706",
      colorError: "#dc2626",
      colorTextBase: isDark ? "#fafafa" : "#171717",
      colorBgBase: isDark ? "#0a0a0a" : "#ffffff",
    },
    components: {
      Layout: {
        bodyBg: "transparent",
        headerBg: "transparent",
        siderBg: "transparent",
      },
      Card: {
        borderRadiusLG: 16,
      },
      Modal: {
        borderRadiusLG: 16,
      },
      Drawer: {
        borderRadiusLG: 16,
      },
      Button: {
        borderRadius: 8,
      },
      Input: {
        borderRadius: 8,
      },
      Select: {
        borderRadius: 8,
      },
    },
  };
}
