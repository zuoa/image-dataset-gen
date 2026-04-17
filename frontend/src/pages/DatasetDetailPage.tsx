import { useEffect, useRef, useState, type ChangeEvent, type MouseEvent as ReactMouseEvent } from "react";
import { CheckSquare, ChevronLeft, ChevronRight, ClipboardList, Download, FlipHorizontal2, Layers, ListChecks, Loader, Sparkles, Square, Tag, Upload, Wand2, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { downloadWithToken } from "../api/client";
import {
  annotateDataset,
  augmentDataset,
  exportDataset,
  getDataset,
  importDatasetImagesArchive,
  retryDatasetTask,
  updateDatasetImageAnnotations,
  updateDatasetSelection,
} from "../api/datasets";
import { AuthImage } from "../components/AuthImage";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { SectionCard } from "../components/ui/SectionCard";
import type { AugmentationMethod, AugmentationSettings, Dataset, DatasetImage } from "../lib/types";
import { formatCurrency, formatDate } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const DEFAULT_BOX_SIZE = 0.22;
const MIN_BOX_SIZE = 0.04;
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

type ResizeCorner = "nw" | "ne" | "sw" | "se";

function detectionStyle([xCenter, yCenter, width, height]: [number, number, number, number]) {
  return {
    left: `${(xCenter - width / 2) * 100}%`,
    top: `${(yCenter - height / 2) * 100}%`,
    width: `${width * 100}%`,
    height: `${height * 100}%`,
  };
}

function clamp(value: number, min = 0, max = 1) {
  return Math.min(Math.max(value, min), max);
}

function pointerToStage(rect: DOMRect, clientX: number, clientY: number) {
  return {
    x: clamp((clientX - rect.left) / rect.width),
    y: clamp((clientY - rect.top) / rect.height),
  };
}

function boxFromCorners(startX: number, startY: number, endX: number, endY: number): [number, number, number, number] {
  const left = clamp(Math.min(startX, endX));
  const right = clamp(Math.max(startX, endX));
  const top = clamp(Math.min(startY, endY));
  const bottom = clamp(Math.max(startY, endY));
  const width = Math.max(right - left, MIN_BOX_SIZE);
  const height = Math.max(bottom - top, MIN_BOX_SIZE);
  const xCenter = clamp((left + right) / 2, width / 2, 1 - width / 2);
  const yCenter = clamp((top + bottom) / 2, height / 2, 1 - height / 2);
  return [xCenter, yCenter, width, height];
}

export function DatasetDetailPage() {
  const token = useAuthStore((state) => state.token);
  const { datasetId } = useParams();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const datasetRef = useRef<Dataset | null>(null);
  datasetRef.current = dataset;
  const [isAugmentationModalOpen, setIsAugmentationModalOpen] = useState(false);
  const [isAnnotationModalOpen, setIsAnnotationModalOpen] = useState(false);
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [isCreatingAugmentationTask, setIsCreatingAugmentationTask] = useState(false);
  const [isSubmittingAnnotation, setIsSubmittingAnnotation] = useState(false);
  const [isCreatingExport, setIsCreatingExport] = useState(false);
  const [multiplier, setMultiplier] = useState(3);
  const [augmentationMethods, setAugmentationMethods] = useState<AugmentationMethod[]>(defaultAugmentationMethods);
  const [augmentationSettings, setAugmentationSettings] = useState(defaultAugmentationSettings);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.6);
  const [skipAnnotated, setSkipAnnotated] = useState(true);
  const [exportFormat, setExportFormat] = useState<ExportFormat>("yolo");
  const [actionError, setActionError] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<DatasetImage["detections"]>([]);
  const [isSavingAnnotations, setIsSavingAnnotations] = useState(false);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);
  const [isTasksExpanded, setIsTasksExpanded] = useState(false);
  const [isToolsPanelOpen, setIsToolsPanelOpen] = useState(false);
  const [isTasksDrawerOpen, setIsTasksDrawerOpen] = useState(false);
  const [isToolsDrawerOpen, setIsToolsDrawerOpen] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const archiveInputRef = useRef<HTMLInputElement | null>(null);

  const images = dataset?.images ?? [];
  const previewIndex = previewImageId ? images.findIndex((image) => image.id === previewImageId) : -1;
  const previewImage = previewIndex >= 0 ? images[previewIndex] : null;
  const runningTask = dataset?.tasks.some((task) => task.status === "running");
  const annotationRunning = dataset?.annotation?.status === "running";
  const selectedOriginalCount = images.filter((image) => image.selected && image.status !== "augmented").length;
  const latestExport = dataset?.exports[0];
  const annotationStatus = String(dataset?.annotation?.status ?? "idle");

  useEffect(() => {
    if (!token || !datasetId) return;

    let disposed = false;
    const loadDataset = async () => {
      try {
        const response = await getDataset(datasetId, token);
        if (!disposed) {
          setDataset(response.dataset);
          setActionError(null);
        }
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
      }
    };

    void loadDataset();
    const interval = window.setInterval(() => {
      const hasPendingExports = datasetRef.current?.exports.some(
        (item) => item.status === "pending" || item.status === "running"
      );
      if (runningTask || annotationRunning || hasPendingExports) {
        void loadDataset();
      }
    }, 2000);

    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [annotationRunning, datasetId, runningTask, token]);

  useEffect(() => {
    setDraftDetections(previewImage?.detections ?? []);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(false);
  }, [previewImage]);

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
    previewImage !== null && JSON.stringify(previewImage.detections) !== JSON.stringify(draftDetections);

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
    if (!isAugmentationModalOpen && !isAnnotationModalOpen && !isExportModalOpen) return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !isCreatingAugmentationTask &&
        !isSubmittingAnnotation &&
        !isCreatingExport
      ) {
        setIsAugmentationModalOpen(false);
        setIsAnnotationModalOpen(false);
        setIsExportModalOpen(false);
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

  function openAugmentationModal() {
    setIsAugmentationModalOpen(true);
    setIsAnnotationModalOpen(false);
    setIsExportModalOpen(false);
  }

  function openAnnotationModal() {
    setIsAnnotationModalOpen(true);
    setIsAugmentationModalOpen(false);
    setIsExportModalOpen(false);
  }

  function openExportModal() {
    setIsExportModalOpen(true);
    setIsAugmentationModalOpen(false);
    setIsAnnotationModalOpen(false);
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

  async function applySelection(
    payload:
      | { mode: "all" | "none" | "invert" }
      | { mode: "single"; image_id: string; selected: boolean },
  ) {
    if (!token || !datasetId) return;
    try {
      const response = await updateDatasetSelection(datasetId, token, payload);
      setDataset(response.dataset);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  async function handleArchiveImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!token || !datasetId || !file) return;
    setIsImporting(true);
    setImportSummary(null);
    try {
      const response = await importDatasetImagesArchive(datasetId, token, file);
      setDataset(response.dataset);
      setActionError(null);
      setImportSummary(
        `已导入 ${String(response.summary.importedCount ?? 0)} 张图片` +
          (Number(response.summary.skippedCount ?? 0) > 0 ? `，跳过 ${String(response.summary.skippedCount ?? 0)} 个无效文件` : ""),
      );
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      event.target.value = "";
      setIsImporting(false);
    }
  }

  async function saveAnnotations() {
    if (!token || !datasetId || !previewImage) return;
    setIsSavingAnnotations(true);
    try {
      const response = await updateDatasetImageAnnotations(datasetId, previewImage.id, token, draftDetections);
      setDataset(response.dataset);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSavingAnnotations(false);
    }
  }

  function beginDragDetection(index: number, event: ReactMouseEvent<HTMLDivElement>) {
    if (!stageRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = stageRef.current.getBoundingClientRect();
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
    if (!stageRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = stageRef.current.getBoundingClientRect();
    const origin = draftDetections[index];
    const [xCenter, yCenter, width, height] = origin.bbox;
    const left = xCenter - width / 2;
    const right = xCenter + width / 2;
    const top = yCenter - height / 2;
    const bottom = yCenter + height / 2;
    const anchorX = corner.includes("w") ? right : left;
    const anchorY = corner.includes("n") ? bottom : top;

    const handleMove = (moveEvent: MouseEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(anchorX, anchorY, pointer.x, pointer.y);
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
    if (!stageRef.current || !isAddingDetection || !dataset) return;
    event.preventDefault();
    const rect = stageRef.current.getBoundingClientRect();
    const start = pointerToStage(rect, event.clientX, event.clientY);
    const category = dataset.categories[0] ?? "object";
    const nextIndex = draftDetections.length;

    setDraftDetections((current) => [
      ...current,
      { category, confidence: 0.8, bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE] },
    ]);
    setSelectedDetectionIndex(nextIndex);

    const handleMove = (moveEvent: MouseEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(start.x, start.y, pointer.x, pointer.y);
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
              <Button
                variant="secondary"
                onClick={openExportModal}
                disabled={dataset.selectedCount === 0}
              >
                <Download className="mr-2 h-4 w-4" />
                导出
              </Button>
              <Button variant="secondary" onClick={() => archiveInputRef.current?.click()} disabled={isImporting}>
                <Upload className="mr-2 h-4 w-4" />
                导入
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
            </div>
            {importSummary ? <div className="mt-3 text-sm text-neutral-500">{importSummary}</div> : null}
            {selectedOriginalCount === 0 ? (
              <div className="mt-3 text-sm text-neutral-500">当前没有已选中的原始样本，暂时不能创建增强批次。</div>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "样本池", value: String(dataset.imageCount) },
              { label: "已选样本", value: String(dataset.selectedCount) },
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
                    当前已选中 {dataset.selectedCount} 张样本，可导出为 {exportFormat.toUpperCase()} 数据集。
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
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => void applySelection({ mode: "all" })}><CheckSquare className="mr-2 h-4 w-4" />全选</Button>
              <Button variant="secondary" onClick={() => void applySelection({ mode: "invert" })}><FlipHorizontal2 className="mr-2 h-4 w-4" />反选</Button>
              <Button variant="secondary" onClick={() => void applySelection({ mode: "none" })}><Square className="mr-2 h-4 w-4" />清空</Button>
            </div>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {images.map((image) => (
              <button
                key={image.id}
                type="button"
                className={`group overflow-hidden rounded-[24px] border text-left transition ${
                  image.selected
                    ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.03]"
                    : "border-neutral-200 bg-white opacity-80 dark:border-white/10 dark:bg-black/20"
                }`}
                onClick={() => openPreview(image.id)}
              >
                <div className="relative aspect-square overflow-hidden">
                  <AuthImage src={image.previewSvg} alt={image.promptText} className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
                  <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_35%,rgba(10,10,10,0.72))]" />
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void applySelection({ mode: "single", image_id: image.id, selected: !image.selected });
                    }}
                    className={`absolute right-3 top-3 rounded-full px-3 py-1 text-xs ${
                      image.selected ? "bg-white text-neutral-900" : "bg-black/65 text-white"
                    }`}
                  >
                    {image.selected ? "已保留" : "未选中"}
                  </button>
                  <div className="absolute bottom-3 left-3 right-3 text-white">
                    <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em]">
                      <span>{image.sourceType}</span>
                      <span>#{image.ordinal}</span>
                    </div>
                    <div className="mt-2 line-clamp-2 text-sm">{image.promptText}</div>
                  </div>
                </div>
              </button>
            ))}
	          </div>
	        </SectionCard>
	
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
                增强批次会基于当前已选中的原始样本生成新的变体，并自动写回同一个数据集样本池。
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
                选择导出格式后创建数据集压缩包，导出范围基于当前已选中的样本。
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
                <div className="mt-3 text-lg text-neutral-900 dark:text-white">{dataset.selectedCount} 张已选样本</div>
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
                className={`relative mx-auto flex h-full max-h-[72vh] w-full max-w-[72vh] items-center justify-center overflow-hidden rounded-[28px] ${
                  isAddingDetection ? "cursor-crosshair" : "cursor-default"
                }`}
                onMouseDown={handleStageMouseDown}
              >
                <AuthImage src={previewImage.previewSvg} alt={previewImage.promptText} className="h-full w-full object-contain" />
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
            </div>

            <div className="w-full overflow-y-auto border-t border-neutral-200 p-6 dark:border-white/10 xl:w-[420px] xl:border-l xl:border-t-0">
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Image Inspector</div>
              <div className="mt-2 text-2xl text-neutral-900 dark:text-white">
                样本 #{previewImage.ordinal}
              </div>
              <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">{previewImage.promptText}</div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge>{previewImage.sourceType}</Badge>
                <Badge>{previewImage.annotationStatus}</Badge>
              </div>

              <div className="mt-6 flex gap-3">
                <Button variant="secondary" onClick={() => setIsAddingDetection((current) => !current)}>
                  {isAddingDetection ? "取消新增框" : "新增框"}
                </Button>
                <Button onClick={() => void saveAnnotations()} disabled={isSavingAnnotations}>
                  保存标注
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
