import { useEffect, useRef, useState, type ChangeEvent, type MouseEvent as ReactMouseEvent } from "react";
import { ChevronLeft, ChevronRight, Upload, X } from "lucide-react";
import { useParams } from "react-router-dom";

import { downloadWithToken } from "../api/client";
import { AuthImage } from "../components/AuthImage";
import {
  annotateTask,
  augmentTask,
  exportTask,
  getTask,
  importTaskImagesArchive,
  retryTask,
  updateImageAnnotations,
  updateSelection,
} from "../api/tasks";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import { SectionCard } from "../components/ui/SectionCard";
import type { AugmentationMethod, Task, TaskImage } from "../lib/types";
import { formatCurrency, formatDate, formatProviderLabel } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const DEFAULT_BOX_SIZE = 0.22;
const MIN_BOX_SIZE = 0.04;
const defaultAugmentationMethods: AugmentationMethod[] = ["flip", "color_jitter", "blur"];
const augmentationOptions: Array<{ value: AugmentationMethod; label: string; desc: string }> = [
  { value: "flip", label: "翻转", desc: "水平或垂直镜像" },
  { value: "rotate", label: "旋转", desc: "小角度旋转扰动" },
  { value: "crop", label: "随机裁切", desc: "保留主体的视野变化" },
  { value: "color_jitter", label: "颜色抖动", desc: "亮度饱和度微调" },
  { value: "blur", label: "模糊", desc: "模拟失焦和运动模糊" },
  { value: "noise", label: "噪声", desc: "模拟高 ISO 与传感器噪点" },
  { value: "occlusion", label: "遮挡", desc: "局部挡住目标边缘" },
  { value: "perspective", label: "透视变换", desc: "模拟轻微视角偏移" },
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

function sourceLabel(image: TaskImage) {
  if (image.source === "augmented") return "Augmented";
  if (image.source === "uploaded") return "Uploaded";
  return image.source === "placeholder" ? "Placeholder" : image.source.toUpperCase();
}

function clamp(value: number, min = 0, max = 1) {
  return Math.min(Math.max(value, min), max);
}

function pointerToStage(
  rect: DOMRect,
  clientX: number,
  clientY: number,
): { x: number; y: number } {
  return {
    x: clamp((clientX - rect.left) / rect.width),
    y: clamp((clientY - rect.top) / rect.height),
  };
}

function boxFromCorners(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
): [number, number, number, number] {
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

export function TaskDetailPage() {
  const token = useAuthStore((state) => state.token);
  const { taskId } = useParams();
  const [task, setTask] = useState<Task | null>(null);
  const [multiplier, setMultiplier] = useState(5);
  const [augmentationMethods, setAugmentationMethods] = useState<AugmentationMethod[]>(defaultAugmentationMethods);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.6);
  const [exportFormat, setExportFormat] = useState<"yolo" | "coco" | "voc" | "csv">("yolo");
  const [exportError, setExportError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<TaskImage["detections"]>([]);
  const [isSavingAnnotations, setIsSavingAnnotations] = useState(false);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const archiveInputRef = useRef<HTMLInputElement | null>(null);

  const images = task?.images ?? [];
  const previewIndex = previewImageId ? images.findIndex((image) => image.id === previewImageId) : -1;
  const previewImage = previewIndex >= 0 ? images[previewIndex] : null;
  const augmentationSummary = task?.config.augmentation ?? null;
  const isAugmenting = augmentationSummary?.status === "running";
  const selectedOriginalCount = images.filter((image) => image.selected && image.status !== "augmented").length;

  useEffect(() => {
    if (!token || !taskId) return;

    let disposed = false;

    const loadTask = async () => {
      try {
        const response = await getTask(taskId, token);
        if (!disposed) {
          setTask(response.task);
          setActionError(null);
        }
      } catch (error) {
        if (!disposed) {
          setActionError((error as Error).message);
        }
      }
    };

    void loadTask();
    const interval = window.setInterval(() => {
      if (task?.status === "running" || task?.config.augmentation?.status === "running") {
        void loadTask();
      }
    }, 2000);

    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [task?.config.augmentation?.status, task?.status, taskId, token]);

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

  useEffect(() => {
    setDraftDetections(previewImage?.detections ?? []);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(false);
  }, [previewImage]);

  useEffect(() => {
    const methods = task?.config.augmentation?.methods;
    if (methods?.length) {
      setAugmentationMethods(methods);
      return;
    }
    setAugmentationMethods(defaultAugmentationMethods);
  }, [task?.config.augmentation?.methods]);

  function toggleAugmentationMethod(method: AugmentationMethod) {
    setAugmentationMethods((current) =>
      current.includes(method) ? current.filter((item) => item !== method) : [...current, method],
    );
  }

  async function applySelection(
    payload:
      | { mode: "all" | "none" | "invert" }
      | { mode: "single"; image_id: string; selected: boolean },
  ) {
    if (!token || !taskId) return;
    try {
      const response = await updateSelection(taskId, token, payload);
      setTask(response.task);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  async function handleArchiveImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!token || !taskId || !file) return;
    setIsImporting(true);
    setImportSummary(null);
    try {
      const response = await importTaskImagesArchive(taskId, token, file);
      setTask(response.task);
      setActionError(null);
      setImportSummary(
        `已导入 ${String(response.summary.importedCount ?? 0)} 张本地图片` +
          (Number(response.summary.skippedCount ?? 0) > 0
            ? `，跳过 ${String(response.summary.skippedCount ?? 0)} 个无效文件`
            : ""),
      );
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      event.target.value = "";
      setIsImporting(false);
    }
  }

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

  const hasAnnotationChanges =
    previewImage !== null && JSON.stringify(previewImage.detections) !== JSON.stringify(draftDetections);
  const selectedDetection =
    selectedDetectionIndex !== null ? draftDetections[selectedDetectionIndex] ?? null : null;

  useEffect(() => {
    if (!previewImage || !hasAnnotationChanges) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasAnnotationChanges, previewImage]);

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

  function beginResizeDetection(
    index: number,
    corner: ResizeCorner,
    event: ReactMouseEvent<HTMLButtonElement>,
  ) {
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
        current.map((detection, detectionIndex) =>
          detectionIndex === index ? { ...detection, bbox } : detection,
        ),
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
    if (!stageRef.current || !isAddingDetection || !task) return;

    event.preventDefault();
    const rect = stageRef.current.getBoundingClientRect();
    const start = pointerToStage(rect, event.clientX, event.clientY);
    const category = task.categories[0] ?? "object";
    const nextIndex = draftDetections.length;

    setDraftDetections((current) => [
      ...current,
      {
        category,
        confidence: 0.8,
        bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE],
      },
    ]);
    setSelectedDetectionIndex(nextIndex);

    const handleMove = (moveEvent: MouseEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(start.x, start.y, pointer.x, pointer.y);
      setDraftDetections((current) =>
        current.map((detection, detectionIndex) =>
          detectionIndex === nextIndex ? { ...detection, bbox } : detection,
        ),
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

  function updateDetectionField(
    index: number,
    field: "category" | "confidence",
    value: string | number,
  ) {
    setDraftDetections((current) =>
      current.map((detection, detectionIndex) => {
        if (detectionIndex !== index) return detection;
        if (field === "category") {
          return { ...detection, category: String(value).slice(0, 120) || "object" };
        }
        const nextConfidence = Number(value);
        return {
          ...detection,
          confidence: Number.isFinite(nextConfidence)
            ? Math.min(Math.max(nextConfidence, 0), 1)
            : detection.confidence,
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

  async function saveAnnotations() {
    if (!token || !taskId || !previewImage) return;
    setIsSavingAnnotations(true);
    try {
      const response = await updateImageAnnotations(taskId, previewImage.id, token, draftDetections);
      setTask(response.task);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSavingAnnotations(false);
    }
  }

  if (!task) {
    return (
      <SectionCard>
        <div className="text-sm text-neutral-500 dark:text-neutral-400">加载任务中...</div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-6">
      <SectionCard className="overflow-hidden">
        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <div className="flex flex-wrap gap-2">
              <Badge>{task.status}</Badge>
              <Badge>{formatProviderLabel(task.apiProvider)}</Badge>
            </div>
            <h2 className="mt-4 text-4xl font-medium text-neutral-900 dark:text-white">{task.subject}</h2>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">{task.subject}</p>
            <div className="mt-8 h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-white/10">
              <div
                className="h-full rounded-full bg-neutral-900 transition-all duration-500 dark:bg-white"
                style={{ width: `${task.progressPercent}%` }}
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-6 text-sm text-neutral-500 dark:text-neutral-400">
              <div>已生成 {task.imagesGenerated} / 目标 {task.imageCount}</div>
              <div>已消耗 {formatCurrency(task.spentCost)}</div>
              <div>开始于 {formatDate(task.startedAt)}</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "当前样本", value: task.sampleCount.toString() },
              { label: "保留样本", value: `${task.selectedCount}/${task.sampleCount}` },
              { label: "目标数量", value: task.imageCount.toString() },
              { label: "预估成本", value: formatCurrency(task.estimatedCost) },
            ].map((metric) => (
              <div key={metric.label} className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-white/[0.03]">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">{metric.label}</div>
                <div className="mt-3 text-2xl text-neutral-900 dark:text-white">{metric.value}</div>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      {task.config.runtime?.generationError ? (
        <SectionCard className="border-red-300/30 bg-red-50/60 dark:border-red-400/20 dark:bg-red-950/20">
          <div className="text-xs uppercase tracking-[0.24em] text-red-600/70 dark:text-red-300/70">Generation Error</div>
          <div className="mt-3 text-sm text-red-700 dark:text-red-100">{String(task.config.runtime.generationError)}</div>
          <div className="mt-2 flex items-center justify-between gap-4">
            <div className="text-xs text-red-600/70 dark:text-red-200/60">
              任务已暂停。修正 provider 或 API Key 后可直接重试。
            </div>
            <Button
              onClick={() => {
                if (!token || !taskId) return;
                void retryTask(taskId, token)
                  .then((data) => {
                    setTask(data.task);
                    setActionError(null);
                  })
                  .catch((error) => setActionError((error as Error).message));
              }}
            >
              重试生成
            </Button>
          </div>
        </SectionCard>
      ) : null}

      {actionError ? (
        <SectionCard className="border-amber-300/30 bg-amber-50/60 dark:border-amber-400/20 dark:bg-amber-950/20">
          <div className="text-sm text-amber-800 dark:text-amber-100">{actionError}</div>
        </SectionCard>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <SectionCard>
          <div className="mb-5 flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Generated Samples</div>
              <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">生成结果</h3>
            </div>
            <div className="text-sm text-neutral-500">
              {task.selectedCount}/{task.images.length} 张已保留
            </div>
          </div>

          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/[0.02]">
            <Button variant="secondary" onClick={() => void applySelection({ mode: "all" })}>
              全选
            </Button>
            <Button variant="secondary" onClick={() => void applySelection({ mode: "none" })}>
              全不选
            </Button>
            <Button variant="secondary" onClick={() => void applySelection({ mode: "invert" })}>
              反选
            </Button>
            <input
              ref={archiveInputRef}
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={(event) => void handleArchiveImport(event)}
            />
            <Button
              variant="secondary"
              disabled={isImporting}
              onClick={() => archiveInputRef.current?.click()}
            >
              <Upload className="mr-2 h-4 w-4" />
              {isImporting ? "导入中..." : "导入本地 ZIP"}
            </Button>
            <div className="text-sm text-neutral-500">点击样本可进入审核台，支持键盘左右切换。</div>
            {importSummary ? <div className="text-sm text-neutral-500">{importSummary}</div> : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {task.images.map((image) => (
              <div
                key={image.id}
                className={`rounded-[24px] border p-3 transition ${image.selected ? "border-neutral-300 bg-neutral-100 dark:border-white/20 dark:bg-black/40" : "border-neutral-100 bg-white dark:border-white/8 dark:bg-black/20 opacity-75"}`}
              >
                <button className="block w-full" onClick={() => openPreview(image.id)} type="button">
                  <div className="relative overflow-hidden rounded-[18px] border border-neutral-200 dark:border-white/10">
                    <AuthImage
                      src={image.previewSvg}
                      alt={`preview-${image.ordinal}`}
                      className="aspect-square w-full object-cover transition hover:scale-[1.01]"
                    />
                    <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 via-black/10 to-transparent px-3 py-3 text-[11px] uppercase tracking-[0.18em] text-neutral-300">
                      <span>{sourceLabel(image)}</span>
                      <span>{image.detections.length} Box</span>
                    </div>
                  </div>
                </button>
                <div className="mt-3 flex items-center justify-between gap-3">
                  <span className="rounded-full border border-neutral-200 px-2 py-1 text-[11px] uppercase tracking-[0.2em] text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                    {image.status}
                  </span>
                  <span className="rounded-full border border-neutral-200 px-2 py-1 text-[11px] uppercase tracking-[0.2em] text-neutral-500 dark:border-white/10">
                    #{image.ordinal}
                  </span>
                </div>
                <div className="mt-3 flex items-center justify-between text-xs text-neutral-500">
                  <span>{image.annotationStatus}</span>
                  <span>{image.latencyMs}ms</span>
                </div>
                <div className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">{image.diversityVars.composition}</div>
                <button
                  className="mt-2 text-left text-xs text-neutral-500 transition hover:text-neutral-900 dark:hover:text-white"
                  onClick={() => openPreview(image.id)}
                  type="button"
                >
                  查看 Prompt / Seed / 标注框
                </button>
                <Button
                  className="mt-3 w-full"
                  variant={image.selected ? "primary" : "secondary"}
                  onClick={() =>
                    void applySelection({
                      mode: "single",
                      image_id: image.id,
                      selected: !image.selected,
                    })
                  }
                >
                  {image.selected ? "保留中" : "重新保留"}
                </Button>
              </div>
            ))}
          </div>
        </SectionCard>

        <div className="space-y-6">
          <SectionCard>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Augmentation</div>
            <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">数据增强</h3>
            <p className="mt-4 text-sm text-neutral-500">先选增强方式，再设置扩增倍数。</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {augmentationOptions.map((option) => {
                const active = augmentationMethods.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={`rounded-full border px-3 py-2 text-sm transition ${active ? "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950" : "border-neutral-200 text-neutral-600 dark:border-white/10 dark:text-neutral-300 dark:hover:border-white/20 dark:hover:bg-white/[0.04]"}`}
                    onClick={() => toggleAugmentationMethod(option.value)}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {augmentationOptions
                .filter((option) => augmentationMethods.includes(option.value))
                .map((option) => (
                  <div
                    key={option.value}
                    className="rounded-2xl border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/30 dark:text-neutral-300"
                  >
                    <div className="text-neutral-900 dark:text-white">{option.label}</div>
                    <div className="mt-1 text-xs text-neutral-500">{option.desc}</div>
                  </div>
                ))}
            </div>
            <div className="mt-4 flex items-center gap-3">
              <Input
                type="number"
                min={1}
                max={20}
                value={multiplier}
                onChange={(event) => setMultiplier(Number(event.target.value))}
              />
              <Button
                disabled={augmentationMethods.length === 0 || selectedOriginalCount === 0 || isAugmenting}
                onClick={() => {
                  if (!token || !taskId) return;
                  void augmentTask(taskId, token, multiplier, augmentationMethods)
                    .then((data) => {
                      setTask(data.task);
                      setActionError(null);
                    })
                    .catch((error) => setActionError((error as Error).message));
                }}
              >
                {isAugmenting ? "增强中..." : "运行增强"}
              </Button>
            </div>
            {augmentationMethods.length === 0 ? (
              <div className="mt-3 text-sm text-amber-700 dark:text-amber-200">至少选择 1 种增强方式。</div>
            ) : null}
            {selectedOriginalCount === 0 ? (
              <div className="mt-3 text-sm text-amber-700 dark:text-amber-200">至少保留 1 张原始图片后才能运行增强，增强图不会再次参与增强。</div>
            ) : null}
            {augmentationSummary ? (
              <div className="mt-4 rounded-2xl border border-neutral-200 bg-neutral-100 px-4 py-4 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/30 dark:text-neutral-300">
                <div className="text-neutral-900 dark:text-white">
                  {isAugmenting ? "增强任务进行中" : "增强任务已更新"}
                </div>
                {typeof augmentationSummary.progressPercent === "number" ? (
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-white/10">
                    <div
                      className="h-full rounded-full bg-neutral-900 transition-all duration-500 dark:bg-white"
                      style={{ width: `${augmentationSummary.progressPercent}%` }}
                    />
                  </div>
                ) : null}
                <div className="mt-2 leading-7">
                  基于 {augmentationSummary.sourceCount} 张原始图片，已选 {augmentationSummary.methods.length} 种方式，
                  预计新增 {augmentationSummary.estimatedAddedImages} 张，增强后总量 {augmentationSummary.simulatedOutput} 张。
                </div>
                <div className="mt-2 text-xs text-neutral-500">
                  当前进度 {augmentationSummary.completedImages}/{augmentationSummary.totalImagesToCreate}
                  {typeof augmentationSummary.progressPercent === "number"
                    ? ` · ${augmentationSummary.progressPercent}%`
                    : ""}
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-neutral-500">还没有运行增强。选择方式后点击“运行增强”即可生成增强计划。</p>
            )}
          </SectionCard>

          <SectionCard>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Annotation</div>
            <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">自动标注</h3>
            <div className="mt-4 flex items-center gap-3">
              <Input
                type="number"
                min={0.3}
                max={0.95}
                step={0.05}
                value={confidenceThreshold}
                onChange={(event) => setConfidenceThreshold(Number(event.target.value))}
              />
              <Button
                onClick={() => {
                  if (!token || !taskId) return;
                  void annotateTask(taskId, token, confidenceThreshold)
                    .then((data) => {
                      setTask(data.task);
                      setActionError(null);
                    })
                    .catch((error) => setActionError((error as Error).message));
                }}
              >
                生成 YOLO 标注
              </Button>
            </div>
            <p className="mt-4 text-sm text-neutral-500">
              检测到 {String(task.config.annotation?.detectedImages ?? 0)} 张图片带有效目标。
            </p>
          </SectionCard>

          <SectionCard>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Export</div>
            <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">导出数据集</h3>
            <div className="mt-4 flex items-center gap-3">
              <Select
                value={exportFormat}
                onChange={(event) => setExportFormat(event.target.value as typeof exportFormat)}
              >
                <option value="yolo">YOLOv8</option>
                <option value="coco">COCO</option>
                <option value="voc">Pascal VOC</option>
                <option value="csv">CSV</option>
              </Select>
              <Button
                disabled={task.selectedCount === 0}
                onClick={async () => {
                  if (!token || !taskId) return;
                  setExportError(null);
                  try {
                    const data = await exportTask(taskId, token, exportFormat, "keep");
                    setTask(data.task);
                  } catch (error) {
                    setExportError((error as Error).message);
                  }
                }}
              >
                生成下载包
              </Button>
            </div>
            {exportError ? <div className="mt-3 text-sm text-red-600 dark:text-red-300">{exportError}</div> : null}
            {task.selectedCount === 0 ? (
              <div className="mt-3 text-sm text-amber-700 dark:text-amber-200">至少保留 1 张图片后才能导出。</div>
            ) : null}
            <div className="mt-4 space-y-3">
              {task.exports.map((exportJob) => (
                <div key={exportJob.id} className="rounded-2xl border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/30">
                  <div className="flex items-center justify-between text-sm text-neutral-900 dark:text-white">
                    <span>v{exportJob.version} · {exportJob.exportFormat.toUpperCase()}</span>
                    <span className="text-neutral-500">{formatDate(exportJob.createdAt)}</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <div className="text-xs text-neutral-500">
                      {String(exportJob.summary.structure ?? "")} · {String(exportJob.summary.imageFormat ?? "")} · {String(exportJob.summary.estimatedSizeMb ?? "")} MB
                    </div>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        if (!token) return;
                        void downloadWithToken(
                          exportJob.downloadUrl,
                          token,
                          `dataset-export-v${exportJob.version}.zip`,
                        ).catch((error) => setActionError((error as Error).message));
                      }}
                    >
                      下载
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </div>

      {previewImage ? (
        <div className="fixed inset-0 z-50 bg-black/88 backdrop-blur-md">
          <div className="flex min-h-full items-center justify-center p-4 xl:p-8">
            <div className="grid max-h-[94vh] w-full max-w-7xl gap-4 xl:grid-cols-[minmax(0,1.2fr)_400px]">
              <div className="rounded-[28px] border border-white/10 bg-neutral-950 p-4 shadow-panel">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{sourceLabel(previewImage)}</Badge>
                    <Badge>{previewImage.status}</Badge>
                    <Badge>{previewImage.selected ? "Selected" : "Dropped"}</Badge>
                    <Badge>{previewImage.annotationStatus}</Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="secondary" disabled={previewIndex <= 0} onClick={() => movePreview(-1)}>
                      <ChevronLeft className="mr-1 h-4 w-4" />
                      上一张
                    </Button>
                    <Button variant="secondary" disabled={previewIndex >= images.length - 1} onClick={() => movePreview(1)}>
                      下一张
                      <ChevronRight className="ml-1 h-4 w-4" />
                    </Button>
                    <Button variant="secondary" onClick={() => openPreview(null)}>
                      <X className="mr-2 h-4 w-4" />
                      关闭
                    </Button>
                  </div>
                </div>

                <div
                  ref={stageRef}
                  className={`relative overflow-hidden rounded-[24px] border bg-black ${isAddingDetection ? "cursor-crosshair border-white/30" : "border-white/10"}`}
                  onMouseDown={handleStageMouseDown}
                >
                  <AuthImage
                    src={previewImage.previewSvg}
                    alt={`preview-large-${previewImage.ordinal}`}
                    className="max-h-[68vh] w-full object-contain"
                  />
                  <div className="absolute inset-0">
                    {draftDetections.map((detection, index) => (
                      <div
                        key={`${detection.category}-${index}`}
                        className={`pointer-events-auto absolute cursor-move border shadow-[0_0_0_1px_rgba(0,0,0,0.5)] ${selectedDetectionIndex === index ? "border-white" : "border-white/80"}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedDetectionIndex(index);
                        }}
                        onMouseDown={(event) => {
                          setSelectedDetectionIndex(index);
                          beginDragDetection(index, event);
                        }}
                        style={detectionStyle(detection.bbox)}
                      >
                        <div className="absolute left-0 top-0 -translate-y-full rounded-t-md bg-white px-2 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-black">
                          {detection.category} {detection.confidence.toFixed(2)}
                        </div>
                        {selectedDetectionIndex === index
                          ? (["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
                              <button
                                key={corner}
                                className={`absolute h-3 w-3 rounded-full border border-black bg-white ${corner === "nw" ? "-left-1.5 -top-1.5 cursor-nwse-resize" : ""} ${corner === "ne" ? "-right-1.5 -top-1.5 cursor-nesw-resize" : ""} ${corner === "sw" ? "-bottom-1.5 -left-1.5 cursor-nesw-resize" : ""} ${corner === "se" ? "-bottom-1.5 -right-1.5 cursor-nwse-resize" : ""}`}
                                onMouseDown={(event) => beginResizeDetection(index, corner, event)}
                                type="button"
                              />
                            ))
                          : null}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-between gap-4 rounded-[22px] border border-white/10 bg-white/[0.03] px-4 py-3">
                  <div className="text-sm text-neutral-400">
                    {previewIndex + 1} / {images.length} · Seed {previewImage.seed} · {draftDetections.length} 个候选框
                  </div>
                  <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
                    Esc 关闭 · ← → 切换 · Delete 删除 · 拖拽框移动/缩放
                  </div>
                </div>

                <div className="mt-4 flex gap-3">
                  <Button
                    variant={isAddingDetection ? "primary" : "secondary"}
                    onClick={() => {
                      setIsAddingDetection((current) => !current);
                      setSelectedDetectionIndex(null);
                    }}
                  >
                    {isAddingDetection ? "取消补框" : "新增框"}
                  </Button>
                  <div className="flex items-center text-sm text-neutral-500">
                    {isAddingDetection ? "在图片上按下并拖拽，直接画出新框。" : "先选中框再编辑，或开启补框模式新增。"}
                  </div>
                </div>

                <div className="mt-4 flex gap-3 overflow-x-auto pb-1">
                  {images.map((image) => (
                    <button
                      key={image.id}
                      className={`relative h-20 min-w-20 overflow-hidden rounded-[18px] border transition ${image.id === previewImage.id ? "border-white/30" : "border-white/10 opacity-70 hover:opacity-100"}`}
                      onClick={() => openPreview(image.id)}
                      type="button"
                    >
                      <AuthImage src={image.previewSvg} alt={`thumb-${image.ordinal}`} className="h-full w-full object-cover" />
                      <div className="absolute inset-x-0 bottom-0 bg-black/70 px-2 py-1 text-[10px] text-neutral-300">
                        #{image.ordinal}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="overflow-y-auto rounded-[28px] border border-white/10 bg-neutral-950/95 p-6 shadow-panel">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Image Review</div>
                <h3 className="mt-3 text-2xl text-white">样本 #{previewImage.ordinal}</h3>
                <p className="mt-2 text-sm leading-7 text-neutral-400">
                  用这张图确认 prompt 质量、标注结果和保留状态。审核操作会直接影响导出集。
                </p>

                <div className="mt-5 grid grid-cols-2 gap-3">
                  <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">Seed</div>
                    <div className="mt-2 text-white">{previewImage.seed}</div>
                  </div>
                  <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">Latency</div>
                    <div className="mt-2 text-white">{previewImage.latencyMs}ms</div>
                  </div>
                  <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">Annotation</div>
                    <div className="mt-2 text-white">{previewImage.annotationStatus}</div>
                  </div>
                  <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">Confidence</div>
                    <div className="mt-2 text-white">
                      {previewImage.confidenceScore ? previewImage.confidenceScore.toFixed(2) : "N/A"}
                    </div>
                  </div>
                </div>

                <div className="mt-6 rounded-[24px] border border-white/10 bg-black/30 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Detections</div>
                    <div className="text-xs text-neutral-500">{draftDetections.length} 个候选结果</div>
                  </div>
                  <div className="mt-3 space-y-3">
                    {draftDetections.length ? (
                      draftDetections.map((detection, index) => (
                        <div
                          key={`${detection.category}-${index}`}
                          className={`rounded-[18px] border bg-white/[0.03] p-3 transition ${selectedDetectionIndex === index ? "border-white/30" : "border-white/10"}`}
                        >
                          <div className="flex items-center justify-between gap-3 text-sm">
                            <button
                              className="text-white"
                              onClick={() => setSelectedDetectionIndex(index)}
                              type="button"
                            >
                              {detection.category}
                            </button>
                            <div className="flex items-center gap-3">
                              <span className="text-neutral-400">{detection.confidence.toFixed(2)}</span>
                              <button
                                className="text-xs text-neutral-500 transition hover:text-white"
                                onClick={() => removeDetection(index)}
                                type="button"
                              >
                                删除
                              </button>
                            </div>
                          </div>
                          <div className="mt-2 text-xs text-neutral-500">
                            bbox {detection.bbox.map((value) => value.toFixed(3)).join(" / ")}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-[18px] border border-dashed border-white/10 px-4 py-5 text-sm text-neutral-500">
                        当前没有有效标注框，可作为负样本保留或重新跑标注。
                      </div>
                    )}
                  </div>
                </div>

                {selectedDetection ? (
                  <div className="mt-6 rounded-[24px] border border-white/10 bg-black/30 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Selected Detection</div>
                      <div className="text-xs text-neutral-500">#{selectedDetectionIndex! + 1}</div>
                    </div>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <label className="space-y-2">
                        <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">Category</div>
                        <Input
                          value={selectedDetection.category}
                          onChange={(event) =>
                            selectedDetectionIndex !== null &&
                            updateDetectionField(selectedDetectionIndex, "category", event.target.value)
                          }
                        />
                      </label>
                      <label className="space-y-2">
                        <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">Confidence</div>
                        <Input
                          type="number"
                          min={0}
                          max={1}
                          step={0.01}
                          value={selectedDetection.confidence}
                          onChange={(event) =>
                            selectedDetectionIndex !== null &&
                            updateDetectionField(selectedDetectionIndex, "confidence", Number(event.target.value))
                          }
                        />
                      </label>
                    </div>
                  </div>
                ) : null}

                <div className="mt-6 rounded-[24px] border border-white/10 bg-black/30 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Prompt</div>
                  <p className="mt-3 text-sm leading-7 text-neutral-300">{previewImage.promptText}</p>
                </div>

                <div className="mt-6 rounded-[24px] border border-white/10 bg-black/30 p-4">
                  <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Diversity Variables</div>
                  <div className="mt-3 space-y-3">
                    {Object.entries(previewImage.diversityVars).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between gap-4 text-sm">
                        <span className="text-neutral-500">{key}</span>
                        <span className="text-right text-neutral-200">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-6 flex gap-3">
                  <Button
                    className="flex-1"
                    disabled={!hasAnnotationChanges}
                    variant="secondary"
                    onClick={() => {
                      setDraftDetections(previewImage.detections);
                      setSelectedDetectionIndex(null);
                      setIsAddingDetection(false);
                    }}
                  >
                    重置改动
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={!hasAnnotationChanges || isSavingAnnotations}
                    onClick={() => void saveAnnotations()}
                  >
                    {isSavingAnnotations ? "保存中..." : "保存标注"}
                  </Button>
                </div>

                <Button
                  className="mt-6 w-full"
                  variant={previewImage.selected ? "primary" : "secondary"}
                  onClick={() =>
                    void applySelection({
                      mode: "single",
                      image_id: previewImage.id,
                      selected: !previewImage.selected,
                    })
                  }
                >
                  {previewImage.selected ? "取消保留此样本" : "重新保留此样本"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
