import { apiRequest, apiRequestFormData } from "./client";
import type {
  AugmentationMethod,
  DashboardSummary,
  ModelProfile,
  PromptPreview,
  ProviderInfo,
  SubjectAssistSuggestion,
  Task,
  TaskConfig,
} from "../lib/types";

function serializeTaskConfig(config: TaskConfig | Partial<TaskConfig>) {
  const { model_profile_id, llm_profile_id, quality, size, ...payload } = config as typeof config & {
    quality?: number;
    size?: string;
  };
  return payload;
}

function serializeModelProfile(profile: ModelProfile) {
  return {
    profileType: profile.profileType,
    name: profile.name,
    providerId: profile.providerId,
    baseUrl: profile.baseUrl ?? "",
    model: profile.model,
    apiKey: profile.apiKey,
    concurrency: profile.concurrency,
    batchSize: profile.batchSize,
    jimengWatermark: profile.jimengWatermark,
    notes: profile.notes ?? "",
  };
}

export function getProviders() {
  return apiRequest<{
    providers: ProviderInfo[];
  }>("/system/providers");
}

export function getModelProfiles(token: string) {
  return apiRequest<{
    profiles: ModelProfile[];
  }>("/system/model-profiles", { token });
}

export function createModelProfile(profile: ModelProfile, token: string) {
  return apiRequest<{ profile: ModelProfile }>("/system/model-profiles", {
    method: "POST",
    token,
    body: JSON.stringify(serializeModelProfile(profile)),
  });
}

export function updateModelProfile(profileId: string, profile: ModelProfile, token: string) {
  return apiRequest<{ profile: ModelProfile }>(`/system/model-profiles/${profileId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(serializeModelProfile(profile)),
  });
}

export function deleteModelProfile(profileId: string, token: string) {
  return apiRequest<{ deleted: boolean; id: string }>(`/system/model-profiles/${profileId}`, {
    method: "DELETE",
    token,
  });
}

export function getDashboard(token: string) {
  return apiRequest<{ summary: DashboardSummary }>("/system/dashboard", { token });
}

export function previewPrompt(config: TaskConfig, token: string) {
  return apiRequest<PromptPreview>("/tasks/prompt-preview", {
    method: "POST",
    token,
    body: JSON.stringify(serializeTaskConfig(config)),
  });
}

export function assistSubject(
  token: string,
  payload: {
    subject: string;
    llmProfileId: string;
  },
) {
  return apiRequest<SubjectAssistSuggestion>("/tasks/assist-subject", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function listTasks(token: string) {
  return apiRequest<{ tasks: Task[]; summary: DashboardSummary }>("/tasks", { token });
}

export function createTask(config: TaskConfig, token: string) {
  return apiRequest<{ task: Task }>("/tasks", {
    method: "POST",
    token,
    body: JSON.stringify(serializeTaskConfig(config)),
  });
}

export function updateTask(taskId: string, config: Partial<TaskConfig>, token: string) {
  return apiRequest<{ task: Task }>(`/tasks/${taskId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(serializeTaskConfig(config)),
  });
}

export function startTask(taskId: string, token: string) {
  return apiRequest<{ task: Task }>(`/tasks/${taskId}/start`, {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export function retryTask(taskId: string, token: string) {
  return apiRequest<{ task: Task }>(`/tasks/${taskId}/retry`, {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export function getTask(taskId: string, token: string) {
  return apiRequest<{ task: Task }>(`/tasks/${taskId}`, { token });
}

export function augmentTask(
  taskId: string,
  token: string,
  multiplier: number,
  methods: AugmentationMethod[],
) {
  return apiRequest<{ summary: Record<string, unknown>; task: Task }>(`/tasks/${taskId}/augment`, {
    method: "POST",
    token,
    body: JSON.stringify({ multiplier, augmentation_methods: methods }),
  });
}

export function importTaskImagesArchive(taskId: string, token: string, archive: File) {
  const body = new FormData();
  body.append("archive", archive);
  return apiRequestFormData<{ summary: Record<string, unknown>; task: Task }>(
    `/tasks/${taskId}/import-images`,
    body,
    { token, method: "POST" },
  );
}

export function annotateTask(taskId: string, token: string, confidenceThreshold: number) {
  return apiRequest<{ summary: Record<string, unknown>; task: Task }>(`/tasks/${taskId}/annotate`, {
    method: "POST",
    token,
    body: JSON.stringify({ confidence_threshold: confidenceThreshold }),
  });
}

export function exportTask(
  taskId: string,
  token: string,
  exportFormat: "yolo" | "coco" | "voc" | "csv",
  imageFormat: "keep" | "jpg" | "png",
) {
  return apiRequest<{ export: Record<string, unknown>; task: Task }>(`/tasks/${taskId}/export`, {
    method: "POST",
    token,
    body: JSON.stringify({ export_format: exportFormat, image_format: imageFormat }),
  });
}

export function updateSelection(
  taskId: string,
  token: string,
  payload:
    | { mode: "all" | "none" | "invert" }
    | { mode: "single"; image_id: string; selected: boolean },
) {
  return apiRequest<{ task: Task }>(`/tasks/${taskId}/selection`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });
}

export function updateImageAnnotations(
  taskId: string,
  imageId: string,
  token: string,
  detections: Array<{
    category: string;
    confidence: number;
    bbox: [number, number, number, number];
  }>,
) {
  return apiRequest<{ task: Task }>(`/tasks/${taskId}/images/${imageId}/annotations`, {
    method: "PATCH",
    token,
    body: JSON.stringify({ detections }),
  });
}
