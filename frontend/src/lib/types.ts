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
  image_count: number;
  distance: "close" | "mid" | "far";
  angle: "front" | "side" | "top" | "bottom" | "random";
  lighting: string[];
  background: string[];
  aspect_ratio: "1:1" | "4:3" | "3:4" | "16:9" | "9:16";
  format: "jpg" | "png";
  style: "realistic" | "illustration" | "sketch" | "3d" | "cartoon";
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

export type TaskImage = {
  id: string;
  ordinal: number;
  status: string;
  latencyMs: number;
  seed: number;
  promptText: string;
  diversityVars: Record<string, string>;
  previewSvg: string;
  selected: boolean;
  annotationStatus: string;
  confidenceScore?: number;
  source: string;
  detections: Array<{
    category: string;
    confidence: number;
    bbox: [number, number, number, number];
  }>;
};

export type TaskExport = {
  id: string;
  version: number;
  status: string;
  exportFormat: string;
  downloadUrl: string;
  summary: Record<string, unknown>;
  createdAt: string;
};

export type Task = {
  id: string;
  subject: string;
  categories: string[];
  imageCount: number;
  sampleCount: number;
  status: string;
  progressPercent: number;
  imagesGenerated: number;
  selectedCount: number;
  estimatedCost: number;
  spentCost: number;
  apiProvider: string;
  startedAt?: string | null;
  completedAt?: string | null;
  createdAt?: string;
  updatedAt?: string;
  config: TaskConfig & {
    augmentation?: {
      multiplier: number;
      methods: AugmentationMethod[];
      settings?: AugmentationSettingsPatch;
      sourceCount: number;
      estimatedAddedImages: number;
      simulatedOutput: number;
      totalImagesToCreate: number;
      completedImages: number;
      progressPercent: number;
      status?: "running" | "completed" | "failed";
      startedAt?: string;
      completedAt?: string;
      updatedAt?: string;
    };
    annotation?: Record<string, unknown>;
    runtime?: Record<string, unknown>;
  };
  prompt: PromptPreview;
  images: TaskImage[];
  exports: TaskExport[];
};

export type User = {
  id: string;
  username: string;
  plan: string;
};

export type DashboardSummary = {
  totalTasks: number;
  runningTasks: number;
  completedTasks: number;
  draftTasks: number;
  totalImages: number;
  avgCompletionMinutes: number;
  successRate: number;
  costToDate: number;
};
