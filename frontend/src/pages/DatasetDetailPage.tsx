import { useEffect, useRef, useState, type ChangeEvent, type MouseEvent as ReactMouseEvent } from "react";
import { CheckSquare, ChevronLeft, ChevronRight, ClipboardList, Cpu, Download, FileVideo, FlipHorizontal2, Layers, ListChecks, Loader, PencilRuler, Play, Sparkles, Square, Tag, Trash2, Upload, Wand2, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { downloadWithToken } from "../api/client";
import {
  createRoboflowConnection,
  deleteRoboflowConnection,
  listRoboflowConnections,
} from "../api/integrations";
import {
  annotateDataset,
  augmentDataset,
  createTrainingJob,
  deleteDatasetImage,
  deleteDatasetImages,
  deleteTrainingJob,
  exportDataset,
  getDataset,
  importDatasetFromRoboflow,
  importDatasetImagesArchive,
  importDatasetVideo,
  listTrainingJobs,
  retryDatasetTask,
  updateDatasetImageAnnotations,
  updateDatasetSelection,
} from "../api/datasets";
import type { ImageFilter, SamplePoolSource, SamplePoolSplit } from "../lib/types";
import { AuthImage } from "../components/AuthImage";
import { TrainingModelTestPanel } from "../components/TrainingModelTestPanel";
import { TrainingResultsPanel } from "../components/TrainingResultsPanel";
import { DatasetQualityPanel } from "../components/DatasetQualityPanel";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import { SectionCard } from "../components/ui/SectionCard";
import { segmentedButtonClasses, segmentedGroupClasses } from "../components/ui/segmentedStyles";
import {
  boxFromCorners,
  DEFAULT_BOX_SIZE,
  detectionStyle,
  detectionsEqual,
  fitImageViewport,
  minimumBoxSizeForImage,
  pointerToStage,
  type ImageViewport,
  type ResizeCorner,
} from "../lib/annotation";
import type { AugmentationMethod, AugmentationSettings, Dataset, DatasetImage, ExternalConnection, TrainingJob } from "../lib/types";
import { formatCurrency, formatDate } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const defaultAugmentationMethods: AugmentationMethod[] = ["flip", "color_jitter", "blur"];
const defaultAugmentationSettings: AugmentationSettings = {
  flip: { mode: "random" },
  rotate: { max_angle: 8 },
  crop: { min_scale: 0.82, max_scale: 0.94 },
  color_jitter: { strength: 0.18 },
  blur: { max_radius: 2.4 },
  noise: { max_sigma: 28 },
  occlusion: { min_ratio: 0.14, max_ratio: 0.28 },
  perspective: { max_warp: 0.08 },
};
const augmentationOptions: Array<{ value: AugmentationMethod; label: string }> = [
  { value: "flip", label: "翻转" },
  { value: "rotate", label: "旋转" },
  { value: "crop", label: "裁切" },
  { value: "color_jitter", label: "颜色抖动" },
  { value: "blur", label: "模糊" },
  { value: "noise", label: "噪声" },
  { value: "occlusion", label: "遮挡" },
  { value: "perspective", label: "透视" },
];
type ExportFormat = "yolo" | "coco" | "voc" | "csv";
const exportFormatOptions: Array<{ value: ExportFormat; label: string }> = [
  { value: "yolo", label: "YOLO" },
  { value: "coco", label: "COCO" },
  { value: "voc", label: "VOC" },
  { value: "csv", label: "CSV" },
];
type VideoOutputFormat = "jpg" | "png";
type VideoTargetSize = "original" | "1080p" | "720p" | "640";
type VideoFrameIntervalMode = "frames" | "seconds";
type ImportTab = "video" | "zip" | "roboflow";
const videoTargetSizeOptions: Array<{ value: VideoTargetSize; label: string }> = [
  { value: "original", label: "原图" },
  { value: "1080p", label: "1080p" },
  { value: "720p", label: "720p" },
  { value: "640", label: "640" },
];
const importTabOptions: Array<{ value: ImportTab; label: string; icon: typeof FileVideo }> = [
  { value: "video", label: "视频抽帧", icon: FileVideo },
  { value: "zip", label: "本地 ZIP", icon: Upload },
  { value: "roboflow", label: "Roboflow", icon: Download },
];
const activeTrainingStatuses = new Set(["queued", "assigned", "preparing", "running", "uploading"]);
const activeDatasetTaskStatuses = new Set(["running"]);
const activeDatasetExportStatuses = new Set(["pending", "running"]);
type SamplePoolSplitFilter = "" | SamplePoolSplit;
type SamplePoolAnnotationFilter = "" | "annotated" | "unannotated";
type SamplePoolSourceFilter = "" | SamplePoolSource;
const samplePoolSourceOptions: Array<{ value: SamplePoolSource; label: string }> = [
  { value: "generation", label: "AI 生成" },
  { value: "imported", label: "导入" },
  { value: "augmentation", label: "数据增强" },
];
const samplePoolSplitOptions: Array<{ value: SamplePoolSplit; label: string }> = [
  { value: "train", label: "训练集" },
  { value: "val", label: "验证集" },
  { value: "test", label: "测试集" },
  { value: "unselected", label: "不保留" },
];
const samplePoolAnnotationOptions: Array<{ value: Exclude<SamplePoolAnnotationFilter, "">; label: string }> = [
  { value: "annotated", label: "已标注" },
  { value: "unannotated", label: "未标注" },
];
const PAGE_SIZE = 100;
const DATASET_STATUS_POLL_INITIAL_DELAY_MS = 1500;
const DATASET_STATUS_POLL_INTERVAL_MS = 8000;
const DATASET_STATUS_POLL_HIDDEN_INTERVAL_MS = 45000;
const DATASET_IMAGE_REFRESH_INTERVAL_MS = 24000;

function buildImageFilter(
  classFilter: string,
  splitFilter: SamplePoolSplitFilter,
  annotationFilter: SamplePoolAnnotationFilter,
  sourceFilter: SamplePoolSourceFilter,
): ImageFilter | undefined {
  const filter: ImageFilter = {};
  if (classFilter) filter.class = classFilter;
  if (splitFilter) filter.split = splitFilter;
  if (annotationFilter) filter.annotation = annotationFilter;
  if (sourceFilter) filter.source = sourceFilter;
  if (!filter.class && !filter.split && !filter.annotation && !filter.source) return undefined;
  return filter;
}

function samplePoolSourceLabel(sourceType: string) {
  if (sourceType === "generation") return "AI 生成";
  if (sourceType === "augmentation") return "数据增强";
  if (["import", "video", "roboflow"].includes(sourceType)) return "导入";
  return sourceType;
}

function samplePoolSplitLabel(split: SamplePoolSplit) {
  return samplePoolSplitOptions.find((option) => option.value === split)?.label ?? split;
}

function isImageAnnotated(image: DatasetImage) {
  return image.annotationStatus === "annotated" || image.annotationStatus === "empty";
}

function samplePoolAnnotationLabel(image: DatasetImage) {
  if (image.annotationStatus === "empty") return "空标注";
  return isImageAnnotated(image) ? "已标注" : "未标注";
}

function formatMetric(value: unknown) {
  if (typeof value !== "number") return "—";
  return value <= 1 ? value.toFixed(3) : String(value);
}

function trainingStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    assigned: "已分配",
    preparing: "准备数据",
    running: "训练中",
    uploading: "上传产物",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status] ?? status;
}

function hasActiveDatasetWork(dataset: Dataset | null) {
  if (!dataset) return false;
  return (
    dataset.tasks.some((task) => activeDatasetTaskStatuses.has(task.status)) ||
    dataset.annotation?.status === "running" ||
    dataset.exports.some((item) => activeDatasetExportStatuses.has(item.status))
  );
}

function hasActiveTrainingWork(jobs: TrainingJob[]) {
  return jobs.some((job) => activeTrainingStatuses.has(job.status));
}

export function DatasetDetailPage() {
  const token = useAuthStore((state) => state.token);
  const { datasetId } = useParams();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loadedImages, setLoadedImages] = useState<DatasetImage[]>([]);
  const [imagesTotal, setImagesTotal] = useState(0);
  const [imagesCursor, setImagesCursor] = useState(0);
  const [nextImagesCursor, setNextImagesCursor] = useState<string | null>(null);
  const [hasMoreImages, setHasMoreImages] = useState(false);
  const [isLoadingFirstPage, setIsLoadingFirstPage] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [trainingJobs, setTrainingJobs] = useState<TrainingJob[]>([]);
  const datasetRef = useRef<Dataset | null>(null);
  datasetRef.current = dataset;
  const imagesTotalRef = useRef(0);
  imagesTotalRef.current = imagesTotal;
  const cursorRef = useRef(0);
  cursorRef.current = imagesCursor;
  const nextCursorRef = useRef<string | null>(null);
  nextCursorRef.current = nextImagesCursor;
  const currentFilterRef = useRef<ImageFilter | undefined>(undefined);
  const pageLoadersRef = useRef<{
    fetchFirstPage: (filter: ImageFilter | undefined) => Promise<void>;
    fetchMore: (filter: ImageFilter | undefined) => Promise<void>;
    refreshLoadedRange: (filter: ImageFilter | undefined) => Promise<Dataset | null>;
    refreshMetadata: (filter: ImageFilter | undefined) => Promise<Dataset | null>;
    refreshTrainingJobs: () => Promise<TrainingJob[] | null>;
  }>({
    fetchFirstPage: async () => {},
    fetchMore: async () => {},
    refreshLoadedRange: async () => null,
    refreshMetadata: async () => null,
    refreshTrainingJobs: async () => null,
  });
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const trainingJobsRef = useRef<TrainingJob[]>([]);
  trainingJobsRef.current = trainingJobs;
  const lastImageRefreshAtRef = useRef(0);
  const [isAugmentationModalOpen, setIsAugmentationModalOpen] = useState(false);
  const [isAnnotationModalOpen, setIsAnnotationModalOpen] = useState(false);
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [isCreatingAugmentationTask, setIsCreatingAugmentationTask] = useState(false);
  const [isSubmittingAnnotation, setIsSubmittingAnnotation] = useState(false);
  const [isCreatingExport, setIsCreatingExport] = useState(false);
  const [isCreatingTrainingJob, setIsCreatingTrainingJob] = useState(false);
  const [deletingTrainingJobId, setDeletingTrainingJobId] = useState<string | null>(null);
  const [deleteSelectionIds, setDeleteSelectionIds] = useState<string[]>([]);
  const [deletingImageIds, setDeletingImageIds] = useState<string[]>([]);
  const [multiplier, setMultiplier] = useState(3);
  const [trainingModel, setTrainingModel] = useState("yolov8n.pt");
  const [trainingEpochs, setTrainingEpochs] = useState(200);
  const [trainingImageSize, setTrainingImageSize] = useState(640);
  const [trainingBatchSize, setTrainingBatchSize] = useState(16);
  const [trainingPatience, setTrainingPatience] = useState(50);
  const [trainingDropout, setTrainingDropout] = useState(0.1);
  const [trainingMixup, setTrainingMixup] = useState(0.15);
  const [trainingWeightDecay, setTrainingWeightDecay] = useState(0.001);
  const [trainingClassIndices, setTrainingClassIndices] = useState<number[]>([]);
  const [samplePoolClassFilter, setSamplePoolClassFilter] = useState("");
  const [samplePoolSplitFilter, setSamplePoolSplitFilter] = useState<SamplePoolSplitFilter>("");
  const [samplePoolAnnotationFilter, setSamplePoolAnnotationFilter] = useState<SamplePoolAnnotationFilter>("");
  const [samplePoolSourceFilter, setSamplePoolSourceFilter] = useState<SamplePoolSourceFilter>("");
  const [augmentationMethods, setAugmentationMethods] = useState<AugmentationMethod[]>(defaultAugmentationMethods);
  const [augmentationSettings, setAugmentationSettings] = useState(defaultAugmentationSettings);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.6);
  const [skipAnnotated, setSkipAnnotated] = useState(true);
  const [exportFormat, setExportFormat] = useState<ExportFormat>("yolo");
  const [actionError, setActionError] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [isImportingVideo, setIsImportingVideo] = useState(false);
  const [isImportingRoboflow, setIsImportingRoboflow] = useState(false);
  const [activeImportTab, setActiveImportTab] = useState<ImportTab>("video");
  const [videoFrameIntervalMode, setVideoFrameIntervalMode] = useState<VideoFrameIntervalMode>("seconds");
  const [videoFrameInterval, setVideoFrameInterval] = useState(30);
  const [videoFrameIntervalSeconds, setVideoFrameIntervalSeconds] = useState(5);
  const [videoOutputFormat, setVideoOutputFormat] = useState<VideoOutputFormat>("jpg");
  const [videoJpegQuality, setVideoJpegQuality] = useState(95);
  const [videoFilenamePrefix, setVideoFilenamePrefix] = useState("frame");
  const [videoTargetSize, setVideoTargetSize] = useState<VideoTargetSize>("original");
  const [selectedVideoFile, setSelectedVideoFile] = useState<File | null>(null);
  const [roboflowConnections, setRoboflowConnections] = useState<ExternalConnection[]>([]);
  const [selectedRoboflowConnectionId, setSelectedRoboflowConnectionId] = useState("");
  const [newRoboflowConnectionName, setNewRoboflowConnectionName] = useState("Roboflow");
  const [newRoboflowApiKey, setNewRoboflowApiKey] = useState("");
  const [showRoboflowConnectionForm, setShowRoboflowConnectionForm] = useState(false);
  const [isLoadingRoboflowConnections, setIsLoadingRoboflowConnections] = useState(false);
  const [isSavingRoboflowConnection, setIsSavingRoboflowConnection] = useState(false);
  const [roboflowWorkspace, setRoboflowWorkspace] = useState("");
  const [roboflowProject, setRoboflowProject] = useState("");
  const [roboflowVersion, setRoboflowVersion] = useState("");
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<DatasetImage["detections"]>([]);
  const [isSavingAnnotations, setIsSavingAnnotations] = useState(false);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);
  const [isTasksExpanded, setIsTasksExpanded] = useState(false);
  const [isTrainingPanelOpen, setIsTrainingPanelOpen] = useState(false);
  const [isToolsPanelOpen, setIsToolsPanelOpen] = useState(false);
  const [isTasksDrawerOpen, setIsTasksDrawerOpen] = useState(false);
  const [isToolsDrawerOpen, setIsToolsDrawerOpen] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const archiveInputRef = useRef<HTMLInputElement | null>(null);
  const videoInputRef = useRef<HTMLInputElement | null>(null);
  const [previewImageNaturalSize, setPreviewImageNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [imageViewport, setImageViewport] = useState<ImageViewport | null>(null);

  const images = loadedImages;
  const filteredImages = loadedImages;
  const samplePoolClassCounts = dataset?.imageClassCounts ?? {};
  const samplePoolSplitCounts = dataset?.imageSplitCounts ?? { train: 0, val: 0, test: 0, unselected: 0 };
  const samplePoolAnnotationCounts = dataset?.imageAnnotationCounts ?? { annotated: 0, unannotated: 0 };
  const samplePoolSourceCounts = dataset?.imageSourceCounts ?? { generation: 0, imported: 0, augmentation: 0 };
  const filteredImageIds = filteredImages.map((image) => image.id);
  const filteredSelectedCount = filteredImages.filter((image) => image.selected).length;
  const filteredAnnotatedCount = filteredImages.filter((image) => isImageAnnotated(image)).length;
  const filteredUnannotatedCount = filteredImages.length - filteredAnnotatedCount;
  const retainedImageCount = dataset?.selectedCount ?? 0;
  const unretainedImageCount = Math.max(0, (dataset?.imageCount ?? 0) - retainedImageCount);
  const unretainedUnannotatedImageCount = dataset?.unretainedUnannotatedImageCount ?? 0;
  const imageIdSet = new Set(images.map((image) => image.id));
  const deleteSelectionIdSet = new Set(deleteSelectionIds);
  const deletingImageIdSet = new Set(deletingImageIds);
  const deleteSelectionCount = deleteSelectionIds.filter((imageId) => imageIdSet.has(imageId)).length;
  const filteredDeleteSelectionCount = filteredImages.filter((image) => deleteSelectionIdSet.has(image.id)).length;
  const previewIndex = previewImageId ? images.findIndex((image) => image.id === previewImageId) : -1;
  const previewImage = previewIndex >= 0 ? images[previewIndex] : null;
  const annotationRunning = dataset?.annotation?.status === "running";
  const selectedOriginalCount = dataset?.selectedOriginalCount ?? 0;
  const latestExport = dataset?.exports[0];
  const annotationStatus = String(dataset?.annotation?.status ?? "idle");
  const latestTrainingJob = trainingJobs[0];
  const trainingRunning = trainingJobs.some((job) => activeTrainingStatuses.has(job.status));
  const trainingClassIndexSet = new Set(trainingClassIndices);
  const isAnyImporting = isImporting || isImportingVideo || isImportingRoboflow;
  const normalizedVideoFrameInterval = Math.max(1, Math.min(10000, Math.round(videoFrameInterval) || 30));
  const normalizedVideoFrameIntervalSeconds = Math.max(0.01, Math.min(3600, Number(videoFrameIntervalSeconds) || 5));
  const videoFrameIntervalHint =
    videoFrameIntervalMode === "seconds"
      ? `每 ${normalizedVideoFrameIntervalSeconds.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 秒取一张`
      : `每 ${normalizedVideoFrameInterval} 帧取一张`;
  const videoFilenamePrefixPreview = videoFilenamePrefix.trim().replace(/[^A-Za-z0-9_-]/g, "") || "frame";
  const videoOutputExample = `${videoFilenamePrefixPreview}_000000.${videoOutputFormat}`;
  const videoTargetSizeLabel = videoTargetSizeOptions.find((option) => option.value === videoTargetSize)?.label ?? "原图";
  const selectedVideoFileSize = selectedVideoFile
    ? `${(selectedVideoFile.size / 1024 / 1024).toLocaleString("zh-CN", { maximumFractionDigits: 1 })} MB`
    : "";

  useEffect(() => {
    if (!token || !datasetId) return;
    let disposed = false;

    const fetchFirstPage = async (filter: ImageFilter | undefined) => {
      setIsLoadingFirstPage(true);
      try {
        const [response, trainingResponse] = await Promise.all([
          getDataset(datasetId, token, { offset: 0, limit: PAGE_SIZE, filter }),
          listTrainingJobs(datasetId, token),
        ]);
        if (disposed) return;
        setDataset(response.dataset);
        setLoadedImages(response.dataset.images);
        setImagesTotal(response.dataset.imagesTotal ?? response.dataset.images.length);
        setImagesCursor(response.dataset.images.length);
        setNextImagesCursor(response.dataset.imagesNextCursor ?? null);
        setHasMoreImages(Boolean(response.dataset.imagesNextCursor));
        setTrainingJobs(trainingResponse.jobs);
        lastImageRefreshAtRef.current = Date.now();
        setActionError(null);
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
      } finally {
        if (!disposed) setIsLoadingFirstPage(false);
      }
    };

    const fetchMore = async (filter: ImageFilter | undefined) => {
      const offset = cursorRef.current;
      if (offset >= imagesTotalRef.current) return;
      setIsLoadingMore(true);
      try {
        const response = await getDataset(datasetId, token, {
          cursor: nextCursorRef.current ?? undefined,
          offset: nextCursorRef.current ? undefined : offset,
          limit: PAGE_SIZE,
          filter,
        });
        if (disposed) return;
        const incoming = response.dataset.images;
        if (incoming.length === 0) {
          setHasMoreImages(false);
          return;
        }
        setLoadedImages((current) => {
          const seen = new Set(current.map((image) => image.id));
          const merged = [...current];
          for (const image of incoming) {
            if (!seen.has(image.id)) {
              merged.push(image);
              seen.add(image.id);
            }
          }
          return merged;
        });
        setDataset(response.dataset);
        setImagesTotal(response.dataset.imagesTotal ?? imagesTotalRef.current);
        const nextCursor = offset + incoming.length;
        setImagesCursor(nextCursor);
        setNextImagesCursor(response.dataset.imagesNextCursor ?? null);
        setHasMoreImages(Boolean(response.dataset.imagesNextCursor));
        lastImageRefreshAtRef.current = Date.now();
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
      } finally {
        if (!disposed) setIsLoadingMore(false);
      }
    };

    const refreshLoadedRange = async (filter: ImageFilter | undefined) => {
      const limit = Math.max(PAGE_SIZE, cursorRef.current);
      try {
        const response = await getDataset(datasetId, token, { offset: 0, limit, filter });
        if (disposed) return null;
        setDataset(response.dataset);
        setLoadedImages(response.dataset.images);
        const total = response.dataset.imagesTotal ?? response.dataset.images.length;
        setImagesTotal(total);
        const nextCursor = response.dataset.images.length;
        setImagesCursor(nextCursor);
        setNextImagesCursor(response.dataset.imagesNextCursor ?? null);
        setHasMoreImages(Boolean(response.dataset.imagesNextCursor));
        lastImageRefreshAtRef.current = Date.now();
        return response.dataset;
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
        return null;
      }
    };

    const refreshMetadata = async (filter: ImageFilter | undefined) => {
      try {
        const response = await getDataset(datasetId, token, { offset: 0, limit: 0, filter });
        if (disposed) return null;
        mergeDatasetMetadata(response.dataset);
        const total = response.dataset.imagesTotal ?? imagesTotalRef.current;
        setImagesTotal(total);
        setHasMoreImages(cursorRef.current < total);
        return response.dataset;
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
        return null;
      }
    };

    const refreshTrainingJobs = async () => {
      try {
        const response = await listTrainingJobs(datasetId, token);
        if (disposed) return null;
        setTrainingJobs(response.jobs);
        return response.jobs;
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
        return null;
      }
    };

    pageLoadersRef.current = { fetchFirstPage, fetchMore, refreshLoadedRange, refreshMetadata, refreshTrainingJobs };

    return () => {
      disposed = true;
    };
  }, [datasetId, token]);

  useEffect(() => {
    if (!token || !datasetId) return;
    let disposed = false;
    let timeoutId: number | undefined;

    const schedule = (delay: number) => {
      if (disposed) return;
      timeoutId = window.setTimeout(() => {
        void pollStatus();
      }, delay);
    };

    const pollStatus = async () => {
      const activeBefore = hasActiveDatasetWork(datasetRef.current) || hasActiveTrainingWork(trainingJobsRef.current);
      if (!activeBefore) {
        schedule(DATASET_STATUS_POLL_INTERVAL_MS);
        return;
      }

      const isVisible = document.visibilityState !== "hidden";
      const shouldRefreshImages =
        isVisible && Date.now() - lastImageRefreshAtRef.current >= DATASET_IMAGE_REFRESH_INTERVAL_MS;

      let latestDataset: Dataset | null = null;
      let latestTrainingJobs: TrainingJob[] | null = null;

      if (shouldRefreshImages) {
        latestDataset = await pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
      } else {
        latestDataset = await pageLoadersRef.current.refreshMetadata(currentFilterRef.current);
      }

      if (hasActiveTrainingWork(trainingJobsRef.current)) {
        latestTrainingJobs = await pageLoadersRef.current.refreshTrainingJobs();
      }

      const activeAfter =
        hasActiveDatasetWork(latestDataset ?? datasetRef.current) ||
        hasActiveTrainingWork(latestTrainingJobs ?? trainingJobsRef.current);
      if (isVisible && activeBefore && !activeAfter) {
        await pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
      }

      schedule(isVisible ? DATASET_STATUS_POLL_INTERVAL_MS : DATASET_STATUS_POLL_HIDDEN_INTERVAL_MS);
    };

    schedule(DATASET_STATUS_POLL_INITIAL_DELAY_MS);

    return () => {
      disposed = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [datasetId, token]);

  useEffect(() => {
    const categoryCount = dataset?.categories.length ?? 0;
    setTrainingClassIndices((current) => current.filter((index) => index < categoryCount));
  }, [dataset?.categories.length]);

  useEffect(() => {
    const currentImageIds = new Set(loadedImages.map((image) => image.id));
    setDeleteSelectionIds((current) => current.filter((imageId) => currentImageIds.has(imageId)));
  }, [loadedImages]);

  useEffect(() => {
    if (samplePoolClassFilter && !(dataset?.categories ?? []).includes(samplePoolClassFilter)) {
      setSamplePoolClassFilter("");
    }
  }, [dataset?.categories, samplePoolClassFilter]);

  useEffect(() => {
    const filter = buildImageFilter(
      samplePoolClassFilter,
      samplePoolSplitFilter,
      samplePoolAnnotationFilter,
      samplePoolSourceFilter,
    );
    currentFilterRef.current = filter;
    if (!token || !datasetId) return;
    void pageLoadersRef.current.fetchFirstPage(filter);
  }, [datasetId, token, samplePoolClassFilter, samplePoolSplitFilter, samplePoolAnnotationFilter, samplePoolSourceFilter]);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          if (!isLoadingMore && hasMoreImages) {
            void pageLoadersRef.current.fetchMore(currentFilterRef.current);
          }
        }
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMoreImages, isLoadingMore, loadedImages.length]);

  useEffect(() => {
    setDraftDetections(previewImage?.detections ?? []);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(false);
  }, [previewImage]);

  useEffect(() => {
    setPreviewImageNaturalSize(null);
    setImageViewport(null);
  }, [previewImage?.id]);

  useEffect(() => {
    if (!previewImageNaturalSize || !stageRef.current) {
      setImageViewport(null);
      return;
    }

    const stage = stageRef.current;
    const syncViewport = () => {
      const rect = stage.getBoundingClientRect();
      setImageViewport(
        fitImageViewport(
          rect.width,
          rect.height,
          previewImageNaturalSize.width,
          previewImageNaturalSize.height,
        ),
      );
    };

    syncViewport();

    const resizeObserver = new ResizeObserver(syncViewport);
    resizeObserver.observe(stage);

    return () => resizeObserver.disconnect();
  }, [previewImageNaturalSize]);

  useEffect(() => {
    if (!previewImage) return;

    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (isAddingDetection) {
          setIsAddingDetection(false);
          return;
        }
        if (confirmDiscardChanges()) {
          setPreviewImageId(null);
        }
        return;
      }
      if (event.key === "ArrowLeft" && previewIndex > 0) {
        movePreview(-1);
      }
      if (event.key === "ArrowRight" && previewIndex < images.length - 1) {
        movePreview(1);
      }
      if (event.key === "Delete" && selectedDetectionIndex !== null) {
        removeDetection(selectedDetectionIndex);
      }
    };

    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [images, isAddingDetection, previewImage, previewIndex, selectedDetectionIndex]);

  const hasAnnotationChanges =
    previewImage !== null && !detectionsEqual(previewImage.detections, draftDetections);

  useEffect(() => {
    if (!previewImage || !hasAnnotationChanges) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasAnnotationChanges, previewImage]);

  useEffect(() => {
    if (!isAugmentationModalOpen && !isAnnotationModalOpen && !isExportModalOpen && !isImportModalOpen) return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !isCreatingAugmentationTask &&
        !isSubmittingAnnotation &&
        !isCreatingExport &&
        !isImporting &&
        !isImportingVideo &&
        !isImportingRoboflow
      ) {
        setIsAugmentationModalOpen(false);
        setIsAnnotationModalOpen(false);
        setIsExportModalOpen(false);
        setIsImportModalOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [
    isAnnotationModalOpen,
    isAugmentationModalOpen,
    isCreatingAugmentationTask,
    isCreatingExport,
    isExportModalOpen,
    isImportModalOpen,
    isImporting,
    isImportingVideo,
    isImportingRoboflow,
    isSubmittingAnnotation,
  ]);

  function confirmDiscardChanges() {
    if (!hasAnnotationChanges) return true;
    return window.confirm("当前图片有未保存的标注改动，确认放弃并继续？");
  }

  function openPreview(nextImageId: string | null) {
    if (!confirmDiscardChanges()) return;
    setPreviewImageId(nextImageId);
  }

  function movePreview(direction: -1 | 1) {
    if (!previewImage) return;
    const nextIndex = previewIndex + direction;
    if (nextIndex < 0 || nextIndex >= images.length) return;
    openPreview(images[nextIndex].id);
  }

  function toggleAugmentationMethod(method: AugmentationMethod) {
    setAugmentationMethods((current) =>
      current.includes(method) ? current.filter((item) => item !== method) : [...current, method],
    );
  }

  function toggleTrainingClass(index: number) {
    setTrainingClassIndices((current) =>
      current.includes(index) ? current.filter((item) => item !== index) : [...current, index].sort((a, b) => a - b),
    );
  }

  function openAugmentationModal() {
    setIsAugmentationModalOpen(true);
    setIsAnnotationModalOpen(false);
    setIsExportModalOpen(false);
    setIsImportModalOpen(false);
  }

  function openAnnotationModal() {
    setIsAnnotationModalOpen(true);
    setIsAugmentationModalOpen(false);
    setIsExportModalOpen(false);
    setIsImportModalOpen(false);
  }

  function openExportModal() {
    setIsExportModalOpen(true);
    setIsAugmentationModalOpen(false);
    setIsAnnotationModalOpen(false);
    setIsImportModalOpen(false);
  }

  function openImportModal() {
    setIsImportModalOpen(true);
    setIsAugmentationModalOpen(false);
    setIsAnnotationModalOpen(false);
    setIsExportModalOpen(false);
    if (token) void loadRoboflowConnections();
  }

  async function loadRoboflowConnections() {
    if (!token) return;
    setIsLoadingRoboflowConnections(true);
    try {
      const response = await listRoboflowConnections(token);
      setRoboflowConnections(response.connections);
      setSelectedRoboflowConnectionId((current) =>
        response.connections.some((connection) => connection.id === current)
          ? current
          : response.connections[0]?.id ?? "",
      );
      setShowRoboflowConnectionForm(response.connections.length === 0);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsLoadingRoboflowConnections(false);
    }
  }

  async function saveRoboflowConnection() {
    if (!token || !newRoboflowConnectionName.trim() || !newRoboflowApiKey.trim()) return;
    setIsSavingRoboflowConnection(true);
    try {
      const response = await createRoboflowConnection(
        token,
        newRoboflowConnectionName.trim(),
        newRoboflowApiKey.trim(),
      );
      setRoboflowConnections((current) => [...current, response.connection]);
      setSelectedRoboflowConnectionId(response.connection.id);
      setNewRoboflowApiKey("");
      setShowRoboflowConnectionForm(false);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSavingRoboflowConnection(false);
    }
  }

  async function removeSelectedRoboflowConnection() {
    if (!token || !selectedRoboflowConnectionId) return;
    if (!window.confirm("删除这个 Roboflow 连接？已导入的数据不会受到影响。")) return;
    try {
      await deleteRoboflowConnection(token, selectedRoboflowConnectionId);
      const remaining = roboflowConnections.filter((connection) => connection.id !== selectedRoboflowConnectionId);
      setRoboflowConnections(remaining);
      setSelectedRoboflowConnectionId(remaining[0]?.id ?? "");
      setShowRoboflowConnectionForm(remaining.length === 0);
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  async function createAugmentationTask() {
    if (!token || !datasetId || augmentationMethods.length === 0 || selectedOriginalCount === 0) return;
    setIsCreatingAugmentationTask(true);
    try {
      const response = await augmentDataset(datasetId, token, multiplier, augmentationMethods, augmentationSettings);
      setDataset(response.dataset);
      setActionError(null);
      setIsAugmentationModalOpen(false);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsCreatingAugmentationTask(false);
    }
  }

  async function runAutoAnnotation() {
    if (!token || !datasetId) return;
    setIsSubmittingAnnotation(true);
    try {
      const response = await annotateDataset(datasetId, token, confidenceThreshold, skipAnnotated);
      setDataset(response.dataset);
      setActionError(null);
      setIsAnnotationModalOpen(false);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSubmittingAnnotation(false);
    }
  }

  async function createExportPackage() {
    if (!token || !datasetId) return;
    setIsCreatingExport(true);
    try {
      const response = await exportDataset(datasetId, token, exportFormat, "keep");
      setDataset(response.dataset);
      setActionError(null);
      setIsExportModalOpen(false);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsCreatingExport(false);
    }
  }

  async function startTrainingJob() {
    if (!token || !datasetId) return;
    setIsCreatingTrainingJob(true);
    try {
      const response = await createTrainingJob(datasetId, token, {
        model: trainingModel.trim() || "yolov8n.pt",
        epochs: trainingEpochs,
        image_size: trainingImageSize,
        batch_size: trainingBatchSize,
        patience: trainingPatience,
        dropout: trainingDropout,
        mixup: trainingMixup,
        weight_decay: trainingWeightDecay,
        classes: trainingClassIndices,
      });
      setDataset(response.dataset);
      setTrainingJobs((current) => [response.job, ...current.filter((job) => job.id !== response.job.id)]);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsCreatingTrainingJob(false);
    }
  }

  async function removeTrainingJob(job: TrainingJob) {
    if (!token || !datasetId) return;
    const confirmed = window.confirm("删除该训练任务？如果 worker 仍在运行，这不会停止 GPU 上的训练进程。");
    if (!confirmed) return;

    setDeletingTrainingJobId(job.id);
    try {
      const response = await deleteTrainingJob(datasetId, job.id, token);
      setDataset(response.dataset);
      setTrainingJobs((current) => current.filter((item) => item.id !== response.deletedJobId));
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setDeletingTrainingJobId(null);
    }
  }

  async function applySelection(
    payload:
      | { mode: "all" | "none" | "invert"; image_ids?: string[]; scope?: "unannotated_unretained" }
      | { mode: "single"; image_id: string; selected: boolean },
  ) {
    if (!token || !datasetId) return;
    try {
      const response = await updateDatasetSelection(datasetId, token, payload);
      const prev = datasetRef.current;
      const merged: Dataset = prev
        ? { ...prev, ...response.dataset, images: prev.images }
        : response.dataset;
      setDataset(merged);
      setActionError(null);
      await pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  function applySamplePoolRetention(mode: "all" | "none" | "invert") {
    const totalImages = dataset?.imageCount ?? 0;
    if (totalImages === 0) return;

    const confirmMessage =
      mode === "all"
        ? `确认将全部 ${totalImages} 张样本标记为保留？当前有 ${unretainedImageCount} 张会从不保留变为保留。`
        : mode === "invert"
          ? `确认反转全部 ${totalImages} 张样本的保留状态？当前 ${retainedImageCount} 张会变为不保留，${unretainedImageCount} 张会变为保留。`
          : `确认将全部 ${totalImages} 张样本标记为不保留？当前 ${retainedImageCount} 张保留样本会被移出训练和导出。`;
    if (!window.confirm(confirmMessage)) return;

    void applySelection({ mode });
  }

  function retainUnannotatedSamplePoolImages() {
    if (unretainedUnannotatedImageCount === 0) return;
    const confirmed = window.confirm(
      `确认将 ${unretainedUnannotatedImageCount} 张未标注且当前不保留的样本标记为保留？`,
    );
    if (!confirmed) return;
    void applySelection({ mode: "all", scope: "unannotated_unretained" });
  }

  function toggleDeleteSelection(imageId: string) {
    setDeleteSelectionIds((current) =>
      current.includes(imageId) ? current.filter((item) => item !== imageId) : [...current, imageId],
    );
  }

  function selectFilteredForDelete() {
    setDeleteSelectionIds((current) => Array.from(new Set([...current, ...filteredImageIds])));
  }

  async function removeDatasetImages(imageIds: string[], label: string) {
    if (!token || !datasetId) return;
    const uniqueImageIds = Array.from(new Set(imageIds)).filter((imageId) => imageIdSet.has(imageId));
    if (uniqueImageIds.length === 0) return;
    if (previewImageId && uniqueImageIds.includes(previewImageId) && !confirmDiscardChanges()) return;

    const confirmed = window.confirm(
      uniqueImageIds.length === 1
        ? `删除${label}？图片文件和标注也会一起移除。`
        : `删除已勾选的 ${uniqueImageIds.length} 张样本？图片文件和标注也会一起移除。`,
    );
    if (!confirmed) return;

    setDeletingImageIds(uniqueImageIds);
    try {
      const response =
        uniqueImageIds.length === 1
          ? await deleteDatasetImage(datasetId, uniqueImageIds[0], token)
          : await deleteDatasetImages(datasetId, uniqueImageIds, token);
      const deletedIdSet = new Set(response.deletedImageIds);
      const prev = datasetRef.current;
      const merged: Dataset = prev
        ? { ...prev, ...response.dataset, images: prev.images }
        : response.dataset;
      setDataset(merged);
      setLoadedImages((current) => current.filter((image) => !deletedIdSet.has(image.id)));
      setImagesTotal((total) => Math.max(0, total - deletedIdSet.size));
      setImagesCursor((cursor) => Math.max(0, cursor - deletedIdSet.size));
      setDeleteSelectionIds((current) => current.filter((imageId) => !deletedIdSet.has(imageId)));
      if (previewImageId && deletedIdSet.has(previewImageId)) {
        setPreviewImageId(null);
      }
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setDeletingImageIds([]);
    }
  }

  function removeDatasetImage(image: DatasetImage) {
    void removeDatasetImages([image.id], `样本 #${image.ordinal}`);
  }

  function removeDeleteSelection() {
    const imageIds = deleteSelectionIds.filter((imageId) => imageIdSet.has(imageId));
    void removeDatasetImages(imageIds, "");
  }

  function mergeDatasetMetadata(responseDataset: Dataset) {
    const prev = datasetRef.current;
    const merged: Dataset = prev
      ? { ...prev, ...responseDataset, images: prev.images }
      : responseDataset;
    setDataset(merged);
  }

  async function handleArchiveImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!token || !datasetId || !file) return;
    setIsImporting(true);
    setImportSummary(null);
    try {
      const response = await importDatasetImagesArchive(datasetId, token, file);
      mergeDatasetMetadata(response.dataset);
      setActionError(null);
      setImportSummary(
        `已导入 ${String(response.summary.importedCount ?? 0)} 张图片` +
          (Number(response.summary.skippedCount ?? 0) > 0 ? `，跳过 ${String(response.summary.skippedCount ?? 0)} 个无效文件` : ""),
      );
      setIsImportModalOpen(false);
      void pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      event.target.value = "";
      setIsImporting(false);
    }
  }

  function handleVideoSelection(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setSelectedVideoFile(file);
    setImportSummary(null);
    setActionError(null);
    event.target.value = "";
  }

  async function handleVideoImport() {
    if (!token || !datasetId || !selectedVideoFile) {
      setActionError("请先选择视频。");
      return;
    }
    const frameInterval = normalizedVideoFrameInterval;
    const frameIntervalSeconds = normalizedVideoFrameIntervalSeconds;
    const jpegQuality = Math.max(1, Math.min(100, Math.round(videoJpegQuality) || 95));
    const filenamePrefix = videoFilenamePrefix.trim() || "frame";
    setIsImportingVideo(true);
    setImportSummary(null);
    try {
      const response = await importDatasetVideo(datasetId, token, selectedVideoFile, {
        frameIntervalMode: videoFrameIntervalMode,
        frameInterval,
        frameIntervalSeconds,
        outputFormat: videoOutputFormat,
        jpegQuality,
        filenamePrefix,
        targetSize: videoTargetSize,
      });
      mergeDatasetMetadata(response.dataset);
      setActionError(null);
      const importedCount = Number(response.summary.importedCount ?? response.task.imagesGenerated ?? 0);
      setImportSummary(
        response.task.status === "running"
          ? `已创建视频抽帧任务，${videoFrameIntervalHint}，尺寸 ${videoTargetSizeLabel}`
          : `已从视频抽取 ${importedCount} 张图片`,
      );
      setSelectedVideoFile(null);
      setIsImportModalOpen(false);
      void pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsImportingVideo(false);
    }
  }

  async function handleRoboflowImport() {
    if (!token || !datasetId) return;
    const connectionId = selectedRoboflowConnectionId;
    const workspace = roboflowWorkspace.trim();
    const project = roboflowProject.trim();
    const version = roboflowVersion.trim();
    if (!connectionId || !workspace || !project || !version) {
      setActionError("请选择 Roboflow 连接，并填写 workspace、project 和 version。");
      return;
    }

    setIsImportingRoboflow(true);
    setImportSummary(null);
    try {
      const response = await importDatasetFromRoboflow(datasetId, token, {
        connectionId,
        workspace,
        project,
        version,
        format: "yolov8",
      });
      mergeDatasetMetadata(response.dataset);
      setActionError(null);
      setImportSummary(response.summary.status === "running"
        ? "已创建 Roboflow 下载任务，可在批次任务中查看进度。"
        : `已从 Roboflow 导入 ${String(response.summary.importedCount ?? 0)} 张图片` +
          (Number(response.summary.annotatedCount ?? 0) > 0 ? `，带标注 ${String(response.summary.annotatedCount ?? 0)} 张` : "") +
          (Number(response.summary.emptyAnnotationCount ?? 0) > 0 ? `，空标注 ${String(response.summary.emptyAnnotationCount ?? 0)} 张` : "") +
          (Number(response.summary.skippedCount ?? 0) > 0 ? `，跳过 ${String(response.summary.skippedCount ?? 0)} 个无效文件` : ""));
      setIsImportModalOpen(false);
      void pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsImportingRoboflow(false);
    }
  }

  async function saveAnnotations() {
    if (!token || !datasetId || !previewImage) return;
    setIsSavingAnnotations(true);
    try {
      const response = await updateDatasetImageAnnotations(datasetId, previewImage.id, token, draftDetections);
      mergeDatasetMetadata(response.dataset);
      const updatedImage = response.image;
      setLoadedImages((current) =>
        current.map((image) => (image.id === updatedImage.id ? updatedImage : image)),
      );
      setActionError(null);
      await pageLoadersRef.current.refreshLoadedRange(currentFilterRef.current);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSavingAnnotations(false);
    }
  }

  function beginDragDetection(index: number, event: ReactMouseEvent<HTMLDivElement>) {
    if (!viewportRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = viewportRef.current.getBoundingClientRect();
    const origin = draftDetections[index];
    const startX = event.clientX;
    const startY = event.clientY;

    const handleMove = (moveEvent: MouseEvent) => {
      const deltaX = (moveEvent.clientX - startX) / rect.width;
      const deltaY = (moveEvent.clientY - startY) / rect.height;
      setDraftDetections((current) =>
        current.map((detection, detectionIndex) => {
          if (detectionIndex !== index) return detection;
          const [, , width, height] = origin.bbox;
          const nextX = Math.min(Math.max(origin.bbox[0] + deltaX, width / 2), 1 - width / 2);
          const nextY = Math.min(Math.max(origin.bbox[1] + deltaY, height / 2), 1 - height / 2);
          return { ...detection, bbox: [nextX, nextY, width, height] };
        }),
      );
    };

    const handleUp = () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  }

  function beginResizeDetection(index: number, corner: ResizeCorner, event: ReactMouseEvent<HTMLButtonElement>) {
    if (!viewportRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = viewportRef.current.getBoundingClientRect();
    const origin = draftDetections[index];
    const [xCenter, yCenter, width, height] = origin.bbox;
    const left = xCenter - width / 2;
    const right = xCenter + width / 2;
    const top = yCenter - height / 2;
    const bottom = yCenter + height / 2;
    const anchorX = corner.includes("w") ? right : left;
    const anchorY = corner.includes("n") ? bottom : top;
    const minBoxSize = minimumBoxSizeForImage(
      previewImageNaturalSize?.width ?? rect.width,
      previewImageNaturalSize?.height ?? rect.height,
    );

    const handleMove = (moveEvent: MouseEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(anchorX, anchorY, pointer.x, pointer.y, minBoxSize.width, minBoxSize.height);
      setDraftDetections((current) =>
        current.map((detection, detectionIndex) => (detectionIndex === index ? { ...detection, bbox } : detection)),
      );
    };

    const handleUp = () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  }

  function handleStageMouseDown(event: ReactMouseEvent<HTMLDivElement>) {
    if (!viewportRef.current || !isAddingDetection || !dataset) return;
    event.preventDefault();
    const rect = viewportRef.current.getBoundingClientRect();
    const start = pointerToStage(rect, event.clientX, event.clientY);
    const category = dataset.categories[0] ?? "object";
    const nextIndex = draftDetections.length;
    const minBoxSize = minimumBoxSizeForImage(
      previewImageNaturalSize?.width ?? rect.width,
      previewImageNaturalSize?.height ?? rect.height,
    );

    setDraftDetections((current) => [
      ...current,
      { category, confidence: 0.8, bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE] },
    ]);
    setSelectedDetectionIndex(nextIndex);

    const handleMove = (moveEvent: MouseEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(start.x, start.y, pointer.x, pointer.y, minBoxSize.width, minBoxSize.height);
      setDraftDetections((current) =>
        current.map((detection, detectionIndex) => (detectionIndex === nextIndex ? { ...detection, bbox } : detection)),
      );
    };

    const handleUp = () => {
      setIsAddingDetection(false);
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  }

  function updateDetectionField(index: number, field: "category" | "confidence", value: string | number) {
    setDraftDetections((current) =>
      current.map((detection, detectionIndex) => {
        if (detectionIndex !== index) return detection;
        if (field === "category") {
          return { ...detection, category: String(value).slice(0, 120) || "object" };
        }
        const nextConfidence = Number(value);
        return {
          ...detection,
          confidence: Number.isFinite(nextConfidence) ? Math.min(Math.max(nextConfidence, 0), 1) : detection.confidence,
        };
      }),
    );
  }

  function removeDetection(index: number) {
    setDraftDetections((current) => current.filter((_, detectionIndex) => detectionIndex !== index));
    setSelectedDetectionIndex((current) => {
      if (current === null) return null;
      if (current === index) return null;
      return current > index ? current - 1 : current;
    });
  }

  if (!dataset) {
    return (
      <SectionCard>
        <div className="text-sm text-neutral-500 dark:text-neutral-400">加载数据集中...</div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-6">
      <SectionCard className="overflow-hidden">
        <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <div className="flex flex-wrap gap-2">
              <Badge>{dataset.status}</Badge>
              {dataset.categories.map((category) => (
                <Badge key={category}>{category}</Badge>
              ))}
            </div>
            <h2 className="mt-4 text-4xl font-medium text-neutral-900 dark:text-white">{dataset.name}</h2>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              {dataset.description || "这个数据集还没有填写说明。"}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to={`/datasets/${dataset.id}/generate`}>
                <Button><Sparkles className="mr-2 h-4 w-4" />生成</Button>
              </Link>
              <Button
                variant="secondary"
                onClick={openAugmentationModal}
                disabled={selectedOriginalCount === 0}
              >
                <Wand2 className="mr-2 h-4 w-4" />
                增强
              </Button>
              <Button
                variant="secondary"
                onClick={openAnnotationModal}
                disabled={dataset.imageCount === 0 || annotationRunning}
              >
                <Tag className="mr-2 h-4 w-4" />
                自动标注
              </Button>
              <Link
                to={`/datasets/${dataset.id}/annotate`}
                className={dataset.imageCount === 0 ? "pointer-events-none" : undefined}
              >
                <Button variant="secondary" disabled={dataset.imageCount === 0}>
                  <PencilRuler className="mr-2 h-4 w-4" />
                  标注模式
                </Button>
              </Link>
              <Button
                variant="secondary"
                onClick={openExportModal}
                disabled={dataset.selectedCount === 0}
              >
                <Download className="mr-2 h-4 w-4" />
                导出
              </Button>
              <Button variant="secondary" onClick={openImportModal} disabled={isAnyImporting}>
                <Upload className="mr-2 h-4 w-4" />
                导入
              </Button>
              <Button
                variant="secondary"
                onClick={() => setIsTrainingPanelOpen(true)}
              >
                <Cpu className="mr-2 h-4 w-4" />
                训练
                {latestTrainingJob ? (
                  <span className="ml-1.5 text-xs text-neutral-400">
                    {trainingRunning ? "运行中" : trainingStatusLabel(latestTrainingJob.status)}
                  </span>
                ) : null}
              </Button>
              <Button
                variant="secondary"
                onClick={() => setIsTasksDrawerOpen(true)}
              >
                <ClipboardList className="mr-2 h-4 w-4" />
                批次任务
                <span className="ml-1.5 text-xs text-neutral-400">{dataset.tasks.length}</span>
              </Button>
              <Button
                variant="secondary"
                onClick={() => setIsToolsDrawerOpen(true)}
              >
                <Layers className="mr-2 h-4 w-4" />
                数据集功能
              </Button>
              <input ref={archiveInputRef} type="file" accept=".zip" className="hidden" onChange={handleArchiveImport} />
              <input
                ref={videoInputRef}
                type="file"
                accept="video/*,.mp4,.mov,.avi,.mkv,.webm,.dav,.mpg,.mpeg,.ps"
                className="hidden"
                onChange={handleVideoSelection}
              />
            </div>
            {importSummary ? <div className="mt-3 text-sm text-neutral-500">{importSummary}</div> : null}
            {selectedOriginalCount === 0 ? (
              <div className="mt-3 text-sm text-neutral-500">当前没有保留的原始样本，暂时不能创建增强批次。</div>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "样本池", value: String(dataset.imageCount) },
              { label: "保留样本", value: String(dataset.selectedCount) },
              { label: "任务批次", value: String(dataset.taskCount) },
              { label: "累计成本", value: formatCurrency(dataset.spentCost) },
            ].map((metric) => (
              <div key={metric.label} className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">{metric.label}</div>
                <div className="mt-3 text-2xl text-neutral-900 dark:text-white">{metric.value}</div>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      {actionError ? (
        <SectionCard className="border-red-300/40 bg-red-50 dark:border-red-400/20 dark:bg-red-950/20">
          <div className="text-sm text-red-700 dark:text-red-100">{actionError}</div>
        </SectionCard>
      ) : null}

      <DatasetQualityPanel datasetId={dataset.id} token={token} imageCount={dataset.imageCount} />

      {isTrainingPanelOpen ? (
      <SectionCard>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-neutral-500">
                  <Cpu className="h-4 w-4" />
                  YOLOv8 Training
                </div>
                <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">训练 worker</h3>
              </div>
              <div className="flex items-center gap-2">
                <Badge>{trainingRunning ? "运行中" : latestTrainingJob ? trainingStatusLabel(latestTrainingJob.status) : "待训练"}</Badge>
                <button
                  type="button"
                  onClick={() => setIsTrainingPanelOpen(false)}
                  className="rounded-full p-1 hover:bg-neutral-100 dark:hover:bg-white/10"
                  aria-label="关闭训练面板"
                >
                  <X className="h-5 w-5 text-neutral-500" />
                </button>
              </div>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <label className="space-y-2 lg:col-span-2">
                <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">模型</span>
                <Input value={trainingModel} onChange={(event) => setTrainingModel(event.target.value)} />
              </label>
              <label className="space-y-2">
                <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Epochs</span>
                <Input type="number" min={1} max={500} value={trainingEpochs} onChange={(event) => setTrainingEpochs(Number(event.target.value))} />
              </label>
              <label className="space-y-2">
                <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Image</span>
                <Input type="number" min={64} max={2048} step={32} value={trainingImageSize} onChange={(event) => setTrainingImageSize(Number(event.target.value))} />
              </label>
              <label className="space-y-2">
                <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Batch</span>
                <Input type="number" min={1} max={256} value={trainingBatchSize} onChange={(event) => setTrainingBatchSize(Number(event.target.value))} />
              </label>
            </div>

            <div className="mt-4 space-y-2">
              <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Classes</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setTrainingClassIndices([])}
                  className={`rounded-full border px-3 py-1.5 text-sm transition ${
                    trainingClassIndices.length === 0
                      ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                      : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                  }`}
                >
                  全部
                </button>
                {dataset.categories.map((category, index) => (
                  <button
                    key={`${index}-${category}`}
                    type="button"
                    onClick={() => toggleTrainingClass(index)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      trainingClassIndexSet.has(index)
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                    }`}
                  >
                    {index}: {category}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-neutral-500">
                <span>Patience</span>
                <Input
                  className="w-24"
                  type="number"
                  min={0}
                  max={200}
                  value={trainingPatience}
                  onChange={(event) => setTrainingPatience(Number(event.target.value))}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-neutral-500">
                <span>Dropout</span>
                <Input
                  className="w-24"
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={trainingDropout}
                  onChange={(event) => setTrainingDropout(Number(event.target.value))}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-neutral-500">
                <span>Mixup</span>
                <Input
                  className="w-24"
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={trainingMixup}
                  onChange={(event) => setTrainingMixup(Number(event.target.value))}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-neutral-500">
                <span>Weight decay</span>
                <Input
                  className="w-28"
                  type="number"
                  min={0}
                  max={1}
                  step={0.0001}
                  value={trainingWeightDecay}
                  onChange={(event) => setTrainingWeightDecay(Number(event.target.value))}
                />
              </label>
              <Button onClick={() => void startTrainingJob()} disabled={isCreatingTrainingJob || dataset.selectedCount === 0 || trainingRunning}>
                <Play className="mr-2 h-4 w-4" />
                {isCreatingTrainingJob ? "创建中..." : "开始训练"}
              </Button>
              {dataset.selectedCount === 0 ? <span className="text-sm text-neutral-500">请先保留样本后再训练。</span> : null}
            </div>
          </div>

          <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">最新训练</div>
                <div className="mt-2 text-lg text-neutral-900 dark:text-white">
                  {latestTrainingJob ? trainingStatusLabel(latestTrainingJob.status) : "暂无训练作业"}
                </div>
              </div>
              {latestTrainingJob ? <Badge>{latestTrainingJob.progressPercent}%</Badge> : null}
            </div>

            {latestTrainingJob ? (
              <>
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-white/10">
                  <div className="h-full rounded-full bg-neutral-900 dark:bg-white" style={{ width: `${latestTrainingJob.progressPercent}%` }} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-neutral-500">mAP50</div>
                    <div className="mt-1 text-neutral-900 dark:text-white">{formatMetric(latestTrainingJob.metrics.mAP50)}</div>
                  </div>
                  <div>
                    <div className="text-neutral-500">mAP50-95</div>
                    <div className="mt-1 text-neutral-900 dark:text-white">{formatMetric(latestTrainingJob.metrics.mAP50_95)}</div>
                  </div>
                  <div>
                    <div className="text-neutral-500">Precision</div>
                    <div className="mt-1 text-neutral-900 dark:text-white">{formatMetric(latestTrainingJob.metrics.precision)}</div>
                  </div>
                  <div>
                    <div className="text-neutral-500">Recall</div>
                    <div className="mt-1 text-neutral-900 dark:text-white">{formatMetric(latestTrainingJob.metrics.recall)}</div>
                  </div>
                </div>
                {latestTrainingJob.error ? <div className="mt-4 text-sm text-red-600 dark:text-red-300">{latestTrainingJob.error}</div> : null}
                {latestTrainingJob.artifacts.length > 0 ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {latestTrainingJob.artifacts.map((artifact) => (
                      <Button
                        key={artifact.id}
                        variant="secondary"
                        className="max-w-full"
                        onClick={() => {
                          if (!token) return;
                          void downloadWithToken(artifact.downloadUrl, token, artifact.filename);
                        }}
                      >
                        <Download className="mr-2 h-4 w-4" />
                        <span className="truncate">{artifact.filename}</span>
                      </Button>
                    ))}
                  </div>
                ) : null}
                <div className="mt-4 flex justify-end border-t border-neutral-200 pt-4 dark:border-white/10">
                  <Button
                    variant="ghost"
                    className="text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-300 dark:hover:bg-red-950/30 dark:hover:text-red-100"
                    disabled={deletingTrainingJobId === latestTrainingJob.id}
                    onClick={() => void removeTrainingJob(latestTrainingJob)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {deletingTrainingJobId === latestTrainingJob.id ? "删除中..." : "删除任务"}
                  </Button>
                </div>
              </>
            ) : (
              <div className="mt-4 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                训练作业会先生成 YOLO 数据包，再由已注册的训练 worker 拉取执行。
              </div>
            )}
          </div>
        </div>

        {latestTrainingJob ? (
          <>
            <TrainingResultsPanel job={latestTrainingJob} token={token} />
            <TrainingModelTestPanel job={latestTrainingJob} token={token} />
          </>
        ) : null}
      </SectionCard>
      ) : null}

      {/* Batch Tasks Drawer */}
      {isTasksDrawerOpen ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-sm" onClick={() => setIsTasksDrawerOpen(false)}>
          <div className="flex h-full w-full max-w-lg flex-col bg-white dark:bg-neutral-950" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4 dark:border-white/10">
              <div className="flex items-center gap-3">
                <ClipboardList className="h-5 w-5 text-neutral-500" />
                <h3 className="text-lg text-neutral-900 dark:text-white">批次任务</h3>
                <span className="text-xs text-neutral-400">{dataset.tasks.length} 个任务</span>
              </div>
              <button type="button" onClick={() => setIsTasksDrawerOpen(false)} className="rounded-full p-1 hover:bg-neutral-100 dark:hover:bg-white/10">
                <X className="h-5 w-5 text-neutral-500" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              <div className="space-y-3">
                {dataset.tasks.length === 0 ? (
                  <div className="text-sm text-neutral-500">暂无批次任务</div>
                ) : (
                  dataset.tasks.map((task) => (
                    <div key={task.id} className="rounded-[22px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/[0.03]">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap gap-2">
                            <Badge>{task.taskType}</Badge>
                            <Badge>{task.status}</Badge>
                          </div>
                          <div className="mt-3 text-lg text-neutral-900 dark:text-white">{task.taskName}</div>
                          <div className="mt-1 text-sm text-neutral-500">{task.subject}</div>
                        </div>
                        {(task.status === "paused" || task.status === "failed") && token ? (
                          <Button
                            variant="secondary"
                            onClick={() => {
                              void retryDatasetTask(dataset.id, task.id, token)
                                .then((response) => setDataset(response.dataset))
                                .catch((error) => setActionError((error as Error).message));
                            }}
                          >
                            <Loader className="mr-2 h-4 w-4" />
                            重试
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-4 h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-white/10">
                        <div className="h-full rounded-full bg-neutral-900 dark:bg-white" style={{ width: `${task.progressPercent}%` }} />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-4 text-xs text-neutral-500">
                        <span>{task.imagesGenerated} / {task.imageCount}</span>
                        <span>{formatCurrency(task.spentCost)}</span>
                        <span>{formatDate(task.updatedAt)}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Tools Drawer */}
      {isToolsDrawerOpen ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-sm" onClick={() => setIsToolsDrawerOpen(false)}>
          <div className="flex h-full w-full max-w-lg flex-col bg-white dark:bg-neutral-950" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4 dark:border-white/10">
              <div className="flex items-center gap-3">
                <Layers className="h-5 w-5 text-neutral-500" />
                <h3 className="text-lg text-neutral-900 dark:text-white">数据集功能</h3>
              </div>
              <button type="button" onClick={() => setIsToolsDrawerOpen(false)} className="rounded-full p-1 hover:bg-neutral-100 dark:hover:bg-white/10">
                <X className="h-5 w-5 text-neutral-500" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              <div className="space-y-4">
                <div className="rounded-[22px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/[0.03]">
                  <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">自动标注</div>
                  <div className="mt-3 text-lg text-neutral-900 dark:text-white">
                    {annotationRunning ? "运行中" : annotationStatus === "completed" ? "已完成" : "待执行"}
                  </div>
                  <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                    对当前样本池执行自动标注，默认阈值 {confidenceThreshold.toFixed(2)}。
                  </div>
                  <div className="mt-4">
                    <Button
                      variant="secondary"
                      onClick={() => { setIsToolsDrawerOpen(false); openAnnotationModal(); }}
                      disabled={dataset.imageCount === 0 || annotationRunning}
                    >
                      <Tag className="mr-2 h-4 w-4" />
                      自动标注
                    </Button>
                  </div>
                </div>

                <div className="rounded-[22px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/[0.03]">
                  <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">导出</div>
                  <div className="mt-3 text-lg text-neutral-900 dark:text-white">
                    {latestExport ? `v${latestExport.version} · ${String(latestExport.status)}` : "未创建导出包"}
                  </div>
                  <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                    当前保留 {dataset.selectedCount} 张样本，可导出为 {exportFormat.toUpperCase()} 数据集。
                  </div>
                  <div className="mt-4 flex flex-wrap gap-3">
                    <Button
                      variant="secondary"
                      onClick={() => { setIsToolsDrawerOpen(false); openExportModal(); }}
                      disabled={dataset.selectedCount === 0}
                    >
                      <Download className="mr-2 h-4 w-4" />
                      导出
                    </Button>
                    {latestExport && latestExport.status === "ready" ? (
                      <Button
                        onClick={() => {
                          if (!token) return;
                          void downloadWithToken(latestExport.downloadUrl, token, `${dataset.name}-${latestExport.version}.zip`);
                        }}
                      >
                        <Download className="mr-2 h-4 w-4" />
                        下载最新包
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <SectionCard>
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">样本池</div>
              <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">统一筛选、标注和导出</h3>
              <div className="mt-2 text-sm text-neutral-500">
                当前显示 {filteredImages.length} / {imagesTotal} 张，显示范围内已保留 {filteredSelectedCount} 张，已标注 {filteredAnnotatedCount} 张，未标注 {filteredUnannotatedCount} 张，当前范围勾选待删 {filteredDeleteSelectionCount} 张
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex flex-wrap items-center gap-2 rounded-full border border-neutral-200 bg-neutral-50 p-1 dark:border-white/10 dark:bg-white/[0.03]">
                <span className="px-3 text-xs text-neutral-500">保留状态</span>
                <Button
                  variant="secondary"
                  onClick={() => applySamplePoolRetention("all")}
                  disabled={(dataset?.imageCount ?? 0) === 0 || unretainedImageCount === 0}
                >
                  <CheckSquare className="mr-2 h-4 w-4" />
                  全部保留
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => applySamplePoolRetention("invert")}
                  disabled={(dataset?.imageCount ?? 0) === 0}
                >
                  <FlipHorizontal2 className="mr-2 h-4 w-4" />
                  反向保留
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => applySamplePoolRetention("none")}
                  disabled={(dataset?.imageCount ?? 0) === 0 || retainedImageCount === 0}
                >
                  <Square className="mr-2 h-4 w-4" />
                  全部不保留
                </Button>
                <Button
                  variant="secondary"
                  onClick={retainUnannotatedSamplePoolImages}
                  disabled={unretainedUnannotatedImageCount === 0}
                >
                  <ListChecks className="mr-2 h-4 w-4" />
                  保留未标注 {unretainedUnannotatedImageCount}
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2 rounded-full border border-red-100 bg-red-50/60 p-1 dark:border-red-400/20 dark:bg-red-500/5">
                <span className="px-3 text-xs text-red-600 dark:text-red-200">删除勾选</span>
                <Button
                  variant="secondary"
                  onClick={selectFilteredForDelete}
                  disabled={filteredImages.length === 0 || isAnyImporting || deletingImageIds.length > 0}
                >
                  <CheckSquare className="mr-2 h-4 w-4" />
                  勾选当前
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setDeleteSelectionIds([])}
                  disabled={deleteSelectionCount === 0 || deletingImageIds.length > 0}
                >
                  <X className="mr-2 h-4 w-4" />
                  清除勾选
                </Button>
                <Button
                  variant="secondary"
                  className="border-red-200 text-red-700 hover:border-red-300 hover:bg-red-50 dark:border-red-400/30 dark:text-red-200 dark:hover:border-red-300/40 dark:hover:bg-red-500/10"
                  onClick={removeDeleteSelection}
                  disabled={deleteSelectionCount === 0 || deletingImageIds.length > 0}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {deletingImageIds.length > 0 ? "删除中..." : `删除勾选 ${deleteSelectionCount}`}
                </Button>
              </div>
            </div>
        </div>

        <div className="mt-5 space-y-4">
            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">来源</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSamplePoolSourceFilter("")}
                  aria-pressed={samplePoolSourceFilter === ""}
                  className={`rounded-full border px-3 py-1.5 text-sm transition ${
                    samplePoolSourceFilter === ""
                      ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                      : "border-neutral-200 bg-neutral-100 text-neutral-600 hover:border-neutral-400 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300 dark:hover:border-white/30"
                  }`}
                >
                  全部 {dataset?.imageCount ?? 0}
                </button>
                {samplePoolSourceOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setSamplePoolSourceFilter(option.value)}
                    aria-pressed={samplePoolSourceFilter === option.value}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      samplePoolSourceFilter === option.value
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 bg-neutral-100 text-neutral-600 hover:border-neutral-400 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300 dark:hover:border-white/30"
                    }`}
                  >
                    {option.label} {samplePoolSourceCounts[option.value] ?? 0}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">Class</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSamplePoolClassFilter("")}
                  className={`rounded-full border px-3 py-1.5 text-sm transition ${
                    samplePoolClassFilter === ""
                      ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                      : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                  }`}
                >
                  全部 {dataset?.imageCount ?? 0}
                </button>
                {dataset.categories.map((category) => (
                  <button
                    key={category}
                    type="button"
                    onClick={() => setSamplePoolClassFilter(category)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      samplePoolClassFilter === category
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                    }`}
                  >
                    {category} {samplePoolClassCounts[category] ?? 0}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">Split</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSamplePoolSplitFilter("")}
                  className={`rounded-full border px-3 py-1.5 text-sm transition ${
                    samplePoolSplitFilter === ""
                      ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                      : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                  }`}
                >
                  全部 {dataset?.imageCount ?? 0}
                </button>
                {samplePoolSplitOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setSamplePoolSplitFilter(option.value)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      samplePoolSplitFilter === option.value
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                    }`}
                  >
                    {option.label} {samplePoolSplitCounts[option.value] ?? 0}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">Annotation</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSamplePoolAnnotationFilter("")}
                  className={`rounded-full border px-3 py-1.5 text-sm transition ${
                    samplePoolAnnotationFilter === ""
                      ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                      : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                  }`}
                >
                  全部 {dataset?.imageCount ?? 0}
                </button>
                {samplePoolAnnotationOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setSamplePoolAnnotationFilter(option.value)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      samplePoolAnnotationFilter === option.value
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                    }`}
                  >
                    {option.label} {samplePoolAnnotationCounts[option.value] ?? 0}
                  </button>
                ))}
              </div>
            </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {filteredImages.map((image) => {
              const isQueuedForDelete = deleteSelectionIdSet.has(image.id);
              const isDeletingImage = deletingImageIdSet.has(image.id);
              const annotated = isImageAnnotated(image);
              const split = (image.split ?? (image.selected ? "train" : "unselected")) as SamplePoolSplit;
              return (
                <article
                  key={image.id}
                  className={`group overflow-hidden rounded-[24px] border text-left transition ${
                    isQueuedForDelete
                      ? "border-red-300 bg-red-50 dark:border-red-300/50 dark:bg-red-500/10"
                      : image.selected
                        ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.03]"
                        : "border-neutral-200 bg-white opacity-80 dark:border-white/10 dark:bg-black/20"
                  } ${isDeletingImage ? "opacity-50" : ""}`}
                >
                  <div className="relative aspect-square overflow-hidden">
                    <button
                      type="button"
                      className="absolute inset-0 text-left"
                      onClick={() => openPreview(image.id)}
                      disabled={isDeletingImage}
                    >
                      <AuthImage src={image.previewSvg} alt={image.promptText} className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
                      <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_35%,rgba(10,10,10,0.72))]" />
                      <div className="absolute bottom-3 left-3 right-3 text-white">
                        <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em]">
                          <span>{samplePoolSourceLabel(image.sourceType)}</span>
                          <span>{samplePoolSplitLabel(split)}</span>
                          <span>#{image.ordinal}</span>
                          <span className={annotated ? "text-lime-200" : "text-amber-200"}>
                            {samplePoolAnnotationLabel(image)}
                          </span>
                        </div>
                        <div className="mt-2 line-clamp-2 text-sm">{image.promptText}</div>
                      </div>
                    </button>
                    <label
                      className={`absolute left-3 top-3 z-10 flex h-9 w-9 items-center justify-center rounded-full border transition ${
                        isQueuedForDelete
                          ? "border-red-300 bg-red-600 text-white"
                          : "border-white/60 bg-black/45 text-white hover:bg-black/65"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isQueuedForDelete}
                        onChange={() => toggleDeleteSelection(image.id)}
                        disabled={deletingImageIds.length > 0}
                        aria-label={`勾选删除样本 #${image.ordinal}`}
                        className="h-4 w-4 rounded border-white/60"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => void applySelection({ mode: "single", image_id: image.id, selected: !image.selected })}
                      disabled={isDeletingImage}
                      className={`absolute right-3 top-3 z-10 rounded-full px-3 py-1 text-xs ${
                        image.selected ? "bg-white text-neutral-900" : "bg-black/65 text-white"
                      }`}
                    >
                      {image.selected ? "已保留" : "不保留"}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeDatasetImage(image)}
                      disabled={deletingImageIds.length > 0}
                      aria-label={`删除样本 #${image.ordinal}`}
                      className="absolute right-3 top-12 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-red-600 text-white shadow-lg transition hover:bg-red-500 disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </article>
              );
            })}
            {filteredImages.length === 0 && !isLoadingFirstPage ? (
              <div className="col-span-full rounded-[22px] border border-dashed border-neutral-200 px-5 py-8 text-sm text-neutral-500 dark:border-white/10">
                当前筛选条件下没有样本。
              </div>
            ) : null}
            {filteredImages.length === 0 && isLoadingFirstPage ? (
              <div className="col-span-full rounded-[22px] border border-dashed border-neutral-200 px-5 py-8 text-sm text-neutral-500 dark:border-white/10">
                正在加载样本...
              </div>
            ) : null}
            {hasMoreImages ? (
              <div ref={sentinelRef} className="col-span-full flex items-center justify-center gap-2 py-4 text-sm text-neutral-500">
                {isLoadingMore ? <Loader className="h-4 w-4 animate-spin" /> : null}
                {isLoadingMore ? "加载更多..." : "向下滚动加载更多"}
              </div>
            ) : filteredImages.length > 0 ? (
              <div className="col-span-full py-3 text-center text-xs text-neutral-400">已加载全部 {filteredImages.length} 张</div>
            ) : null}
        </div>
      </SectionCard>

      {isImportModalOpen ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 px-4 py-6 backdrop-blur-sm"
          onClick={() => {
            if (!isAnyImporting) {
              setIsImportModalOpen(false);
            }
          }}
        >
          <SectionCard
            className="relative z-50 max-h-[calc(100vh-3rem)] w-full max-w-4xl overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-neutral-500">
                  <Upload className="h-4 w-4" />
                  Import
                </div>
                <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">导入数据集</h3>
                <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                  上传视频按帧抽取底库图片，也可以继续使用 ZIP 或 Roboflow 导入。
                </p>
              </div>
              <button
                type="button"
                aria-label="关闭导入面板"
                onClick={() => setIsImportModalOpen(false)}
                disabled={isAnyImporting}
                className="rounded-full p-1 hover:bg-neutral-100 disabled:opacity-50 dark:hover:bg-white/10"
              >
                <X className="h-5 w-5 text-neutral-500" />
              </button>
            </div>

            <div
              className="mt-6 grid gap-2 rounded-[20px] border border-neutral-200 bg-neutral-100 p-1 dark:border-white/10 dark:bg-white/[0.03] sm:grid-cols-3"
              role="tablist"
              aria-label="导入方式"
            >
              {importTabOptions.map((option) => {
                const Icon = option.icon;
                const active = activeImportTab === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="tab"
                    id={`import-tab-${option.value}`}
                    aria-selected={active}
                    aria-controls={`import-panel-${option.value}`}
                    className={`inline-flex items-center justify-center gap-2 rounded-[16px] px-4 py-3 text-sm font-medium transition disabled:opacity-60 ${
                      active
                        ? "bg-white text-neutral-950 shadow-sm dark:bg-neutral-100 dark:text-neutral-950"
                        : "text-neutral-500 hover:bg-white/70 hover:text-neutral-900 dark:text-neutral-300 dark:hover:bg-white/[0.06] dark:hover:text-white"
                    }`}
                    onClick={() => setActiveImportTab(option.value)}
                    disabled={isAnyImporting}
                  >
                    <Icon className="h-4 w-4" />
                    {option.label}
                  </button>
                );
              })}
            </div>

            <div className="mt-5">
              {activeImportTab === "video" ? (
                <div
                  className="rounded-[22px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/[0.03]"
                  role="tabpanel"
                  id="import-panel-video"
                  aria-labelledby="import-tab-video"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-white">
                        <FileVideo className="h-4 w-4 text-neutral-500" />
                        本地视频
                      </div>
                      <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                        按固定帧数或固定秒数抽取图片，抽出的帧会直接加入当前数据集样本池。
                      </p>
                    </div>
                    <Button
                      className="w-full justify-center sm:w-auto"
                      onClick={() => videoInputRef.current?.click()}
                      disabled={isAnyImporting}
                    >
                      <Upload className="mr-2 h-4 w-4" />
                      {selectedVideoFile ? "更换视频" : "选择视频"}
                    </Button>
                  </div>

                  <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="space-y-2 sm:col-span-2">
                        <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">抽帧方式</span>
                        <div className={`${segmentedGroupClasses} w-full max-w-md`}>
                          {([
                            { value: "frames", label: "按帧数" },
                            { value: "seconds", label: "按秒数" },
                          ] as const).map((option) => (
                            <button
                              key={option.value}
                              type="button"
                              className={segmentedButtonClasses(videoFrameIntervalMode === option.value, "flex-1")}
                              onClick={() => setVideoFrameIntervalMode(option.value)}
                              disabled={isAnyImporting}
                            >
                              {option.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <label className="space-y-2">
                        <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">
                          {videoFrameIntervalMode === "seconds" ? "抽帧间隔（秒）" : "抽帧间隔（帧）"}
                        </span>
                        {videoFrameIntervalMode === "seconds" ? (
                          <Input
                            type="number"
                            min={0.01}
                            max={3600}
                            step={0.1}
                            value={videoFrameIntervalSeconds}
                            onChange={(event) => setVideoFrameIntervalSeconds(Number(event.target.value) || 0)}
                            disabled={isAnyImporting}
                          />
                        ) : (
                          <Input
                            type="number"
                            min={1}
                            max={10000}
                            value={videoFrameInterval}
                            onChange={(event) => setVideoFrameInterval(Number(event.target.value) || 0)}
                            disabled={isAnyImporting}
                          />
                        )}
                        <span className="block text-xs text-neutral-500">{videoFrameIntervalHint}</span>
                      </label>
                      <label className="space-y-2">
                        <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">文件名前缀</span>
                        <Input
                          value={videoFilenamePrefix}
                          onChange={(event) => setVideoFilenamePrefix(event.target.value)}
                          placeholder="frame"
                          disabled={isAnyImporting}
                        />
                        <span className="block text-xs text-neutral-500">输出文件名格式：{videoOutputExample}</span>
                      </label>
                    </div>

                    <div className="rounded-[18px] border border-neutral-200 bg-white/75 p-4 dark:border-white/10 dark:bg-black/20">
                      <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">已选视频</div>
                      <div className="mt-2 rounded-[14px] border border-neutral-200 px-3 py-2 text-sm text-neutral-700 dark:border-white/10 dark:text-neutral-200">
                        {selectedVideoFile ? (
                          <>
                            <div className="truncate">{selectedVideoFile.name}</div>
                            <div className="mt-1 text-xs text-neutral-500">{selectedVideoFileSize}</div>
                          </>
                        ) : (
                          <span className="text-neutral-500">尚未选择视频</span>
                        )}
                      </div>

                      <div className="mt-5 text-[11px] uppercase tracking-[0.24em] text-neutral-500">输出格式</div>
                      <div className={`${segmentedGroupClasses} mt-3 w-full`}>
                        {(["jpg", "png"] as const).map((format) => (
                          <button
                            key={format}
                            type="button"
                            className={segmentedButtonClasses(videoOutputFormat === format, "flex-1")}
                            onClick={() => setVideoOutputFormat(format)}
                            disabled={isAnyImporting}
                          >
                            {format.toUpperCase()}
                          </button>
                        ))}
                      </div>
                      {videoOutputFormat === "jpg" ? (
                        <label className="mt-4 block space-y-2">
                          <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">
                            JPEG 质量 {videoJpegQuality}
                          </span>
                          <input
                            type="range"
                            min={1}
                            max={100}
                            value={videoJpegQuality}
                            onChange={(event) => setVideoJpegQuality(Number(event.target.value) || 0)}
                            disabled={isAnyImporting}
                            className="h-2 w-full accent-neutral-900 dark:accent-white"
                          />
                        </label>
                      ) : (
                        <div className="mt-4 rounded-[14px] border border-neutral-200 px-3 py-2 text-xs text-neutral-500 dark:border-white/10">
                          PNG 会保留无损帧图像，文件体积通常更大。
                        </div>
                      )}

                      <div className="mt-5 text-[11px] uppercase tracking-[0.24em] text-neutral-500">图片尺寸</div>
                      <div className={`${segmentedGroupClasses} mt-3 flex w-full flex-wrap rounded-[16px]`}>
                        {videoTargetSizeOptions.map((option) => (
                          <button
                            key={option.value}
                            type="button"
                            className={segmentedButtonClasses(videoTargetSize === option.value, "min-w-[70px] flex-1 px-3 py-1.5 text-xs")}
                            onClick={() => setVideoTargetSize(option.value)}
                            disabled={isAnyImporting}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                      <div className="mt-2 text-xs text-neutral-500">长边超过目标时等比缩小</div>
                      <Button
                        type="button"
                        className="mt-5 w-full"
                        onClick={() => void handleVideoImport()}
                        disabled={!selectedVideoFile || isAnyImporting}
                      >
                        {isImportingVideo ? <Loader className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                        {isImportingVideo ? "抽帧中..." : "开始抽帧"}
                      </Button>
                    </div>
                  </div>
                </div>
              ) : null}

              {activeImportTab === "zip" ? (
                <div
                  className="rounded-[22px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]"
                  role="tabpanel"
                  id="import-panel-zip"
                  aria-labelledby="import-tab-zip"
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-white">
                        <Upload className="h-4 w-4 text-neutral-500" />
                        本地 ZIP
                      </div>
                      <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                        自动识别 YOLO、COCO、Pascal VOC，也兼容只含图片的 ZIP。
                      </p>
                    </div>
                    <Button
                      variant="secondary"
                      className="w-full justify-center sm:w-auto"
                      onClick={() => archiveInputRef.current?.click()}
                      disabled={isAnyImporting}
                    >
                      <Upload className="mr-2 h-4 w-4" />
                      {isImporting ? "导入中..." : "选择 ZIP"}
                    </Button>
                  </div>
                </div>
              ) : null}

              {activeImportTab === "roboflow" ? (
                <div
                  className="rounded-[22px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]"
                  role="tabpanel"
                  id="import-panel-roboflow"
                  aria-labelledby="import-tab-roboflow"
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-white">
                    <Download className="h-4 w-4 text-neutral-500" />
                    Roboflow
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2 sm:col-span-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">加密连接</span>
                        <button type="button" className="text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-white" onClick={() => setShowRoboflowConnectionForm((current) => !current)}>
                          {showRoboflowConnectionForm ? "收起" : "添加连接"}
                        </button>
                      </div>
                      <div className="flex gap-2">
                        <Select
                          className="flex-1"
                          value={selectedRoboflowConnectionId}
                          onChange={(event) => setSelectedRoboflowConnectionId(event.target.value)}
                          disabled={isLoadingRoboflowConnections || isImportingRoboflow}
                        >
                          <option value="">{isLoadingRoboflowConnections ? "读取连接中..." : "选择 Roboflow 连接"}</option>
                          {roboflowConnections.map((connection) => (
                            <option key={connection.id} value={connection.id}>{connection.name} · {connection.status === "valid" ? "已验证" : "需验证"}</option>
                          ))}
                        </Select>
                        <Button variant="secondary" onClick={() => void removeSelectedRoboflowConnection()} disabled={!selectedRoboflowConnectionId || isImportingRoboflow}>删除</Button>
                      </div>
                    </div>
                    {showRoboflowConnectionForm ? (
                      <div className="grid gap-3 rounded-2xl border border-dashed border-neutral-300 p-4 sm:col-span-2 sm:grid-cols-2 dark:border-white/15">
                        <label className="space-y-2">
                          <span className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">连接名称</span>
                          <Input value={newRoboflowConnectionName} onChange={(event) => setNewRoboflowConnectionName(event.target.value)} placeholder="团队 Roboflow" />
                        </label>
                        <label className="space-y-2">
                          <span className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">API Key</span>
                          <Input type="password" value={newRoboflowApiKey} onChange={(event) => setNewRoboflowApiKey(event.target.value)} placeholder="只在保存时发送" autoComplete="off" />
                        </label>
                        <Button className="justify-center sm:col-span-2" onClick={() => void saveRoboflowConnection()} disabled={isSavingRoboflowConnection || !newRoboflowApiKey.trim() || !newRoboflowConnectionName.trim()}>
                          {isSavingRoboflowConnection ? "验证并保存中..." : "验证并保存连接"}
                        </Button>
                      </div>
                    ) : null}
                    <label className="space-y-2">
                      <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Workspace</span>
                      <Input
                        value={roboflowWorkspace}
                        onChange={(event) => setRoboflowWorkspace(event.target.value)}
                        placeholder="workspace-id"
                        disabled={isImportingRoboflow}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Project</span>
                      <Input
                        value={roboflowProject}
                        onChange={(event) => setRoboflowProject(event.target.value)}
                        placeholder="project-id"
                        disabled={isImportingRoboflow}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Version</span>
                      <Input
                        value={roboflowVersion}
                        onChange={(event) => setRoboflowVersion(event.target.value)}
                        placeholder="version"
                        disabled={isImportingRoboflow}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">Format</span>
                      <Input value="YOLOv8" disabled />
                    </label>
                  </div>
                  <Button
                    className="mt-4 w-full justify-center"
                    onClick={() => void handleRoboflowImport()}
                    disabled={
                      isAnyImporting ||
                      !selectedRoboflowConnectionId ||
                      !roboflowWorkspace.trim() ||
                      !roboflowProject.trim() ||
                      !roboflowVersion.trim()
                    }
                  >
                    <Download className="mr-2 h-4 w-4" />
                    {isImportingRoboflow ? "下载导入中..." : "从 Roboflow 导入"}
                  </Button>
                </div>
              ) : null}
            </div>
          </SectionCard>
        </div>
      ) : null}
	
	      {isAugmentationModalOpen ? (
	        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 px-4 py-6 backdrop-blur-sm"
          onClick={() => {
            if (!isCreatingAugmentationTask) {
              setIsAugmentationModalOpen(false);
            }
          }}
        >
          <SectionCard
            className="relative z-50 w-full max-w-4xl max-h-[90vh] overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="absolute right-5 top-5 rounded-full bg-neutral-100 p-2 text-neutral-700 transition hover:bg-neutral-200 dark:bg-white/10 dark:text-white dark:hover:bg-white/20"
              onClick={() => setIsAugmentationModalOpen(false)}
              disabled={isCreatingAugmentationTask}
            >
              <X className="h-4 w-4" />
            </button>

            <div className="pr-12">
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Augmentation</div>
              <h3 className="mt-2 text-3xl text-neutral-900 dark:text-white">增强</h3>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                增强批次会基于当前保留的原始样本生成新的变体，并自动写回同一个数据集样本池。
              </p>
            </div>

            <div className="mt-6 grid gap-6 md:grid-cols-2">
              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">增强倍率</div>
                <Input
                  type="number"
                  min={2}
                  max={20}
                  value={multiplier}
                  onChange={(event) => setMultiplier(Number(event.target.value))}
                />
              </div>
              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">可增强原始样本</div>
                <div className="rounded-[20px] border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm text-neutral-700 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-200">
                  {selectedOriginalCount} 张
                </div>
              </div>
            </div>

            <div className="mt-5">
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">增强方法</div>
              <div className="flex flex-wrap gap-2">
                {augmentationOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleAugmentationMethod(option.value)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      augmentationMethods.includes(option.value)
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {augmentationMethods.length > 0 ? (
              <div className="mt-5 space-y-4">
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">参数调节</div>

                <div className="grid gap-4 sm:grid-cols-2">
                  {augmentationMethods.includes("flip") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">翻转模式</div>
                      <div className="flex flex-wrap gap-2">
                        {(["random", "horizontal", "vertical"] as const).map((mode) => (
                          <button
                            key={mode}
                            type="button"
                            onClick={() => setAugmentationSettings((s) => ({ ...s, flip: { mode } }))}
                            className={`rounded-full border px-3 py-1 text-sm transition ${
                              augmentationSettings.flip.mode === mode
                                ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                                : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                            }`}
                          >
                            {mode === "random" ? "随机" : mode === "horizontal" ? "水平" : "垂直"}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {augmentationMethods.includes("rotate") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        最大旋转角度 <span className="text-neutral-400">{augmentationSettings.rotate.max_angle}°</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={20}
                        step={0.5}
                        value={augmentationSettings.rotate.max_angle}
                        onChange={(e) => setAugmentationSettings((s) => ({ ...s, rotate: { max_angle: Number(e.target.value) } }))}
                        className="w-full accent-neutral-900 dark:accent-white"
                      />
                    </div>
                  ) : null}

                  {augmentationMethods.includes("crop") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        裁切范围 <span className="text-neutral-400">{augmentationSettings.crop.min_scale} – {augmentationSettings.crop.max_scale}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min={0.6}
                          max={0.98}
                          step={0.01}
                          value={augmentationSettings.crop.min_scale}
                          onChange={(e) => setAugmentationSettings((s) => ({ ...s, crop: { ...s.crop, min_scale: Number(e.target.value) } }))}
                          className="flex-1 accent-neutral-900 dark:accent-white"
                        />
                        <input
                          type="range"
                          min={0.6}
                          max={0.99}
                          step={0.01}
                          value={augmentationSettings.crop.max_scale}
                          onChange={(e) => setAugmentationSettings((s) => ({ ...s, crop: { ...s.crop, max_scale: Number(e.target.value) } }))}
                          className="flex-1 accent-neutral-900 dark:accent-white"
                        />
                      </div>
                    </div>
                  ) : null}

                  {augmentationMethods.includes("color_jitter") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        颜色抖动强度 <span className="text-neutral-400">{augmentationSettings.color_jitter.strength}</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={0.4}
                        step={0.01}
                        value={augmentationSettings.color_jitter.strength}
                        onChange={(e) => setAugmentationSettings((s) => ({ ...s, color_jitter: { strength: Number(e.target.value) } }))}
                        className="w-full accent-neutral-900 dark:accent-white"
                      />
                    </div>
                  ) : null}

                  {augmentationMethods.includes("blur") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        最大模糊半径 <span className="text-neutral-400">{augmentationSettings.blur.max_radius}</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={4}
                        step={0.1}
                        value={augmentationSettings.blur.max_radius}
                        onChange={(e) => setAugmentationSettings((s) => ({ ...s, blur: { max_radius: Number(e.target.value) } }))}
                        className="w-full accent-neutral-900 dark:accent-white"
                      />
                    </div>
                  ) : null}

                  {augmentationMethods.includes("noise") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        最大噪声强度 <span className="text-neutral-400">{augmentationSettings.noise.max_sigma}</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={40}
                        step={1}
                        value={augmentationSettings.noise.max_sigma}
                        onChange={(e) => setAugmentationSettings((s) => ({ ...s, noise: { max_sigma: Number(e.target.value) } }))}
                        className="w-full accent-neutral-900 dark:accent-white"
                      />
                    </div>
                  ) : null}

                  {augmentationMethods.includes("occlusion") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        遮挡比例 <span className="text-neutral-400">{augmentationSettings.occlusion.min_ratio} – {augmentationSettings.occlusion.max_ratio}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min={0.05}
                          max={0.35}
                          step={0.01}
                          value={augmentationSettings.occlusion.min_ratio}
                          onChange={(e) => setAugmentationSettings((s) => ({ ...s, occlusion: { ...s.occlusion, min_ratio: Number(e.target.value) } }))}
                          className="flex-1 accent-neutral-900 dark:accent-white"
                        />
                        <input
                          type="range"
                          min={0.05}
                          max={0.4}
                          step={0.01}
                          value={augmentationSettings.occlusion.max_ratio}
                          onChange={(e) => setAugmentationSettings((s) => ({ ...s, occlusion: { ...s.occlusion, max_ratio: Number(e.target.value) } }))}
                          className="flex-1 accent-neutral-900 dark:accent-white"
                        />
                      </div>
                    </div>
                  ) : null}

                  {augmentationMethods.includes("perspective") ? (
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                        最大透视畸变 <span className="text-neutral-400">{augmentationSettings.perspective.max_warp}</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={0.15}
                        step={0.005}
                        value={augmentationSettings.perspective.max_warp}
                        onChange={(e) => setAugmentationSettings((s) => ({ ...s, perspective: { max_warp: Number(e.target.value) } }))}
                        className="w-full accent-neutral-900 dark:accent-white"
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]">
              <div>
                <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">批次预期</div>
                <div className="mt-1 text-lg text-neutral-900 dark:text-white">
                  预计新增 {selectedOriginalCount * multiplier} 张增强样本
                </div>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="secondary"
                  onClick={() => setIsAugmentationModalOpen(false)}
                  disabled={isCreatingAugmentationTask}
                >
                  取消
                </Button>
                <Button
                  onClick={() => void createAugmentationTask()}
                  disabled={isCreatingAugmentationTask || augmentationMethods.length === 0 || selectedOriginalCount === 0}
                >
                  <Wand2 className="mr-2 h-4 w-4" />
                  {isCreatingAugmentationTask ? "处理中..." : "增强"}
                </Button>
              </div>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {isAnnotationModalOpen ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 px-4 py-6 backdrop-blur-sm"
          onClick={() => {
            if (!isSubmittingAnnotation) {
              setIsAnnotationModalOpen(false);
            }
          }}
        >
          <SectionCard className="relative z-50 w-full max-w-xl" onClick={(event) => event.stopPropagation()}>
            <button
              type="button"
              className="absolute right-5 top-5 rounded-full bg-neutral-100 p-2 text-neutral-700 transition hover:bg-neutral-200 dark:bg-white/10 dark:text-white dark:hover:bg-white/20"
              onClick={() => setIsAnnotationModalOpen(false)}
              disabled={isSubmittingAnnotation}
            >
              <X className="h-4 w-4" />
            </button>

            <div className="pr-12">
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Auto Annotation</div>
              <h3 className="mt-2 text-3xl text-neutral-900 dark:text-white">自动标注</h3>
              <p className="mt-3 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                对当前数据集样本池执行自动标注，结果会直接写入每张图片的标注信息。
              </p>
            </div>

            <div className="mt-6 grid gap-6 md:grid-cols-[minmax(0,1fr)_220px]">
              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">置信度阈值</div>
                <Input
                  type="number"
                  min={0.3}
                  max={0.95}
                  step={0.05}
                  value={confidenceThreshold}
                  onChange={(event) => setConfidenceThreshold(Number(event.target.value))}
                />
              </div>

              <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]">
                <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">范围</div>
                <div className="mt-3 text-lg text-neutral-900 dark:text-white">{dataset.imageCount} 张样本</div>
                <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                  当前状态：{annotationRunning ? "运行中" : annotationStatus === "completed" ? "已完成" : "待执行"}
                </div>
              </div>
            </div>

            <label className="mt-5 flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={skipAnnotated}
                onChange={() => setSkipAnnotated((current) => !current)}
                className="h-4 w-4 rounded border-neutral-300"
              />
              <span className="text-sm text-neutral-700 dark:text-neutral-300">跳过已标注的样本，仅标注未标注的图片</span>
            </label>

            <div className="mt-6 flex flex-wrap gap-3">
              <Button
                variant="secondary"
                onClick={() => setIsAnnotationModalOpen(false)}
                disabled={isSubmittingAnnotation}
              >
                取消
              </Button>
              <Button onClick={() => void runAutoAnnotation()} disabled={isSubmittingAnnotation || dataset.imageCount === 0}>
                {isSubmittingAnnotation ? "处理中..." : "自动标注"}
              </Button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {isExportModalOpen ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 px-4 py-6 backdrop-blur-sm"
          onClick={() => {
            if (!isCreatingExport) {
              setIsExportModalOpen(false);
            }
          }}
        >
          <SectionCard className="relative z-50 w-full max-w-2xl" onClick={(event) => event.stopPropagation()}>
            <button
              type="button"
              className="absolute right-5 top-5 rounded-full bg-neutral-100 p-2 text-neutral-700 transition hover:bg-neutral-200 dark:bg-white/10 dark:text-white dark:hover:bg-white/20"
              onClick={() => setIsExportModalOpen(false)}
              disabled={isCreatingExport}
            >
              <X className="h-4 w-4" />
            </button>

            <div className="pr-12">
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Export</div>
              <h3 className="mt-2 text-3xl text-neutral-900 dark:text-white">导出</h3>
              <p className="mt-3 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                选择导出格式后创建数据集压缩包，导出范围基于当前保留的样本。
              </p>
            </div>

            <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_260px]">
              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">导出格式</div>
                <div className="flex flex-wrap gap-2">
                  {exportFormatOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setExportFormat(option.value)}
                      className={`rounded-full border px-3 py-1.5 text-sm transition ${
                        exportFormat === option.value
                          ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                          : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]">
                <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">导出范围</div>
                <div className="mt-3 text-lg text-neutral-900 dark:text-white">{dataset.selectedCount} 张保留样本</div>
                <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                  最近导出：{latestExport ? `v${latestExport.version}` : "暂无"}
                </div>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              <Button
                variant="secondary"
                onClick={() => setIsExportModalOpen(false)}
                disabled={isCreatingExport}
              >
                取消
              </Button>
              <Button onClick={() => void createExportPackage()} disabled={isCreatingExport || dataset.selectedCount === 0}>
                {isCreatingExport ? "处理中..." : "导出"}
              </Button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {previewImage ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/82 px-4 py-6 backdrop-blur-sm">
          <div className="relative flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-[32px] bg-white shadow-2xl dark:bg-neutral-950 xl:flex-row">
            <button
              type="button"
              className="absolute right-5 top-5 z-10 rounded-full bg-black/10 p-2 text-neutral-900 transition hover:bg-black/20 dark:bg-white/10 dark:text-white dark:hover:bg-white/20"
              onClick={() => {
                if (confirmDiscardChanges()) {
                  setPreviewImageId(null);
                }
              }}
            >
              <X className="h-5 w-5" />
            </button>

            <div className="relative flex-1 bg-neutral-950 p-4">
              <button
                type="button"
                className="absolute left-5 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/12 p-3 text-white transition hover:bg-white/20"
                onClick={() => movePreview(-1)}
                disabled={previewIndex <= 0}
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
              <button
                type="button"
                className="absolute right-5 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/12 p-3 text-white transition hover:bg-white/20"
                onClick={() => movePreview(1)}
                disabled={previewIndex >= images.length - 1}
              >
                <ChevronRight className="h-5 w-5" />
              </button>
              <div
                ref={stageRef}
                className="relative mx-auto flex h-full max-h-[72vh] w-full max-w-[72vh] items-center justify-center overflow-hidden rounded-[28px]"
              >
                {imageViewport && imageViewport.width > 0 && imageViewport.height > 0 ? (
                  <div
                    ref={viewportRef}
                    className={`relative ${isAddingDetection ? "cursor-crosshair" : "cursor-default"}`}
                    style={{
                      width: imageViewport.width,
                      height: imageViewport.height,
                    }}
                    onMouseDown={handleStageMouseDown}
                  >
                    <AuthImage
                      src={previewImage.previewSvg}
                      alt={previewImage.promptText}
                      className="h-full w-full"
                      onLoad={(event) => {
                        const target = event.currentTarget;
                        setPreviewImageNaturalSize({
                          width: target.naturalWidth,
                          height: target.naturalHeight,
                        });
                      }}
                    />
                    <div className="pointer-events-none absolute inset-0">
                      {draftDetections.map((detection, index) => (
                        <div
                          key={`${detection.category}-${index}`}
                          className={`pointer-events-auto absolute rounded-xl border-2 ${
                            selectedDetectionIndex === index ? "border-lime-300 shadow-[0_0_0_9999px_rgba(0,0,0,0.08)]" : "border-white/90"
                          }`}
                          style={detectionStyle(detection.bbox)}
                          onMouseDown={(event) => beginDragDetection(index, event)}
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedDetectionIndex(index);
                          }}
                        >
                          <div className="absolute left-0 top-0 -translate-y-full rounded-t-lg bg-black/72 px-2 py-1 text-[11px] text-white">
                            {detection.category} · {(detection.confidence * 100).toFixed(0)}%
                          </div>
                          {(["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
                            <button
                              key={corner}
                              type="button"
                              className={`absolute h-3 w-3 rounded-full border border-white bg-black/70 ${
                                corner === "nw"
                                  ? "-left-1.5 -top-1.5"
                                  : corner === "ne"
                                    ? "-right-1.5 -top-1.5"
                                    : corner === "sw"
                                      ? "-left-1.5 -bottom-1.5"
                                      : "-right-1.5 -bottom-1.5"
                              }`}
                              onMouseDown={(event) => beginResizeDetection(index, corner, event)}
                            />
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <AuthImage
                    src={previewImage.previewSvg}
                    alt={previewImage.promptText}
                    className="h-full w-full object-contain"
                    onLoad={(event) => {
                      const target = event.currentTarget;
                      setPreviewImageNaturalSize({
                        width: target.naturalWidth,
                        height: target.naturalHeight,
                      });
                    }}
                  />
                )}
              </div>
            </div>

            <div className="w-full overflow-y-auto border-t border-neutral-200 p-6 dark:border-white/10 xl:w-[420px] xl:border-l xl:border-t-0">
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Image Inspector</div>
              <div className="mt-2 text-2xl text-neutral-900 dark:text-white">
                样本 #{previewImage.ordinal}
              </div>
              <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">{previewImage.promptText}</div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge>{samplePoolSourceLabel(previewImage.sourceType)}</Badge>
                <Badge>{previewImage.annotationStatus}</Badge>
              </div>

              <div className="mt-6 flex flex-wrap gap-3">
                <Button variant="secondary" onClick={() => setIsAddingDetection((current) => !current)}>
                  {isAddingDetection ? "取消新增框" : "新增框"}
                </Button>
                <Button onClick={() => void saveAnnotations()} disabled={isSavingAnnotations}>
                  保存标注
                </Button>
                <Button
                  variant="secondary"
                  className="border-red-200 text-red-700 hover:border-red-300 hover:bg-red-50 dark:border-red-400/30 dark:text-red-200 dark:hover:border-red-300/40 dark:hover:bg-red-500/10"
                  onClick={() => removeDatasetImage(previewImage)}
                  disabled={deletingImageIds.length > 0 || isSavingAnnotations}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  删除样本
                </Button>
              </div>

              <div className="mt-6 space-y-3">
                {draftDetections.map((detection, index) => (
                  <div
                    key={`${detection.category}-${index}`}
                    className={`rounded-[20px] border p-4 ${
                      selectedDetectionIndex === index
                        ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.04]"
                        : "border-neutral-200 bg-white dark:border-white/10 dark:bg-black/20"
                    }`}
                    onClick={() => setSelectedDetectionIndex(index)}
                  >
                    <div className="grid gap-3">
                      <Input
                        value={detection.category}
                        onChange={(event) => updateDetectionField(index, "category", event.target.value)}
                      />
                      <Input
                        type="number"
                        min={0}
                        max={1}
                        step={0.01}
                        value={detection.confidence}
                        onChange={(event) => updateDetectionField(index, "confidence", Number(event.target.value))}
                      />
                      <Button variant="secondary" onClick={() => removeDetection(index)}>
                        删除框
                      </Button>
                    </div>
                  </div>
                ))}
                {draftDetections.length === 0 ? (
                  <div className="rounded-[20px] border border-dashed border-neutral-200 p-4 text-sm text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                    当前没有检测框。可以点击“新增框”后直接在图片上拖拽创建。
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
