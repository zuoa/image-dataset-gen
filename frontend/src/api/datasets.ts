import { apiRequest, apiRequestFormData } from "./client";
import type {
  AugmentationMethod,
  AugmentationSettings,
  Dataset,
  DatasetSummary,
  DatasetTask,
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
  return apiRequest<{ datasets: Dataset[]; summary: DatasetSummary }>("/datasets", { token });
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

export function getDataset(datasetId: string, token: string) {
  return apiRequest<{ dataset: Dataset }>(`/datasets/${datasetId}`, { token });
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
    frameInterval: number;
    outputFormat: "jpg" | "png";
    jpegQuality: number;
    filenamePrefix: string;
  },
) {
  const body = new FormData();
  body.append("video", video);
  body.append("frame_interval", String(settings.frameInterval));
  body.append("output_format", settings.outputFormat);
  body.append("jpeg_quality", String(settings.jpegQuality));
  body.append("filename_prefix", settings.filenamePrefix);
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
    imageSize: number;
  },
) {
  const body = new FormData();
  body.append("image", payload.image);
  body.append("confidence_threshold", String(payload.confidenceThreshold));
  body.append("image_size", String(payload.imageSize));
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
    | { mode: "all" | "none" | "invert"; image_ids?: string[] }
    | { mode: "single"; image_id: string; selected: boolean },
) {
  return apiRequest<{ dataset: Dataset }>(`/datasets/${datasetId}/selection`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });
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
  return apiRequest<{ dataset: Dataset }>(`/datasets/${datasetId}/images/${imageId}/annotations`, {
    method: "PATCH",
    token,
    body: JSON.stringify({ detections }),
  });
}
