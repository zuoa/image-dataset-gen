import type { ThemeConfig } from "antd";
import { theme as antTheme } from "antd";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "dataset-forge-theme";

export const graphitePalette = {
  ink: "#17191c",
  graphite: "#34383e",
  steel: "#626871",
  muted: "#8a9098",
  border: "#d8dadd",
  mist: "#f3f4f5",
  paper: "#ffffff",
  darkCanvas: "#0d0f11",
  darkSurface: "#15171a",
  darkElevated: "#1b1e22",
  darkBorder: "#303338",
} as const;

const semanticPalette = {
  success: "#4f7a69",
  warning: "#96713b",
  error: "#b65050",
} as const;

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
  const colorPrimary = isDark ? "#717780" : graphitePalette.graphite;
  const colorPrimaryHover = isDark ? "#888e97" : "#4a4f57";
  const colorPrimaryActive = isDark ? "#5d626a" : "#25282d";
  const colorBgLayout = isDark
    ? graphitePalette.darkCanvas
    : graphitePalette.mist;
  const colorBgContainer = isDark
    ? graphitePalette.darkSurface
    : graphitePalette.paper;
  const colorBgElevated = isDark
    ? graphitePalette.darkElevated
    : graphitePalette.paper;
  const colorBorder = isDark
    ? graphitePalette.darkBorder
    : graphitePalette.border;
  const colorBorderSecondary = isDark ? "#25282d" : "#e6e7e9";
  const colorText = isDark ? "#f4f4f5" : graphitePalette.ink;
  const colorTextSecondary = isDark ? "#a7abb2" : "#5d6269";
  const colorFillAlter = isDark ? "#1b1e22" : "#f5f6f7";
  const colorItemActive = isDark ? "#292d32" : "#e8eaec";

  return {
    algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    cssVar: {
      prefix: "df",
      key: "dataset-forge",
    },
    token: {
      fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      fontFamilyCode: "'IBM Plex Mono', monospace",
      borderRadius: 8,
      borderRadiusLG: 10,
      borderRadiusSM: 6,
      borderRadiusXS: 4,
      controlHeight: 36,
      controlHeightSM: 28,
      colorPrimary,
      colorPrimaryHover,
      colorPrimaryActive,
      colorPrimaryBg: isDark ? "#24272b" : "#f0f1f2",
      colorPrimaryBgHover: isDark ? "#2b2f34" : "#e5e7e9",
      colorPrimaryBorder: isDark ? "#484d54" : "#c4c7cc",
      colorPrimaryBorderHover: isDark ? "#5d626a" : "#a8acb2",
      colorPrimaryText: isDark ? "#c8cbd0" : graphitePalette.graphite,
      colorPrimaryTextHover: isDark ? "#eef0f2" : graphitePalette.ink,
      colorPrimaryTextActive: isDark ? "#aeb2b8" : "#25282d",
      colorInfo: colorPrimary,
      colorLink: isDark ? "#c8cbd0" : graphitePalette.graphite,
      colorLinkHover: isDark ? "#ffffff" : graphitePalette.ink,
      colorLinkActive: isDark ? "#aeb2b8" : "#25282d",
      colorSuccess: semanticPalette.success,
      colorWarning: semanticPalette.warning,
      colorError: semanticPalette.error,
      colorTextBase: colorText,
      colorText,
      colorTextSecondary,
      colorTextTertiary: isDark ? "#858b93" : "#737981",
      colorTextQuaternary: isDark ? "#646a72" : "#9a9fa6",
      colorBgBase: colorBgContainer,
      colorBgLayout,
      colorBgContainer,
      colorBgElevated,
      colorBgSpotlight: isDark ? "#2a2e33" : "#272a2f",
      colorBorder,
      colorBorderSecondary,
      colorFillAlter,
      colorFillContent: isDark ? "#22252a" : "#eef0f1",
      colorFillContentHover: isDark ? "#292d32" : "#e5e7e9",
      colorBgTextHover: isDark ? "rgba(255,255,255,0.08)" : "rgba(23,25,28,0.06)",
      colorBgTextActive: isDark ? "rgba(255,255,255,0.12)" : "rgba(23,25,28,0.1)",
      controlItemBgHover: isDark ? "#22252a" : "#eef0f1",
      controlItemBgActive: colorItemActive,
      controlItemBgActiveHover: isDark ? "#30343a" : "#dfe1e4",
      controlOutline: isDark
        ? "rgba(174,178,184,0.24)"
        : "rgba(52,56,62,0.18)",
      boxShadow: isDark
        ? "0 10px 30px rgba(0,0,0,0.28)"
        : "0 10px 30px rgba(23,25,28,0.08)",
      boxShadowSecondary: isDark
        ? "0 16px 48px rgba(0,0,0,0.38)"
        : "0 16px 48px rgba(23,25,28,0.12)",
    },
    components: {
      Layout: {
        bodyBg: "transparent",
        headerBg: "transparent",
        siderBg: "transparent",
      },
      Card: {
        borderRadiusLG: 10,
        headerBg: colorBgContainer,
        actionsBg: colorBgContainer,
      },
      Modal: {
        borderRadiusLG: 10,
        headerBg: colorBgElevated,
        contentBg: colorBgElevated,
        footerBg: colorBgElevated,
      },
      Drawer: {
        borderRadiusLG: 10,
        colorBgElevated,
      },
      Button: {
        borderRadius: 8,
        fontWeight: 500,
        defaultBg: colorBgContainer,
        defaultColor: colorText,
        defaultBorderColor: colorBorder,
        defaultHoverBg: isDark ? "#1d2024" : "#f7f7f8",
        defaultHoverColor: colorPrimaryHover,
        defaultHoverBorderColor: isDark ? "#555a62" : "#9da2a9",
        defaultActiveBg: colorFillAlter,
        defaultActiveColor: colorPrimaryActive,
        defaultActiveBorderColor: colorPrimaryActive,
        primaryShadow: "none",
        defaultShadow: "none",
        dangerShadow: "none",
      },
      Input: {
        borderRadius: 8,
        activeBorderColor: colorPrimary,
        hoverBorderColor: isDark ? "#555a62" : "#9da2a9",
        activeShadow: isDark
          ? "0 0 0 2px rgba(113,119,128,0.18)"
          : "0 0 0 2px rgba(52,56,62,0.12)",
      },
      Select: {
        borderRadius: 8,
        optionSelectedBg: colorItemActive,
        optionSelectedColor: colorText,
        optionActiveBg: isDark ? "#22252a" : "#eef0f1",
        activeBorderColor: colorPrimary,
        hoverBorderColor: isDark ? "#555a62" : "#9da2a9",
        activeOutlineColor: isDark
          ? "rgba(113,119,128,0.18)"
          : "rgba(52,56,62,0.12)",
      },
      Menu: {
        itemSelectedBg: colorItemActive,
        itemSelectedColor: colorText,
        itemHoverBg: isDark ? "#22252a" : "#eef0f1",
        itemHoverColor: colorText,
        itemActiveBg: isDark ? "#30343a" : "#dfe1e4",
      },
      Segmented: {
        trackBg: isDark ? "#1b1e22" : "#eef0f1",
        itemSelectedBg: isDark ? "#34383e" : "#ffffff",
        itemSelectedColor: colorText,
        itemHoverBg: isDark ? "#292d32" : "#e4e6e8",
        itemHoverColor: colorText,
      },
      Tabs: {
        inkBarColor: colorPrimary,
        itemSelectedColor: colorText,
        itemActiveColor: colorPrimaryActive,
        itemHoverColor: colorPrimaryHover,
      },
      Table: {
        headerBg: colorFillAlter,
        headerColor: colorTextSecondary,
        headerSortActiveBg: colorItemActive,
        headerSortHoverBg: isDark ? "#30343a" : "#dfe1e4",
        rowHoverBg: isDark ? "#1d2024" : "#f7f7f8",
        rowSelectedBg: colorItemActive,
        rowSelectedHoverBg: isDark ? "#30343a" : "#dfe1e4",
        borderColor: colorBorderSecondary,
      },
      Tag: {
        defaultBg: colorFillAlter,
        defaultColor: colorTextSecondary,
      },
      Progress: {
        defaultColor: colorPrimary,
        remainingColor: isDark ? "#292d32" : "#e4e6e8",
      },
    },
  };
}
