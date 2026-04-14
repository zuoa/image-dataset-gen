import { create } from "zustand";
import { persist } from "zustand/middleware";

type ThemeMode = "light" | "dark" | "system";

interface ThemeState {
  mode: ThemeMode;
  resolved: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
  init: () => void;
}

function applyTheme(resolved: "light" | "dark") {
  const root = document.documentElement;
  if (resolved === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

function resolve(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return mode;
}

let mediaListener: ((e: MediaQueryListEvent) => void) | null = null;

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: "system",
      resolved: "dark",
      setMode: (mode) => {
        const resolved = resolve(mode);
        applyTheme(resolved);
        set({ mode, resolved });
      },
      init: () => {
        const resolved = resolve(get().mode);
        applyTheme(resolved);
        set({ resolved });

        if (mediaListener) {
          window
            .matchMedia("(prefers-color-scheme: dark)")
            .removeEventListener("change", mediaListener);
        }

        mediaListener = (e: MediaQueryListEvent) => {
          if (get().mode === "system") {
            const next = e.matches ? "dark" : "light";
            applyTheme(next);
            set({ resolved: next });
          }
        };
        window
          .matchMedia("(prefers-color-scheme: dark)")
          .addEventListener("change", mediaListener);
      },
    }),
    {
      name: "dataset-gen-theme",
    },
  ),
);
