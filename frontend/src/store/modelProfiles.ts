import { create } from "zustand";

import {
  createModelProfile,
  deleteModelProfile,
  getModelProfiles,
  updateModelProfile,
} from "../api/system";
import type { ModelProfile } from "../lib/types";

type ModelProfileState = {
  profiles: ModelProfile[];
  isLoading: boolean;
  isLoaded: boolean;
  error: string | null;
  fetchProfiles: (token: string) => Promise<void>;
  saveProfile: (profile: ModelProfile, token: string) => Promise<ModelProfile>;
  removeProfile: (id: string, token: string) => Promise<void>;
  clear: () => void;
};

export const useModelProfilesStore = create<ModelProfileState>((set, get) => ({
  profiles: [],
  isLoading: false,
  isLoaded: false,
  error: null,
  async fetchProfiles(token) {
    if (!token) return;
    set({ isLoading: true, error: null });
    try {
      const data = await getModelProfiles(token);
      set({ profiles: data.profiles, isLoading: false, isLoaded: true });
    } catch (error) {
      set({ isLoading: false, isLoaded: true, error: (error as Error).message });
    }
  },
  async saveProfile(profile, token) {
    set({ isLoading: true, error: null });
    try {
      const response = get().profiles.some((item) => item.id === profile.id)
        ? await updateModelProfile(profile.id, profile, token)
        : await createModelProfile(profile, token);
      const saved = response.profile;
      set((state) => ({
        profiles: state.profiles.some((item) => item.id === saved.id)
          ? state.profiles.map((item) => (item.id === saved.id ? saved : item))
          : [...state.profiles, saved],
        isLoading: false,
        isLoaded: true,
      }));
      return saved;
    } catch (error) {
      set({ isLoading: false, error: (error as Error).message });
      throw error;
    }
  },
  async removeProfile(id, token) {
    set({ isLoading: true, error: null });
    try {
      await deleteModelProfile(id, token);
      set((state) => ({
        profiles: state.profiles.filter((profile) => profile.id !== id),
        isLoading: false,
        isLoaded: true,
      }));
    } catch (error) {
      set({ isLoading: false, error: (error as Error).message });
      throw error;
    }
  },
  clear() {
    set({ profiles: [], isLoading: false, isLoaded: false, error: null });
  },
}));
