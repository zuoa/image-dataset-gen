import { create } from "zustand";

import { login, logout, refreshSession } from "../api/auth";
import type { User } from "../lib/types";
import { clearLegacyToken } from "../lib/session";
import { useModelProfilesStore } from "./modelProfiles";

type AuthState = {
  token: string | null;
  user: User | null;
  status: "checking" | "authenticated" | "anonymous";
  isSubmitting: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  signIn: (username: string, password: string, captchaId: string, captchaCode: string) => Promise<boolean>;
  signOut: (message?: string | null) => void;
};

let hydrationPromise: Promise<void> | null = null;

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  status: "checking",
  isSubmitting: false,
  error: null,
  hydrate() {
    if (hydrationPromise) return hydrationPromise;
    hydrationPromise = (async () => {
      clearLegacyToken();
      set({ status: "checking", error: null });
      try {
        const session = await refreshSession();
        set({ user: session.user, status: "authenticated", token: session.token });
      } catch (error) {
        useModelProfilesStore.getState().clear();
        set({ token: null, user: null, status: "anonymous", error: null });
      }
    })().finally(() => {
      hydrationPromise = null;
    });
    return hydrationPromise;
  },
  async signIn(username, password, captchaId, captchaCode) {
    set({ isSubmitting: true, error: null });
    try {
      const data = await login(username, password, captchaId, captchaCode);
      set({
        token: data.token,
        user: data.user,
        status: "authenticated",
        isSubmitting: false,
      });
      return true;
    } catch (error) {
      set({ error: (error as Error).message, isSubmitting: false });
      return false;
    }
  },
  signOut(message = null) {
    void logout().catch(() => undefined);
    useModelProfilesStore.getState().clear();
    set({
      token: null,
      user: null,
      status: "anonymous",
      isSubmitting: false,
      error: message,
    });
  },
}));
