import { create } from "zustand";

import { getMe, login, register } from "../api/auth";
import type { User } from "../lib/types";
import { tokenStorageKey } from "../lib/session";
import { useModelProfilesStore } from "./modelProfiles";

type AuthState = {
  token: string | null;
  user: User | null;
  isLoading: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  signIn: (email: string, password: string, mode: "login" | "register") => Promise<void>;
  signOut: (message?: string | null) => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(tokenStorageKey),
  user: null,
  isLoading: false,
  error: null,
  async hydrate() {
    const token = localStorage.getItem(tokenStorageKey);
    if (!token) return;
    set({ isLoading: true, error: null, token });
    try {
      const data = await getMe(token);
      set({ user: data.user, isLoading: false, token });
    } catch (error) {
      localStorage.removeItem(tokenStorageKey);
      useModelProfilesStore.getState().clear();
      set({ token: null, user: null, isLoading: false, error: (error as Error).message });
    }
  },
  async signIn(email, password, mode) {
    set({ isLoading: true, error: null });
    try {
      const data =
        mode === "login" ? await login(email, password) : await register(email, password);
      localStorage.setItem(tokenStorageKey, data.token);
      set({ token: data.token, user: data.user, isLoading: false });
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
    }
  },
  signOut(message = null) {
    localStorage.removeItem(tokenStorageKey);
    useModelProfilesStore.getState().clear();
    set({ token: null, user: null, error: message });
  },
}));
