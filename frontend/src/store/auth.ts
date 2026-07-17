import { create } from "zustand";

import { getMe, login, logout, refreshSession } from "../api/auth";
import type { User } from "../lib/types";
import { clearLegacyToken } from "../lib/session";
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
  token: null,
  user: null,
  isLoading: false,
  error: null,
  async hydrate() {
    clearLegacyToken();
    set({ isLoading: true, error: null });
    try {
      const session = await refreshSession();
      const token = session.token;
      const data = await getMe(token);
      set({ user: data.user, isLoading: false, token });
    } catch (error) {
      useModelProfilesStore.getState().clear();
      set({ token: null, user: null, isLoading: false, error: null });
    }
  },
  async signIn(username, password) {
    set({ isLoading: true, error: null });
    try {
      const data = await login(username, password);
      set({ token: data.token, user: data.user, isLoading: false });
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
    }
  },
  signOut(message = null) {
    void logout().catch(() => undefined);
    useModelProfilesStore.getState().clear();
    set({ token: null, user: null, error: message });
  },
}));
