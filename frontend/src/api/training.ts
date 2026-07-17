import { apiRequest } from "./client";
import type { TrainingWorkerList } from "../lib/types";

export function listTrainingWorkers(token: string, signal?: AbortSignal) {
  return apiRequest<TrainingWorkerList>("/training/workers", { token, signal });
}
