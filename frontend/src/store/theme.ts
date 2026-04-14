import { create } from "zustand";

type ThemeMode = "light";

interface ThemeState {
  mode: ThemeMode;
  resolved: "light";
  setMode: (mode: ThemeMode) => void;
  init: () => void;
}

function applyTheme() {
  const root = document.documentElement;
  root.classList.remove("dark");
}

export const useThemeStore = create<ThemeState>((set) => ({
  mode: "light",
  resolved: "light",
  setMode: () => {
    applyTheme();
    set({ mode: "light", resolved: "light" });
  },
  init: () => {
    applyTheme();
    set({ mode: "light", resolved: "light" });
    window.localStorage.removeItem("dataset-gen-theme");
  },
}));
