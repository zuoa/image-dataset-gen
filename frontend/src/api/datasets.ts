import { apiRequest, apiRequestFormData } from "./client";
import type {
  AugmentationMethod,
  AugmentationSettings,
  Dataset,
  DatasetImage,
  DatasetListItem,
  DatasetSummary,
  DatasetTask,
  ImageFilter,
  PromptPreview,
  TaskConfig,
  TrainingInferenceTest,
  TrainingJob,
} from "../lib/types";

function serializeTaskConfig(config: TaskConfig | Partial<TaskConfig>) {
  const { model_profile_id, llm_profile_id, task_name, quality, size, ...payload } = config as typeof config & {
    task_name?: string;
    quality?: number;
    size?: string;
  };
  return payload;
}

export function listDatasets(token: string) {
  return apiRequest<{ datasets: DatasetListItem[]; summary: DatasetSummary }>("/datasets", { token });
}

export function createDataset(
  payload: {
    name: string;
    categories: string[];
    description?: string;
  },
  token: string,
) {
  return apiRequest<{ dataset: Dataset }>("/datasets", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function getDataset(
  datasetId: string,
  token: string,
  options?: { offset?: number; limit?: number; filter?: ImageFilter },
) {
  const params = new URLSearchParams();
  if (options?.offset !== undefined) params.set("images_offset", String(options.offset));
  if (options?.limit !== undefined) params.set("images_limit", String(options.limit));
  if (options?.filter?.class) params.set("filter_class", options.filter.class);
  if (options?.filter?.split) params.set("filter_split", options.filter.split);
  if (options?.filter?.annotation) params.set("filter_annotation", options.filter.annotation);
  const query = params.toString();
  return apiRequest<{ dataset: Dataset }>(
    `/datasets/${datasetId}${query ? `?${query}` : ""}`,
    { token },
  );
}

export function buildImageFilter(filter: ImageFilter | null): ImageFilter | undefined {
  if (!filter) return undefined;
  if (!filter.class && !filter.split && !filter.annotation) return undefined;
  return filter;
}

export function updateDataset(
  datasetId: string,
  payload: Partial<{
    name: string;
    categories: string[];
    description: string;
  }>,
  token: string,
) {
  return apiRequest<{ dataset: Dataset }>(`/datasets/${datasetId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });
}

export function previewGenerationPrompt(config: TaskConfig, token: string) {
  return apiRequest<PromptPreview>("/datasets/generation/prompt-preview", {
    method: "POST",
    token,
    body: JSON.stringify(serializeTaskConfig(config)),
  });
}

export function assistDatasetSubject(
  token: string,
  payload: {
    subject: string;
    llmProfileId: string;
  },
) {
  return apiRequest<{ categories: string[]; extra_desc: string }>("/datasets/assist-subject", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function createGenerationTask(datasetId: string, config: TaskConfig, token: string) {
  return apiRequest<{ task: unknown; dataset: Dataset }>(`/datasets/${datasetId}/tasks/generation`, {
    method: "POST",
    token,
    body: JSON.stringify(serializeTaskConfig(config)),
  });
}

export function startDatasetTask(datasetId: string, taskId: string, token: string) {
  return apiRequest<{ task: unknown; dataset: Dataset }>(`/datasets/${datasetId}/tasks/${taskId}/start`, {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export function retryDatasetTask(datasetId: string, taskId: string, token: string) {
  return apiRequest<{ task: unknown; dataset: Dataset }>(`/datasets/${datasetId}/tasks/${taskId}/retry`, {
    method: "POST",
    token,
    body: JSON.stringify({}),
  });
}

export function importDatasetImagesArchive(datasetId: string, token: string, archive: File) {
  const body = new FormData();
  body.append("archive", archive);
  return apiRequestFormData<{ summary: Record<string, unknown>; dataset: Dataset }>(
    `/datasets/${datasetId}/tasks/import`,
    body,
    { token, method: "POST" },
  );
}

export function importDatasetVideo(
  datasetId: string,
  token: string,
  video: File,
  settings: {
    frameIntervalMode: "frames" | "seconds";
    frameInterval: number;
    frameIntervalSeconds: number;
    outputFormat: "jpg" | "png";
    jpegQuality: number;
    filenamePrefix: string;
    targetSize: "original" | "1080p" | "720p" | "640";
  },
) {
  const body = new FormData();
  body.append("video", video);
  body.append("frame_interval_mode", settings.frameIntervalMode);
  body.append("frame_interval", String(settings.frameInterval));
  body.append("frame_interval_seconds", String(settings.frameIntervalSeconds));
  body.append("output_format", settings.outputFormat);
  body.append("jpeg_quality", String(settings.jpegQuality));
  body.append("filename_prefix", settings.filenamePrefix);
  body.append("target_size", settings.targetSize);
  return apiRequestFormData<{ summary: Record<string, unknown>; task: DatasetTask; dataset: Dataset }>(
    `/datasets/${datasetId}/tasks/import/video`,
    body,
    { token, method: "POST" },
  );
}

export function importDatasetFromRoboflow(
  datasetId: string,
  token: string,
  payload: {
    apiKey: string;
    workspace: string;
    project: string;
    version: string;
    format?: "yolov8";
  },
) {
  return apiRequest<{ summary: Record<string, unknown>; dataset: Dataset }>(
    `/datasets/${datasetId}/tasks/import/roboflow`,
    {
      method: "POST",
      token,
      body: JSON.stringify({ ...payload, format: payload.format ?? "yolov8" }),
    },
  );
}

export function augmentDataset(
  datasetId: string,
  token: string,
  multiplier: number,
  methods: AugmentationMethod[],
  settings: AugmentationSettings,
) {
  return apiRequest<{ task: unknown; dataset: Dataset }>(`/datasets/${datasetId}/tasks/augmentation`, {
    method: "POST",
    token,
    body: JSON.stringify({ multiplier, augmentation_methods: methods, augmentation_settings: settings }),
  });
}

export function annotateDataset(datasetId: string, token: string, confidenceThreshold: number, skipAnnotated: boolean = false) {
  return apiRequest<{ summary: Record<string, unknown>; dataset: Dataset }>(`/datasets/${datasetId}/annotate`, {
    method: "POST",
    token,
    body: JSON.stringify({ confidence_threshold: confidenceThreshold, skip_annotated: skipAnnotated }),
  });
}

export function exportDataset(
  datasetId: string,
  token: string,
  exportFormat: "yolo" | "coco" | "voc" | "csv",
  imageFormat: "keep" | "jpg" | "png",
) {
  return apiRequest<{ export: Record<string, unknown>; dataset: Dataset }>(`/datasets/${datasetId}/export`, {
    method: "POST",
    token,
    body: JSON.stringify({ export_format: exportFormat, image_format: imageFormat }),
  });
}

export function listTrainingJobs(datasetId: string, token: string) {
  return apiRequest<{ jobs: TrainingJob[] }>(`/datasets/${datasetId}/training-jobs`, { token });
}

export function createTrainingJob(
  datasetId: string,
  token: string,
  payload: {
    model: string;
    epochs: number;
    image_size: number;
    batch_size: number;
    patience: number;
    dropout: number;
    mixup: number;
    weight_decay: number;
    classes: number[];
    device?: string;
  },
) {
  return apiRequest<{ job: TrainingJob; dataset: Dataset }>(`/datasets/${datasetId}/training-jobs`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function deleteTrainingJob(datasetId: string, jobId: string, token: string) {
  return apiRequest<{ deletedJobId: string; dataset: Dataset }>(`/datasets/${datasetId}/training-jobs/${jobId}`, {
    method: "DELETE",
    token,
  });
}

export function createTrainingInferenceTest(
  datasetId: string,
  jobId: string,
  token: string,
  payload: {
    image: File;
    artifactId?: string;
    confidenceThreshold: number;
  },
) {
  const body = new FormData();
  body.append("image", payload.image);
  body.append("confidence_threshold", String(payload.confidenceThreshold));
  if (payload.artifactId) {
    body.append("artifact_id", payload.artifactId);
  }
  return apiRequestFormData<{ test: TrainingInferenceTest }>(
    `/datasets/${datasetId}/training-jobs/${jobId}/test`,
    body,
    { token, method: "POST" },
  );
}

export function getTrainingInferenceTest(datasetId: string, jobId: string, testId: string, token: string) {
  return apiRequest<{ test: TrainingInferenceTest }>(
    `/datasets/${datasetId}/training-jobs/${jobId}/tests/${testId}`,
    { token },
  );
}

export function updateDatasetSelection(
  datasetId: string,
  token: string,
  payload:
    | { mode: "all" | "none" | "invert"; image_ids?: string[]; scope?: "unannotated_unretained" }
    | { mode: "single"; image_id: string; selected: boolean },
) {
  return apiRequest<{ dataset: Dataset }>(`/datasets/${datasetId}/selection`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });
}

export function deleteDatasetImage(datasetId: string, imageId: string, token: string) {
  return apiRequest<{ deletedImageIds: string[]; deletedCount: number; dataset: Dataset }>(
    `/datasets/${datasetId}/images/${imageId}`,
    {
      method: "DELETE",
      token,
    },
  );
}

export function deleteDatasetImages(datasetId: string, imageIds: string[], token: string) {
  return apiRequest<{ deletedImageIds: string[]; deletedCount: number; dataset: Dataset }>(
    `/datasets/${datasetId}/images`,
    {
      method: "DELETE",
      token,
      body: JSON.stringify({ image_ids: imageIds }),
    },
  );
}

export function updateDatasetImageAnnotations(
  datasetId: string,
  imageId: string,
  token: string,
  detections: Array<{
    category: string;
    confidence: number;
    bbox: [number, number, number, number];
  }>,
) {
  return apiRequest<{ dataset: Dataset; image: DatasetImage }>(
    `/datasets/${datasetId}/images/${imageId}/annotations`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify({ detections }),
    },
  );
}
