export type ProviderId = "gemini" | "jimeng" | "stability" | "custom";
export type ModelProfileType = "image" | "llm";
export type AugmentationMethod =
  | "flip"
  | "rotate"
  | "crop"
  | "color_jitter"
  | "blur"
  | "noise"
  | "occlusion"
  | "perspective";

export type AugmentationSettings = {
  flip: { mode: "random" | "horizontal" | "vertical" };
  rotate: { max_angle: number };
  crop: { min_scale: number; max_scale: number };
  color_jitter: { strength: number };
  blur: { max_radius: number };
  noise: { max_sigma: number };
  occlusion: { min_ratio: number; max_ratio: number };
  perspective: { max_warp: number };
};

export type AugmentationSettingsPatch = {
  [K in keyof AugmentationSettings]?: Partial<AugmentationSettings[K]>;
};

export type TaskConfig = {
  model_profile_id?: string;
  llm_profile_id?: string;
  subject: string;
  categories: string[];
  cv_task?: "detection" | "segmentation" | "classification" | "instance_segmentation";
  image_count: number;
  distance: "close" | "mid" | "far";
  angle: "front" | "side" | "top" | "bottom" | "random";
  lighting: string[];
  background: string[];
  aspect_ratio: "1:1" | "4:3" | "3:4" | "16:9" | "9:16";
  format: "jpg" | "png";
  style: "realistic" | "illustration" | "sketch" | "3d" | "cartoon" | "surveillance";
  api_provider: ProviderId;
  api_key: string;
  concurrency: number;
  batch_size: number;
  budget_limit?: number | null;
  extra_desc?: string;
  provider_model?: string;
  jimeng_watermark?: boolean;
  llm_enhanced?: boolean;
  is_manual_edited?: boolean;
  manual_prompt?: string;
};

export type ProviderInfo = {
  id: ProviderId;
  name: string;
  latency: string;
  recommendConcurrency: number;
  unitPrice: number;
  supportsStrictMode: boolean;
  promptLanguage: string;
  defaultModel: string;
  models: string[];
  sizeHint: string;
  notes: string[];
};

export type ModelProfile = {
  id: string;
  profileType: ModelProfileType;
  name: string;
  providerId: string;
  baseUrl?: string | null;
  model: string;
  apiKey: string;
  concurrency: number;
  batchSize: number;
  jimengWatermark: boolean;
  notes?: string;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type PromptPreview = {
  positive_prompt: string;
  negative_prompt: string;
  variants: Array<{
    seed: number;
    prompt: string;
    diversity_vars: Record<string, string>;
  }>;
  language: string;
  estimated_cost: number;
  token_safe: boolean;
};

export type SubjectAssistSuggestion = {
  categories: string[];
  extra_desc: string;
};

export type DatasetTask = {
  id: string;
  datasetId: string;
  taskType: "generation" | "import" | "augmentation" | string;
  taskName: string;
  subject: string;
  categories: string[];
  imageCount: number;
  imagesGenerated: number;
  selectedCount: number;
  progressPercent: number;
  status: string;
  estimatedCost: number;
  spentCost: number;
  apiProvider: string;
  config: Partial<TaskConfig> & {
    source?: "zip" | "video" | "roboflow" | string;
    sourcePath?: string;
    video?: {
      filename: string;
      frameInterval: number;
      outputFormat: "jpg" | "png";
      jpegQuality: number;
      filenamePrefix: string;
      targetSize?: "original" | "1080p" | "720p" | "640";
      targetMaxDimension?: number | null;
      totalFrames?: number;
      expectedFrames?: number;
      extractedFrames?: number;
      progressPercent?: number;
      status?: "running" | "completed" | "failed";
      error?: string;
      startedAt?: string;
      completedAt?: string;
      updatedAt?: string;
    };
    augmentation?: {
      multiplier: number;
      methods: AugmentationMethod[];
      settings?: AugmentationSettingsPatch;
      sourceCount: number;
      estimatedAddedImages: number;
      totalImagesToCreate: number;
      completedImages: number;
      progressPercent: number;
      status?: "running" | "completed" | "failed";
      startedAt?: string;
      completedAt?: string;
      updatedAt?: string;
    };
    runtime?: Record<string, unknown>;
  };
  prompt: PromptPreview;
  runtime: Record<string, unknown>;
  sourceImageIds: string[];
  createdAt?: string | null;
  updatedAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
};

export type DatasetImage = {
  id: string;
  datasetId: string;
  sourceTaskId?: string | null;
  sourceType: string;
  sourceOrdinal: number;
  ordinal: number;
  status: string;
  latencyMs: number;
  seed: number;
  promptText: string;
  diversityVars: Record<string, string>;
  previewSvg: string;
  selected: boolean;
  annotationStatus: string;
  confidenceScore?: number | null;
  source: string;
  detections: Array<{
    category: string;
    confidence: number;
    bbox: [number, number, number, number];
  }>;
};

export type DatasetExport = {
  id: string;
  version: number;
  status: string;
  exportFormat: string;
  downloadUrl: string;
  summary: Record<string, unknown>;
  createdAt: string;
};

export type TrainingArtifact = {
  id: string;
  type: string;
  filename: string;
  sizeBytes: number;
  downloadUrl: string;
  createdAt?: string | null;
};

export type TrainingJob = {
  id: string;
  datasetId: string;
  exportId: string;
  workerId?: string | null;
  status: "queued" | "assigned" | "preparing" | "running" | "uploading" | "completed" | "failed" | string;
  progressPercent: number;
  config: {
    framework: "yolov8" | string;
    task: "detect" | string;
    model: string;
    epochs: number;
    imageSize: number;
    batchSize: number;
    patience: number;
    dropout: number;
    mixup: number;
    weightDecay: number;
    classes: number[];
    device?: string;
  };
  metrics: Record<string, number | string | null>;
  error: string;
  artifacts: TrainingArtifact[];
  export?: DatasetExport | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
};

export type TrainingInferenceResult = {
  artifact: {
    id: string;
    type: string;
    filename: string;
  };
  image: {
    width: number;
    height: number;
  };
  confidenceThreshold: number;
  imageSize: number;
  detections: Array<{
    category: string;
    classId: number;
    confidence: number;
    bbox: [number, number, number, number];
  }>;
  annotatedImage: string;
};

export type TrainingInferenceTest = {
  id: string;
  trainingJobId: string;
  datasetId: string;
  artifact: {
    id: string;
    type: string;
    filename: string;
  };
  workerId?: string | null;
  status: "queued" | "assigned" | "running" | "completed" | "failed" | string;
  confidenceThreshold: number;
  imageSize: number;
  image: {
    filename: string;
    mimeType?: string;
    width: number;
    height: number;
  };
  detections: TrainingInferenceResult["detections"];
  error: string;
  result?: TrainingInferenceResult | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
};

export type Dataset = {
  id: string;
  name: string;
  description: string;
  categories: string[];
  status: string;
  imageCount: number;
  selectedCount: number;
  taskCount: number;
  spentCost: number;
  annotation: Record<string, unknown>;
  createdAt?: string | null;
  updatedAt?: string | null;
  images: DatasetImage[];
  tasks: DatasetTask[];
  exports: DatasetExport[];
  latestTask?: DatasetTask | null;
};

export type DatasetSummary = {
  totalDatasets: number;
  activeDatasets: number;
  totalTasks: number;
  totalImages: number;
  selectedImages: number;
  costToDate: number;
};

export type User = {
  id: string;
  username: string;
  plan: string;
};
