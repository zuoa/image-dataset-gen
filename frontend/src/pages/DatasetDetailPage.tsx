import { useEffect, useMemo, useRef, useState } from "react";
import {
  ClipboardList,
  Download,
  Layers,
  Loader,
} from "lucide-react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  List,
  Progress,
  Row,
  Space,
  Typography,
} from "antd";
import { useQueryClient } from "@tanstack/react-query";

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
  importDatasetFromRoboflow,
  importDatasetImagesArchive,
  importDatasetVideo,
  retryDatasetTask,
  updateDatasetImageAnnotations,
  updateDatasetSelection,
} from "../api/datasets";
import { PageContainer } from "../components/common/PageContainer";
import { LoadingState } from "../components/common/LoadingState";
import { StatusBadge } from "../components/common/StatusBadge";
import { DatasetHeader } from "../components/dataset/DatasetHeader";
import { DatasetMetrics } from "../components/dataset/DatasetMetrics";
import { DatasetActions } from "../components/dataset/DatasetActions";
import {
  SamplePoolFilters,
  SamplePoolGrid,
  SamplePoolToolbar,
} from "../components/dataset/SamplePool";
import { ImportModal } from "../components/dataset/ImportModal";
import { AugmentationModal } from "../components/dataset/AugmentationModal";
import { AnnotationModal } from "../components/dataset/AnnotationModal";
import { ExportModal } from "../components/dataset/ExportModal";
import { ImagePreviewModal } from "../components/dataset/ImagePreviewModal";
import { TrainingPanel } from "../components/dataset/TrainingPanel";
import { DatasetQualityPanel } from "../components/DatasetQualityPanel";
import { confirm } from "../hooks/useConfirm";
import { useDatasetImages } from "../hooks/useDatasetImages";
import { useDatasetTasks } from "../hooks/useDatasetTasks";
import { useTrainingJobs } from "../hooks/useTrainingJobs";
import { useAuthStore } from "../store/auth";
import {
  detectionsEqual,
} from "../lib/annotation";
import type {
  AugmentationMethod,
  AugmentationSettings,
  DatasetImage,
  ExternalConnection,
  ImageFilter,
  SamplePoolSource,
  SamplePoolSplit,
  TrainingJob,
} from "../lib/types";
import { formatCurrency, formatDate } from "../lib/utils";
import type {
  ExportFormat,
  ImportTab,
  VideoFrameIntervalMode,
  VideoOutputFormat,
  VideoTargetSize,
} from "../components/dataset/types";

const { Text } = Typography;

const defaultAugmentationMethods: AugmentationMethod[] = [
  "flip",
  "color_jitter",
  "blur",
];
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
  if (
    !filter.class &&
    !filter.split &&
    !filter.annotation &&
    !filter.source
  )
    return undefined;
  return filter;
}

type SamplePoolSplitFilter = "" | SamplePoolSplit;
type SamplePoolAnnotationFilter = "" | "annotated" | "unannotated";
type SamplePoolSourceFilter = "" | SamplePoolSource;

export function DatasetDetailPage() {
  const token = useAuthStore((state) => state.token);
  const { datasetId } = useParams();
  const queryClient = useQueryClient();

  const [samplePoolClassFilter, setSamplePoolClassFilter] = useState("");
  const [samplePoolSplitFilter, setSamplePoolSplitFilter] =
    useState<SamplePoolSplitFilter>("");
  const [samplePoolAnnotationFilter, setSamplePoolAnnotationFilter] =
    useState<SamplePoolAnnotationFilter>("");
  const [samplePoolSourceFilter, setSamplePoolSourceFilter] =
    useState<SamplePoolSourceFilter>("");

  const filter = useMemo(
    () =>
      buildImageFilter(
        samplePoolClassFilter,
        samplePoolSplitFilter,
        samplePoolAnnotationFilter,
        samplePoolSourceFilter,
      ),
    [
      samplePoolClassFilter,
      samplePoolSplitFilter,
      samplePoolAnnotationFilter,
      samplePoolSourceFilter,
    ],
  );

  const datasetTasksQuery = useDatasetTasks(datasetId!, filter);
  const imagesQuery = useDatasetImages(datasetId!, filter);
  const trainingJobsQuery = useTrainingJobs(datasetId!);

  const dataset = datasetTasksQuery.data?.dataset ?? null;
  const loadedImages = useMemo(
    () => imagesQuery.data?.pages.flatMap((page) => page.images) ?? [],
    [imagesQuery.data],
  );
  const imagesTotal =
    imagesQuery.data?.pages[0]?.imagesTotal ?? loadedImages.length;
  const hasMoreImages = imagesQuery.hasNextPage ?? false;
  const isLoadingFirstPage = imagesQuery.isLoading;
  const isLoadingMore = imagesQuery.isFetchingNextPage;

  const trainingJobs = trainingJobsQuery.data?.jobs ?? [];

  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries.some((entry) => entry.isIntersecting) &&
          hasMoreImages &&
          !isLoadingMore
        ) {
          void imagesQuery.fetchNextPage();
        }
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMoreImages, isLoadingMore, imagesQuery.fetchNextPage]);

  useEffect(() => {
    setDeleteSelectionIds((current) =>
      current.filter((imageId) =>
        loadedImages.some((image) => image.id === imageId)),
    );
  }, [loadedImages]);

  useEffect(() => {
    if (samplePoolClassFilter && !(dataset?.categories ?? []).includes(samplePoolClassFilter)) {
      setSamplePoolClassFilter("");
    }
  }, [dataset?.categories, samplePoolClassFilter]);

  useEffect(() => {
    const categoryCount = dataset?.categories.length ?? 0;
    setTrainingClassIndices((current) =>
      current.filter((index) => index < categoryCount),
    );
  }, [dataset?.categories.length]);

  const [isAugmentationModalOpen, setIsAugmentationModalOpen] = useState(false);
  const [isAnnotationModalOpen, setIsAnnotationModalOpen] = useState(false);
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [isCreatingAugmentationTask, setIsCreatingAugmentationTask] =
    useState(false);
  const [isSubmittingAnnotation, setIsSubmittingAnnotation] = useState(false);
  const [isCreatingExport, setIsCreatingExport] = useState(false);
  const [isCreatingTrainingJob, setIsCreatingTrainingJob] = useState(false);
  const [deletingTrainingJobId, setDeletingTrainingJobId] = useState<
    string | null
  >(null);
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
  const [trainingClassIndices, setTrainingClassIndices] = useState<number[]>(
    [],
  );

  const [augmentationMethods, setAugmentationMethods] = useState<
    AugmentationMethod[]
  >(defaultAugmentationMethods);
  const [augmentationSettings, setAugmentationSettings] =
    useState(defaultAugmentationSettings);

  const [confidenceThreshold, setConfidenceThreshold] = useState(0.6);
  const [skipAnnotated, setSkipAnnotated] = useState(true);
  const [exportFormat, setExportFormat] = useState<ExportFormat>("yolo");

  const [actionError, setActionError] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [isImportingVideo, setIsImportingVideo] = useState(false);
  const [isImportingRoboflow, setIsImportingRoboflow] = useState(false);
  const [archiveImportFile, setArchiveImportFile] = useState<{
    name: string;
    size: number;
  } | null>(null);
  const [activeImportTab, setActiveImportTab] = useState<ImportTab>("video");
  const [videoFrameIntervalMode, setVideoFrameIntervalMode] =
    useState<VideoFrameIntervalMode>("seconds");
  const [videoFrameInterval, setVideoFrameInterval] = useState(30);
  const [videoFrameIntervalSeconds, setVideoFrameIntervalSeconds] = useState(5);
  const [videoOutputFormat, setVideoOutputFormat] =
    useState<VideoOutputFormat>("jpg");
  const [videoJpegQuality, setVideoJpegQuality] = useState(95);
  const [videoFilenamePrefix, setVideoFilenamePrefix] = useState("frame");
  const [videoTargetSize, setVideoTargetSize] =
    useState<VideoTargetSize>("original");
  const [selectedVideoFile, setSelectedVideoFile] = useState<File | null>(null);

  const [roboflowConnections, setRoboflowConnections] = useState<
    ExternalConnection[]
  >([]);
  const [selectedRoboflowConnectionId, setSelectedRoboflowConnectionId] =
    useState("");
  const [newRoboflowConnectionName, setNewRoboflowConnectionName] =
    useState("Roboflow");
  const [newRoboflowApiKey, setNewRoboflowApiKey] = useState("");
  const [showRoboflowConnectionForm, setShowRoboflowConnectionForm] =
    useState(false);
  const [isLoadingRoboflowConnections, setIsLoadingRoboflowConnections] =
    useState(false);
  const [isSavingRoboflowConnection, setIsSavingRoboflowConnection] =
    useState(false);
  const [roboflowWorkspace, setRoboflowWorkspace] = useState("");
  const [roboflowProject, setRoboflowProject] = useState("");
  const [roboflowVersion, setRoboflowVersion] = useState("");

  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<
    DatasetImage["detections"]
  >([]);
  const [isSavingAnnotations, setIsSavingAnnotations] = useState(false);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<
    number | null
  >(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);

  const [isTrainingPanelOpen, setIsTrainingPanelOpen] = useState(false);
  const [isTasksDrawerOpen, setIsTasksDrawerOpen] = useState(false);
  const [isToolsDrawerOpen, setIsToolsDrawerOpen] = useState(false);

  const archiveInputRef = useRef<HTMLInputElement>(null);

  const previewImage = previewImageId
    ? loadedImages.find((image) => image.id === previewImageId) ?? null
    : null;

  const isAnyImporting = isImporting || isImportingVideo || isImportingRoboflow;

  const normalizedVideoFrameInterval = Math.max(
    1,
    Math.min(10000, Math.round(videoFrameInterval) || 30),
  );
  const normalizedVideoFrameIntervalSeconds = Math.max(
    0.01,
    Math.min(3600, Number(videoFrameIntervalSeconds) || 5),
  );
  const videoFrameIntervalHint =
    videoFrameIntervalMode === "seconds"
      ? `每 ${normalizedVideoFrameIntervalSeconds.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 秒取一张`
      : `每 ${normalizedVideoFrameInterval} 帧取一张`;
  const videoTargetSizeLabel =
    (
      [
        { value: "original", label: "原图" },
        { value: "1080p", label: "1080p" },
        { value: "720p", label: "720p" },
        { value: "640", label: "640" },
      ] as const
    ).find((option) => option.value === videoTargetSize)?.label ?? "原图";

  const latestTrainingJob = trainingJobs[0];
  const latestExport = dataset?.exports[0];

  async function invalidateDatasetData() {
    await queryClient.invalidateQueries({
      queryKey: ["dataset-tasks", datasetId, token],
    });
    await queryClient.invalidateQueries({
      queryKey: ["dataset-images", datasetId, token],
    });
  }

  async function confirmDiscardChanges() {
    if (!previewImage || !detectionsEqual(previewImage.detections, draftDetections))
      return true;
    return confirm({
      title: "放弃标注改动",
      content: "当前图片有未保存的标注改动，确认放弃并继续？",
    });
  }

  function openPreview(nextImageId: string | null) {
    void confirmDiscardChanges().then((confirmed) => {
      if (confirmed) setPreviewImageId(nextImageId);
    });
  }

  async function applySelection(
    payload:
      | { mode: "all" | "none" | "invert"; image_ids?: string[]; scope?: "unannotated_unretained" }
      | { mode: "single"; image_id: string; selected: boolean },
  ) {
    if (!token || !datasetId) return;
    try {
      await updateDatasetSelection(datasetId, token, payload);
      setActionError(null);
      await invalidateDatasetData();
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  function applySamplePoolRetention(mode: "all" | "none" | "invert") {
    const totalImages = dataset?.imageCount ?? 0;
    if (totalImages === 0) return;

    const retainedImageCount = dataset?.selectedCount ?? 0;
    const unretainedImageCount = Math.max(
      0,
      totalImages - retainedImageCount,
    );
    const confirmMessage =
      mode === "all"
        ? `确认将全部 ${totalImages} 张样本标记为保留？当前有 ${unretainedImageCount} 张会从不保留变为保留。`
        : mode === "invert"
          ? `确认反转全部 ${totalImages} 张样本的保留状态？当前 ${retainedImageCount} 张会变为不保留，${unretainedImageCount} 张会变为保留。`
          : `确认将全部 ${totalImages} 张样本标记为不保留？当前 ${retainedImageCount} 张保留样本会被移出训练和导出。`;

    void confirm({
      title: mode === "all" ? "全部保留" : mode === "invert" ? "反向保留" : "全部不保留",
      content: confirmMessage,
    }).then((confirmed) => {
      if (confirmed) void applySelection({ mode });
    });
  }

  function retainUnannotatedSamplePoolImages() {
    const count = dataset?.unretainedUnannotatedImageCount ?? 0;
    if (count === 0) return;
    void confirm({
      title: "保留未标注样本",
      content: `确认将 ${count} 张未标注且当前不保留的样本标记为保留？`,
    }).then((confirmed) => {
      if (confirmed) void applySelection({ mode: "all", scope: "unannotated_unretained" });
    });
  }

  function toggleDeleteSelection(imageId: string) {
    setDeleteSelectionIds((current) =>
      current.includes(imageId)
        ? current.filter((item) => item !== imageId)
        : [...current, imageId],
    );
  }

  function selectFilteredForDelete() {
    setDeleteSelectionIds((current) =>
      Array.from(new Set([...current, ...loadedImages.map((image) => image.id)])),
    );
  }

  async function removeDatasetImages(imageIds: string[], label: string) {
    if (!token || !datasetId) return;
    const uniqueImageIds = Array.from(new Set(imageIds)).filter((imageId) =>
      loadedImages.some((image) => image.id === imageId),
    );
    if (uniqueImageIds.length === 0) return;
    if (
      previewImageId &&
      uniqueImageIds.includes(previewImageId) &&
      !(await confirmDiscardChanges())
    )
      return;

    const confirmed = await confirm({
      title: "删除样本",
      content:
        uniqueImageIds.length === 1
          ? `删除${label}？图片文件和标注也会一起移除。`
          : `删除已勾选的 ${uniqueImageIds.length} 张样本？图片文件和标注也会一起移除。`,
      okDanger: true,
    });
    if (!confirmed) return;

    setDeletingImageIds(uniqueImageIds);
    try {
      const response =
        uniqueImageIds.length === 1
          ? await deleteDatasetImage(datasetId, uniqueImageIds[0], token)
          : await deleteDatasetImages(datasetId, uniqueImageIds, token);
      const deletedIdSet = new Set(response.deletedImageIds);
      if (previewImageId && deletedIdSet.has(previewImageId)) {
        setPreviewImageId(null);
      }
      setDeleteSelectionIds((current) =>
        current.filter((imageId) => !deletedIdSet.has(imageId)),
      );
      setActionError(null);
      await invalidateDatasetData();
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
    const imageIds = deleteSelectionIds.filter((imageId) =>
      loadedImages.some((image) => image.id === imageId),
    );
    void removeDatasetImages(imageIds, "");
  }

  async function createAugmentationTask() {
    if (
      !token ||
      !datasetId ||
      augmentationMethods.length === 0 ||
      (dataset?.selectedOriginalCount ?? 0) === 0
    )
      return;
    setIsCreatingAugmentationTask(true);
    try {
      await augmentDataset(
        datasetId,
        token,
        multiplier,
        augmentationMethods,
        augmentationSettings,
      );
      setActionError(null);
      setIsAugmentationModalOpen(false);
      await invalidateDatasetData();
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
      await annotateDataset(datasetId, token, confidenceThreshold, skipAnnotated);
      setActionError(null);
      setIsAnnotationModalOpen(false);
      await invalidateDatasetData();
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
      await exportDataset(datasetId, token, exportFormat, "keep");
      setActionError(null);
      setIsExportModalOpen(false);
      await invalidateDatasetData();
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
      await createTrainingJob(datasetId, token, {
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
      setActionError(null);
      await queryClient.invalidateQueries({
        queryKey: ["training-jobs", datasetId, token],
      });
      await invalidateDatasetData();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsCreatingTrainingJob(false);
    }
  }

  async function removeTrainingJob(job: TrainingJob) {
    if (!token || !datasetId) return;
    const confirmed = await confirm({
      title: "删除训练任务",
      content:
        "删除该训练任务？如果 worker 仍在运行，这不会停止 GPU 上的训练进程。",
      okDanger: true,
    });
    if (!confirmed) return;

    setDeletingTrainingJobId(job.id);
    try {
      await deleteTrainingJob(datasetId, job.id, token);
      setActionError(null);
      await queryClient.invalidateQueries({
        queryKey: ["training-jobs", datasetId, token],
      });
      await invalidateDatasetData();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setDeletingTrainingJobId(null);
    }
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
    if (!token || !newRoboflowConnectionName.trim() || !newRoboflowApiKey.trim())
      return;
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
    const confirmed = await confirm({
      title: "删除 Roboflow 连接",
      content: "删除这个 Roboflow 连接？已导入的数据不会受到影响。",
      okDanger: true,
    });
    if (!confirmed) return;
    try {
      await deleteRoboflowConnection(token, selectedRoboflowConnectionId);
      const remaining = roboflowConnections.filter(
        (connection) => connection.id !== selectedRoboflowConnectionId,
      );
      setRoboflowConnections(remaining);
      setSelectedRoboflowConnectionId(remaining[0]?.id ?? "");
      setShowRoboflowConnectionForm(remaining.length === 0);
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  async function handleArchiveImport(file: File) {
    if (!token || !datasetId) return;
    setArchiveImportFile({ name: file.name, size: file.size });
    setIsImporting(true);
    setImportSummary(null);
    setActionError(null);
    try {
      const response = await importDatasetImagesArchive(datasetId, token, file);
      setActionError(null);
      setImportSummary("ZIP 导入任务已创建，后台处理中。");
      setIsImportModalOpen(false);
      await invalidateDatasetData();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setArchiveImportFile(null);
      setIsImporting(false);
    }
  }

  async function handleVideoImport() {
    if (!token || !datasetId || !selectedVideoFile) {
      setActionError("请先选择视频。");
      return;
    }
    const frameInterval = normalizedVideoFrameInterval;
    const frameIntervalSeconds = normalizedVideoFrameIntervalSeconds;
    const jpegQuality = Math.max(
      1,
      Math.min(100, Math.round(videoJpegQuality) || 95),
    );
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
      setActionError(null);
      const importedCount = Number(
        response.summary.importedCount ?? response.task.imagesGenerated ?? 0,
      );
      setImportSummary(
        response.task.status === "running"
          ? `已创建视频抽帧任务，${videoFrameIntervalHint}，尺寸 ${videoTargetSizeLabel}`
          : `已从视频抽取 ${importedCount} 张图片`,
      );
      setSelectedVideoFile(null);
      setIsImportModalOpen(false);
      await invalidateDatasetData();
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
      setActionError(null);
      setImportSummary(
        response.summary.status === "running"
          ? "已创建 Roboflow 下载任务，可在批次任务中查看进度。"
          : `已从 Roboflow 导入 ${String(response.summary.importedCount ?? 0)} 张图片` +
            (Number(response.summary.annotatedCount ?? 0) > 0
              ? `，带标注 ${String(response.summary.annotatedCount ?? 0)} 张`
              : "") +
            (Number(response.summary.emptyAnnotationCount ?? 0) > 0
              ? `，空标注 ${String(response.summary.emptyAnnotationCount ?? 0)} 张`
              : "") +
            (Number(response.summary.skippedCount ?? 0) > 0
              ? `，跳过 ${String(response.summary.skippedCount ?? 0)} 个无效文件`
              : ""),
      );
      setIsImportModalOpen(false);
      await invalidateDatasetData();
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
      await updateDatasetImageAnnotations(
        datasetId,
        previewImage.id,
        token,
        draftDetections,
      );
      setActionError(null);
      await invalidateDatasetData();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSavingAnnotations(false);
    }
  }

  function handleArchiveFileChange(
    event: React.ChangeEvent<HTMLInputElement>,
  ) {
    const file = event.target.files?.[0];
    if (!file) return;
    void handleArchiveImport(file);
  }

  if (!dataset) {
    return (
      <PageContainer>
        <LoadingState rows={6} />
      </PageContainer>
    );
  }

  const filteredSelectedCount = loadedImages.filter(
    (image) => image.selected,
  ).length;
  const filteredAnnotatedCount = loadedImages.filter(
    (image) =>
      image.annotationStatus === "annotated" ||
      image.annotationStatus === "empty",
  ).length;
  const filteredUnannotatedCount =
    loadedImages.length - filteredAnnotatedCount;
  const deleteSelectionCount = deleteSelectionIds.filter((imageId) =>
    loadedImages.some((image) => image.id === imageId),
  ).length;

  return (
    <PageContainer>
      <Card className="shadow-panel">
        <Row gutter={[32, 32]} align="middle">
          <Col xs={24} lg={14}>
            <DatasetHeader dataset={dataset} />
            <DatasetActions
              dataset={dataset}
              latestTrainingJob={latestTrainingJob}
              onAugment={() => setIsAugmentationModalOpen(true)}
              onAnnotate={() => setIsAnnotationModalOpen(true)}
              onExport={() => setIsExportModalOpen(true)}
              onImport={() => {
                setActionError(null);
                setIsImportModalOpen(true);
                if (token) void loadRoboflowConnections();
              }}
              onTrain={() => setIsTrainingPanelOpen(true)}
              onTasks={() => setIsTasksDrawerOpen(true)}
              onTools={() => setIsToolsDrawerOpen(true)}
              isAnyImporting={isAnyImporting}
            />
            {importSummary ? (
              <div className="mt-3 text-sm text-neutral-500">{importSummary}</div>
            ) : null}
            {(dataset.selectedOriginalCount ?? 0) === 0 ? (
              <div className="mt-3 text-sm text-neutral-500">
                当前没有保留的原始样本，暂时不能创建增强批次。
              </div>
            ) : null}
          </Col>
          <Col xs={24} lg={10}>
            <DatasetMetrics dataset={dataset} />
          </Col>
        </Row>
      </Card>

      {actionError ? (
        <Alert
          className="mt-6"
          message={actionError}
          type="error"
          showIcon
          closable
          onClose={() => setActionError(null)}
        />
      ) : null}

      <DatasetQualityPanel datasetId={dataset.id} imageCount={dataset.imageCount} />

      {isTrainingPanelOpen ? (
        <TrainingPanel
          dataset={dataset}
          trainingJobs={trainingJobs}
          trainingModel={trainingModel}
          onTrainingModelChange={setTrainingModel}
          trainingEpochs={trainingEpochs}
          onTrainingEpochsChange={setTrainingEpochs}
          trainingImageSize={trainingImageSize}
          onTrainingImageSizeChange={setTrainingImageSize}
          trainingBatchSize={trainingBatchSize}
          onTrainingBatchSizeChange={setTrainingBatchSize}
          trainingPatience={trainingPatience}
          onTrainingPatienceChange={setTrainingPatience}
          trainingDropout={trainingDropout}
          onTrainingDropoutChange={setTrainingDropout}
          trainingMixup={trainingMixup}
          onTrainingMixupChange={setTrainingMixup}
          trainingWeightDecay={trainingWeightDecay}
          onTrainingWeightDecayChange={setTrainingWeightDecay}
          trainingClassIndices={trainingClassIndices}
          onTrainingClassIndicesChange={setTrainingClassIndices}
          isCreatingTrainingJob={isCreatingTrainingJob}
          deletingTrainingJobId={deletingTrainingJobId}
          onStartTrainingJob={startTrainingJob}
          onRemoveTrainingJob={removeTrainingJob}
          onDownloadArtifact={(artifact) => {
            if (!token) return;
            void downloadWithToken(artifact.downloadUrl, token, artifact.filename);
          }}
          onClose={() => setIsTrainingPanelOpen(false)}
        />
      ) : null}

      <Card className="mt-6 shadow-panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
              样本池
            </div>
            <div className="mt-2 text-2xl">统一筛选、标注和导出</div>
            <div className="mt-2 text-sm text-neutral-500">
              当前显示 {loadedImages.length} / {imagesTotal} 张，显示范围内已保留{" "}
              {filteredSelectedCount} 张，已标注 {filteredAnnotatedCount} 张，未标注{" "}
              {filteredUnannotatedCount} 张，当前范围勾选待删 {deleteSelectionCount} 张
            </div>
          </div>
        </div>

        <SamplePoolToolbar
          dataset={dataset}
          filteredImagesCount={loadedImages.length}
          deleteSelectionCount={deleteSelectionCount}
          unretainedUnannotatedImageCount={
            dataset.unretainedUnannotatedImageCount ?? 0
          }
          isDeletingImages={deletingImageIds.length > 0}
          isAnyImporting={isAnyImporting}
          onRetainAll={() => applySamplePoolRetention("all")}
          onRetainInvert={() => applySamplePoolRetention("invert")}
          onRetainNone={() => applySamplePoolRetention("none")}
          onRetainUnannotated={retainUnannotatedSamplePoolImages}
          onSelectFilteredForDelete={selectFilteredForDelete}
          onClearDeleteSelection={() => setDeleteSelectionIds([])}
          onRemoveDeleteSelection={removeDeleteSelection}
        />

        <SamplePoolFilters
          dataset={dataset}
          classFilter={samplePoolClassFilter}
          splitFilter={samplePoolSplitFilter}
          annotationFilter={samplePoolAnnotationFilter}
          sourceFilter={samplePoolSourceFilter}
          onClassFilterChange={setSamplePoolClassFilter}
          onSplitFilterChange={setSamplePoolSplitFilter}
          onAnnotationFilterChange={setSamplePoolAnnotationFilter}
          onSourceFilterChange={setSamplePoolSourceFilter}
        />

        <SamplePoolGrid
          images={loadedImages}
          imagesTotal={imagesTotal}
          isLoadingFirstPage={isLoadingFirstPage}
          isLoadingMore={isLoadingMore}
          hasMoreImages={hasMoreImages}
          deleteSelectionIds={deleteSelectionIds}
          deletingImageIds={deletingImageIds}
          onToggleDeleteSelection={toggleDeleteSelection}
          onOpenPreview={openPreview}
          onToggleSelection={(image) =>
            void applySelection({
              mode: "single",
              image_id: image.id,
              selected: !image.selected,
            })
          }
          onDeleteImage={removeDatasetImage}
          sentinelRef={sentinelRef}
        />
      </Card>

      <ImportModal
        open={isImportModalOpen}
        onClose={() => {
          if (!isAnyImporting) setIsImportModalOpen(false);
        }}
        activeTab={activeImportTab}
        onTabChange={setActiveImportTab}
        actionError={actionError}
        onClearActionError={() => setActionError(null)}
        isAnyImporting={isAnyImporting}
        selectedVideoFile={selectedVideoFile}
        onVideoSelect={setSelectedVideoFile}
        onVideoImport={handleVideoImport}
        isImportingVideo={isImportingVideo}
        videoFrameIntervalMode={videoFrameIntervalMode}
        onVideoFrameIntervalModeChange={setVideoFrameIntervalMode}
        videoFrameInterval={videoFrameInterval}
        onVideoFrameIntervalChange={setVideoFrameInterval}
        videoFrameIntervalSeconds={videoFrameIntervalSeconds}
        onVideoFrameIntervalSecondsChange={setVideoFrameIntervalSeconds}
        videoOutputFormat={videoOutputFormat}
        onVideoOutputFormatChange={setVideoOutputFormat}
        videoJpegQuality={videoJpegQuality}
        onVideoJpegQualityChange={setVideoJpegQuality}
        videoFilenamePrefix={videoFilenamePrefix}
        onVideoFilenamePrefixChange={setVideoFilenamePrefix}
        videoTargetSize={videoTargetSize}
        onVideoTargetSizeChange={setVideoTargetSize}
        archiveInputRef={archiveInputRef}
        onArchiveSelect={handleArchiveImport}
        isImportingZip={isImporting}
        archiveImportFile={archiveImportFile}
        roboflowConnections={roboflowConnections}
        selectedRoboflowConnectionId={selectedRoboflowConnectionId}
        onSelectedRoboflowConnectionIdChange={setSelectedRoboflowConnectionId}
        onLoadRoboflowConnections={loadRoboflowConnections}
        onSaveRoboflowConnection={saveRoboflowConnection}
        onRemoveSelectedRoboflowConnection={removeSelectedRoboflowConnection}
        newRoboflowConnectionName={newRoboflowConnectionName}
        onNewRoboflowConnectionNameChange={setNewRoboflowConnectionName}
        newRoboflowApiKey={newRoboflowApiKey}
        onNewRoboflowApiKeyChange={setNewRoboflowApiKey}
        showRoboflowConnectionForm={showRoboflowConnectionForm}
        onShowRoboflowConnectionFormChange={setShowRoboflowConnectionForm}
        isLoadingRoboflowConnections={isLoadingRoboflowConnections}
        isSavingRoboflowConnection={isSavingRoboflowConnection}
        roboflowWorkspace={roboflowWorkspace}
        onRoboflowWorkspaceChange={setRoboflowWorkspace}
        roboflowProject={roboflowProject}
        onRoboflowProjectChange={setRoboflowProject}
        roboflowVersion={roboflowVersion}
        onRoboflowVersionChange={setRoboflowVersion}
        onRoboflowImport={handleRoboflowImport}
        isImportingRoboflow={isImportingRoboflow}
      />

      <AugmentationModal
        open={isAugmentationModalOpen}
        onClose={() => setIsAugmentationModalOpen(false)}
        multiplier={multiplier}
        onMultiplierChange={setMultiplier}
        augmentationMethods={augmentationMethods}
        onAugmentationMethodsChange={setAugmentationMethods}
        augmentationSettings={augmentationSettings}
        onAugmentationSettingsChange={setAugmentationSettings}
        selectedOriginalCount={dataset.selectedOriginalCount ?? 0}
        isCreatingAugmentationTask={isCreatingAugmentationTask}
        onCreate={createAugmentationTask}
      />

      <AnnotationModal
        open={isAnnotationModalOpen}
        onClose={() => setIsAnnotationModalOpen(false)}
        dataset={dataset}
        confidenceThreshold={confidenceThreshold}
        onConfidenceThresholdChange={setConfidenceThreshold}
        skipAnnotated={skipAnnotated}
        onSkipAnnotatedChange={setSkipAnnotated}
        isSubmittingAnnotation={isSubmittingAnnotation}
        onSubmit={runAutoAnnotation}
      />

      <ExportModal
        open={isExportModalOpen}
        onClose={() => setIsExportModalOpen(false)}
        dataset={dataset}
        exportFormat={exportFormat}
        onExportFormatChange={setExportFormat}
        latestExport={latestExport}
        isCreatingExport={isCreatingExport}
        onCreate={createExportPackage}
      />

      <ImagePreviewModal
        open={previewImageId !== null}
        onClose={() => setPreviewImageId(null)}
        previewImage={previewImage}
        images={loadedImages}
        dataset={dataset}
        draftDetections={draftDetections}
        setDraftDetections={setDraftDetections}
        selectedDetectionIndex={selectedDetectionIndex}
        setSelectedDetectionIndex={setSelectedDetectionIndex}
        isAddingDetection={isAddingDetection}
        setIsAddingDetection={setIsAddingDetection}
        isSavingAnnotations={isSavingAnnotations}
        onSaveAnnotations={saveAnnotations}
        onDeleteImage={removeDatasetImage}
        onPreviewChange={(imageId) => setPreviewImageId(imageId)}
        onConfirmDiscardChanges={confirmDiscardChanges}
      />

      <Drawer
        title={
          <div className="flex items-center gap-3">
            <ClipboardList className="h-5 w-5 text-neutral-500" />
            <span>批次任务</span>
            <span className="text-xs text-neutral-400">{dataset.tasks.length} 个任务</span>
          </div>
        }
        open={isTasksDrawerOpen}
        onClose={() => setIsTasksDrawerOpen(false)}
        width={520}
      >
        <List
          dataSource={dataset.tasks}
          locale={{
            emptyText: (
              <div className="text-sm text-neutral-500">暂无批次任务</div>
            ),
          }}
          renderItem={(task) => (
            <List.Item key={task.id}>
              <Card className="w-full bg-neutral-50 dark:bg-white/[0.03]">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <Space wrap size="small">
                      <StatusBadge status={task.taskType} />
                      <StatusBadge status={task.status} />
                    </Space>
                    <div className="mt-3 text-lg">{task.taskName}</div>
                    <div className="mt-1 text-sm text-neutral-500">{task.subject}</div>
                  </div>
                  {(task.status === "paused" || task.status === "failed") && token ? (
                    <Button
                      onClick={() =>
                        void retryDatasetTask(dataset.id, task.id, token)
                          .then(() => invalidateDatasetData())
                          .catch((error) =>
                            setActionError((error as Error).message),
                          )
                      }
                    >
                      重试
                    </Button>
                  ) : null}
                </div>
                <Progress percent={task.progressPercent} className="mt-4" />
                <Space wrap className="mt-3 text-xs text-neutral-500">
                  <span>
                    {task.imagesGenerated} / {task.imageCount}
                  </span>
                  <span>{formatCurrency(task.spentCost)}</span>
                  <span>{formatDate(task.updatedAt)}</span>
                </Space>
              </Card>
            </List.Item>
          )}
        />
      </Drawer>

      <Drawer
        title={
          <div className="flex items-center gap-3">
            <Layers className="h-5 w-5 text-neutral-500" />
            <span>数据集功能</span>
          </div>
        }
        open={isToolsDrawerOpen}
        onClose={() => setIsToolsDrawerOpen(false)}
        width={520}
      >
        <div className="space-y-4">
          <Card className="bg-neutral-50 dark:bg-white/[0.03]">
            <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
              自动标注
            </div>
            <div className="mt-3 text-lg">
              {dataset.annotation?.status === "running"
                ? "运行中"
                : String(dataset.annotation?.status ?? "idle") === "completed"
                  ? "已完成"
                  : "待执行"}
            </div>
            <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              对当前样本池执行自动标注，默认阈值 {confidenceThreshold.toFixed(2)}。
            </div>
            <Button
              className="mt-4"
              onClick={() => {
                setIsToolsDrawerOpen(false);
                setIsAnnotationModalOpen(true);
              }}
              disabled={dataset.imageCount === 0 || dataset.annotation?.status === "running"}
            >
              自动标注
            </Button>
          </Card>

          <Card className="bg-neutral-50 dark:bg-white/[0.03]">
            <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">导出</div>
            <div className="mt-3 text-lg">
              {latestExport
                ? `v${latestExport.version} · ${String(latestExport.status)}`
                : "未创建导出包"}
            </div>
            <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              当前保留 {dataset.selectedCount} 张样本，可导出为{" "}
              {exportFormat.toUpperCase()} 数据集。
            </div>
            <Space className="mt-4">
              <Button
                onClick={() => {
                  setIsToolsDrawerOpen(false);
                  setIsExportModalOpen(true);
                }}
                disabled={dataset.selectedCount === 0}
              >
                导出
              </Button>
              {latestExport && latestExport.status === "ready" ? (
                <Button
                  type="primary"
                  icon={<Download className="h-4 w-4" />}
                  onClick={() => {
                    if (!token) return;
                    void downloadWithToken(
                      latestExport.downloadUrl,
                      token,
                      `${dataset.name}-${latestExport.version}.zip`,
                    );
                  }}
                >
                  下载最新包
                </Button>
              ) : null}
            </Space>
          </Card>
        </div>
      </Drawer>
    </PageContainer>
  );
}
