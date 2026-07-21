import { apiRequest } from "./client";
import type { TrainingModelCatalog, TrainingWorkerList } from "../lib/types";

export function listTrainingWorkers(token: string, signal?: AbortSignal) {
  return apiRequest<TrainingWorkerList>("/training/workers", { token, signal });
}

export function listTrainingModels(token: string, signal?: AbortSignal) {
  return apiRequest<TrainingModelCatalog>("/training/models", { token, signal });
}
