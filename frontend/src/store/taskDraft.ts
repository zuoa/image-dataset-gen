import { create } from "zustand";

import { defaultTaskConfig } from "../lib/constants";
import type { TaskConfig } from "../lib/types";

type DraftState = {
  draft: TaskConfig;
  taskId: string | null;
  setDraft: (update: Partial<TaskConfig>) => void;
  replaceDraft: (next: TaskConfig) => void;
  setTaskId: (taskId: string | null) => void;
  resetDraft: () => void;
};

const storageKey = "image-dataset-gen-draft";
const savedDraft = localStorage.getItem(storageKey);

export const useTaskDraftStore = create<DraftState>((set) => ({
  draft: savedDraft ? { ...defaultTaskConfig, ...JSON.parse(savedDraft) } : defaultTaskConfig,
  taskId: null,
  setDraft(update) {
    set((state) => {
      const next = { ...state.draft, ...update };
      localStorage.setItem(storageKey, JSON.stringify(next));
      return { draft: next };
    });
  },
  replaceDraft(next) {
    localStorage.setItem(storageKey, JSON.stringify(next));
    set({ draft: next });
  },
  setTaskId(taskId) {
    set({ taskId });
  },
  resetDraft() {
    localStorage.removeItem(storageKey);
    set({ draft: defaultTaskConfig, taskId: null });
  },
}));
