import { create } from "zustand";

import {
  applyThemeClass,
  readSavedThemeMode,
  resolveThemeMode,
  saveThemeMode,
  type ThemeMode,
} from "../lib/theme";

interface ThemeState {
  mode: ThemeMode;
  resolved: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
  init: () => void;
}

function apply(mode: ThemeMode): "light" | "dark" {
  const resolved = resolveThemeMode(mode);
  applyThemeClass(resolved);
  return resolved;
}

export const useThemeStore = create<ThemeState>((set) => ({
  mode: "system",
  resolved: "light",
  setMode: (mode) => {
    saveThemeMode(mode);
    const resolved = apply(mode);
    set({ mode, resolved });
  },
  toggle: () => {
    set((state) => {
      const nextMode: ThemeMode = state.resolved === "dark" ? "light" : "dark";
      saveThemeMode(nextMode);
      const resolved = apply(nextMode);
      return { mode: nextMode, resolved };
    });
  },
  init: () => {
    const mode = readSavedThemeMode();
    const resolved = apply(mode);
    set({ mode, resolved });

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      set((state) => {
        if (state.mode !== "system") return state;
        const resolved = resolveThemeMode("system");
        applyThemeClass(resolved);
        return { resolved };
      });
    };
    media.addEventListener("change", handleChange);
  },
}));
