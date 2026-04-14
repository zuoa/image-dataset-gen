import { create } from "zustand";

import { getMe, login } from "../api/auth";
import type { User } from "../lib/types";
import { tokenStorageKey } from "../lib/session";
import { useModelProfilesStore } from "./modelProfiles";

type AuthState = {
  token: string | null;
  user: User | null;
  isLoading: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  signIn: (username: string, password: string) => Promise<void>;
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
      const message = (error as Error).message;
      const hasToken = Boolean(localStorage.getItem(tokenStorageKey));

      // Only clear auth state when the token was actually invalidated.
      // Transient refresh-time failures should not force a logout.
      if (!hasToken) {
        useModelProfilesStore.getState().clear();
        set({ token: null, user: null, isLoading: false, error: message });
        return;
      }

      set({ token, user: null, isLoading: false, error: message });
    }
  },
  async signIn(username, password) {
    set({ isLoading: true, error: null });
    try {
      const data = await login(username, password);
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
