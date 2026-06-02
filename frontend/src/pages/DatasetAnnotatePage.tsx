import { useContext, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ImageOff,
  Loader2,
  MousePointer2,
  PencilRuler,
  Save,
  Trash2,
} from "lucide-react";
import { Link, UNSAFE_NavigationContext, useParams } from "react-router-dom";

import { deleteDatasetImage, getDataset, updateDatasetImageAnnotations } from "../api/datasets";
import { AuthImage } from "../components/AuthImage";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import {
  boxFromCorners,
  DEFAULT_BOX_SIZE,
  detectionStyle,
  detectionsEqual,
  fitImageViewport,
  pointerToStage,
  type Detection,
  type ImageViewport,
  type ResizeCorner,
} from "../lib/annotation";
import type { Dataset, DatasetImage } from "../lib/types";
import { cn } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const categoryPalette = ["#38bdf8", "#f59e0b", "#84cc16", "#fb7185", "#a78bfa", "#2dd4bf", "#f97316", "#e879f9", "#94a3b8"];
const unsavedAnnotationMessage = "当前图片有未保存的标注改动，确认放弃并继续？";

function annotationStatusLabel(status: string) {
  const labels: Record<string, string> = {
    annotated: "已标注",
    empty: "空标注",
    pending: "待标注",
    generated: "待标注",
  };
  return labels[status] ?? (status || "待标注");
}

function isProcessed(status: string) {
  return status === "annotated" || status === "empty";
}

function categoryColor(category: string, categories: string[]) {
  const index = Math.max(categories.indexOf(category), 0);
  return categoryPalette[index % categoryPalette.length];
}

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}

export function DatasetAnnotatePage() {
  const token = useAuthStore((state) => state.token);
  const { datasetId } = useParams();
  const navigation = useContext(UNSAFE_NavigationContext);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [activeImageId, setActiveImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<Detection[]>([]);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [deletingImageId, setDeletingImageId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [currentCategory, setCurrentCategory] = useState("object");
  const [previewImageNaturalSize, setPreviewImageNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [imageViewport, setImageViewport] = useState<ImageViewport | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  const images = dataset?.images ?? [];
  const categories = dataset?.categories ?? [];
  const activeIndex = activeImageId ? images.findIndex((image) => image.id === activeImageId) : images.length > 0 ? 0 : -1;
  const activeImage = activeIndex >= 0 ? images[activeIndex] : null;
  const processedCount = useMemo(() => images.filter((image) => isProcessed(image.annotationStatus)).length, [images]);
  const activeCategory = currentCategory || categories[0] || "object";
  const hasAnnotationChanges = activeImage !== null && !detectionsEqual(activeImage.detections, draftDetections);
  const canSave = activeImage !== null && !deletingImageId && (hasAnnotationChanges || !isProcessed(activeImage.annotationStatus));
  const isDeletingActiveImage = Boolean(activeImage && deletingImageId === activeImage.id);

  useEffect(() => {
    if (!token || !datasetId) return;

    let disposed = false;
    void getDataset(datasetId, token)
      .then((response) => {
        if (disposed) return;
        setDataset(response.dataset);
        setActiveImageId((current) => {
          if (current && response.dataset.images.some((image) => image.id === current)) return current;
          return response.dataset.images[0]?.id ?? null;
        });
        setActionError(null);
      })
      .catch((error) => {
        if (!disposed) {
          setActionError((error as Error).message);
        }
      });

    return () => {
      disposed = true;
    };
  }, [datasetId, token]);

  useEffect(() => {
    if (categories.length === 0) {
      setCurrentCategory("object");
      return;
    }
    setCurrentCategory((current) => (categories.includes(current) ? current : categories[0]));
  }, [categories]);

  useEffect(() => {
    setDraftDetections(activeImage?.detections ?? []);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(false);
  }, [activeImage]);

  useEffect(() => {
    setPreviewImageNaturalSize(null);
    setImageViewport(null);
  }, [activeImage?.id]);

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
    if (!activeImage || !hasAnnotationChanges) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [activeImage, hasAnnotationChanges]);

  useEffect(() => {
    if (!hasAnnotationChanges) return;

    const navigator = navigation.navigator;
    const originalPush = navigator.push;
    const originalReplace = navigator.replace;
    const originalGo = navigator.go;
    const confirmNavigation = () => window.confirm(unsavedAnnotationMessage);

    navigator.push = (...args) => {
      if (confirmNavigation()) {
        originalPush.apply(navigator, args);
      }
    };
    navigator.replace = (...args) => {
      if (confirmNavigation()) {
        originalReplace.apply(navigator, args);
      }
    };
    navigator.go = (...args) => {
      if (confirmNavigation()) {
        originalGo.apply(navigator, args);
      }
    };

    return () => {
      navigator.push = originalPush;
      navigator.replace = originalReplace;
      navigator.go = originalGo;
    };
  }, [hasAnnotationChanges, navigation.navigator]);

  useEffect(() => {
    if (!activeImage) return;
    const handleKeydown = (event: KeyboardEvent) => {
      const isSaveShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (isSaveShortcut) {
        event.preventDefault();
        void saveAnnotations();
        return;
      }

      if (isEditableTarget(event.target)) return;

      if (event.key === "a" || event.key === "A") {
        event.preventDefault();
        setIsAddingDetection((current) => !current);
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        if (selectedDetectionIndex !== null) {
          event.preventDefault();
          removeDetection(selectedDetectionIndex);
        }
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        moveActiveImage(-1);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        moveActiveImage(1);
        return;
      }
      if (/^[1-9]$/.test(event.key)) {
        const category = categories[Number(event.key) - 1];
        if (category) {
          event.preventDefault();
          setCurrentCategory(category);
          if (selectedDetectionIndex !== null) {
            updateDetectionCategory(selectedDetectionIndex, category);
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [activeImage, categories, selectedDetectionIndex, hasAnnotationChanges, draftDetections]);

  function confirmDiscardChanges() {
    if (!hasAnnotationChanges) return true;
    return window.confirm(unsavedAnnotationMessage);
  }

  function selectImage(imageId: string) {
    if (!confirmDiscardChanges()) return;
    setActiveImageId(imageId);
    setActionError(null);
  }

  function moveActiveImage(direction: -1 | 1) {
    if (!activeImage) return;
    const nextIndex = activeIndex + direction;
    if (nextIndex < 0 || nextIndex >= images.length) return;
    selectImage(images[nextIndex].id);
  }

  async function saveAnnotations() {
    if (!token || !datasetId || !activeImage || deletingImageId) return;
    setIsSaving(true);
    try {
      const response = await updateDatasetImageAnnotations(datasetId, activeImage.id, token, draftDetections);
      setDataset(response.dataset);
      setActiveImageId(activeImage.id);
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsSaving(false);
    }
  }

  async function removeDatasetImage(image: DatasetImage) {
    if (!token || !datasetId || deletingImageId) return;
    const discardsActiveDraft = image.id === activeImage?.id && hasAnnotationChanges;
    const confirmed = window.confirm(
      `删除样本 #${image.ordinal}？图片文件和标注也会一起移除。${discardsActiveDraft ? " 当前未保存的标注改动也会放弃。" : ""}`,
    );
    if (!confirmed) return;

    setDeletingImageId(image.id);
    try {
      const response = await deleteDatasetImage(datasetId, image.id, token);
      const deletedIdSet = new Set(response.deletedImageIds);
      const nextImages = response.dataset.images;
      const deletedIndex = images.findIndex((candidate) => candidate.id === image.id);
      const fallbackIndex = deletedIndex >= 0 ? Math.min(deletedIndex, nextImages.length - 1) : 0;

      setDataset(response.dataset);
      setActiveImageId((current) => {
        if (current && !deletedIdSet.has(current) && nextImages.some((candidate) => candidate.id === current)) {
          return current;
        }
        return nextImages[fallbackIndex]?.id ?? null;
      });
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setDeletingImageId(null);
    }
  }

  function beginDragDetection(index: number, event: ReactMouseEvent<HTMLDivElement>) {
    if (!viewportRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedDetectionIndex(index);
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
    setSelectedDetectionIndex(index);
    const rect = viewportRef.current.getBoundingClientRect();
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
    if (!viewportRef.current) return;
    if (!isAddingDetection) {
      setSelectedDetectionIndex(null);
      return;
    }

    event.preventDefault();
    const rect = viewportRef.current.getBoundingClientRect();
    const start = pointerToStage(rect, event.clientX, event.clientY);
    const nextIndex = draftDetections.length;

    setDraftDetections((current) => [
      ...current,
      { category: activeCategory, confidence: 1, bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE] },
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

  function updateDetectionCategory(index: number, category: string) {
    setDraftDetections((current) =>
      current.map((detection, detectionIndex) =>
        detectionIndex === index ? { ...detection, category: category.slice(0, 120) || "object" } : detection,
      ),
    );
  }

  function updateDetectionConfidence(index: number, value: number) {
    setDraftDetections((current) =>
      current.map((detection, detectionIndex) => {
        if (detectionIndex !== index) return detection;
        return {
          ...detection,
          confidence: Number.isFinite(value) ? Math.min(Math.max(value, 0), 1) : detection.confidence,
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
      <div className="flex min-h-screen items-center justify-center bg-white dark:bg-neutral-950">
        <div className="flex items-center gap-3 text-sm text-neutral-500 dark:text-neutral-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载标注工作台...
        </div>
      </div>
    );
  }

  if (images.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white p-8 text-center dark:bg-neutral-950">
        <div>
          <ImageOff className="mx-auto h-10 w-10 text-neutral-400" />
          <h2 className="mt-4 text-2xl text-neutral-900 dark:text-white">暂无可标注图片</h2>
          <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">导入或生成样本后再进入标注模式。</p>
          <Link to={`/datasets/${dataset.id}`} className="mt-6 inline-flex">
            <Button variant="secondary">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回数据集
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen min-h-0 w-full flex-col overflow-hidden bg-neutral-100 text-neutral-900 dark:bg-neutral-950 dark:text-white">
      <div className="shrink-0 border-b border-neutral-200 bg-white px-4 py-3 dark:border-white/10 dark:bg-neutral-950">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <Link to={`/datasets/${dataset.id}`}>
              <Button variant="ghost" className="h-9 px-3" title="返回数据集">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-neutral-500">
                <PencilRuler className="h-4 w-4" />
                Annotation Mode
              </div>
              <h2 className="truncate text-lg font-medium text-neutral-900 dark:text-white">{dataset.name}</h2>
            </div>
            <Badge>{processedCount} / {images.length}</Badge>
            {hasAnnotationChanges ? (
              <Badge>未保存</Badge>
            ) : activeImage && !isProcessed(activeImage.annotationStatus) ? (
              <Badge>待确认</Badge>
            ) : (
              <Badge>已同步</Badge>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {actionError ? <span className="max-w-[280px] truncate text-sm text-red-600 dark:text-red-300">{actionError}</span> : null}
            <Button variant="secondary" className="h-9 px-3" onClick={() => moveActiveImage(-1)} disabled={activeIndex <= 0 || Boolean(deletingImageId)}>
              <ChevronLeft className="mr-1.5 h-4 w-4" />
              上一张
            </Button>
            <Button variant="secondary" className="h-9 px-3" onClick={() => moveActiveImage(1)} disabled={activeIndex >= images.length - 1 || Boolean(deletingImageId)}>
              下一张
              <ChevronRight className="ml-1.5 h-4 w-4" />
            </Button>
            <Button
              variant="secondary"
              className="h-9 border-red-200 px-3 text-red-700 hover:border-red-300 hover:bg-red-50 dark:border-red-400/30 dark:text-red-200 dark:hover:border-red-300/40 dark:hover:bg-red-500/10"
              onClick={() => activeImage && void removeDatasetImage(activeImage)}
              disabled={!activeImage || isSaving || Boolean(deletingImageId)}
            >
              {isDeletingActiveImage ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
              删除图片
            </Button>
            <Button onClick={() => void saveAnnotations()} disabled={isSaving || !canSave}>
              {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              保存
            </Button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 overflow-hidden xl:grid-cols-[300px_minmax(0,1fr)_390px]">
        <aside className="flex min-h-0 flex-col border-b border-neutral-200 bg-white dark:border-white/10 dark:bg-neutral-950 xl:border-b-0 xl:border-r">
          <div className="shrink-0 border-b border-neutral-200 px-4 py-3 dark:border-white/10">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Queue</div>
                <div className="text-sm text-neutral-900 dark:text-white">{images.length} 张样本</div>
              </div>
              <CheckCircle2 className="h-5 w-5 text-neutral-400" />
            </div>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            {images.map((image, index) => {
              const active = image.id === activeImage?.id;
              return (
                <button
                  key={image.id}
                  type="button"
                  className={cn(
                    "grid w-full grid-cols-[56px_minmax(0,1fr)] gap-3 rounded-2xl border p-2 text-left transition",
                    active
                      ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.06]"
                      : "border-transparent hover:border-neutral-200 hover:bg-neutral-100 dark:hover:border-white/10 dark:hover:bg-white/[0.04]",
                  )}
                  onClick={() => selectImage(image.id)}
                >
                  <div className="relative aspect-square overflow-hidden rounded-xl bg-neutral-200 dark:bg-neutral-800">
                    <AuthImage src={image.previewSvg} alt={image.promptText} className="h-full w-full object-cover" />
                    <div className="absolute left-1.5 top-1.5 rounded-full bg-black/70 px-1.5 py-0.5 text-[10px] text-white">
                      {index + 1}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm text-neutral-900 dark:text-white">#{image.ordinal}</span>
                      <span className="text-xs text-neutral-500">{image.detections.length}</span>
                    </div>
                    <div className="mt-1 truncate text-xs text-neutral-500">{annotationStatusLabel(image.annotationStatus)}</div>
                    <div className="mt-1 truncate text-[11px] text-neutral-400">{image.selected ? "已保留" : image.sourceType}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        <main className="flex min-h-0 flex-col bg-neutral-950">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3 text-white">
            <div className="flex min-w-0 items-center gap-3">
              <MousePointer2 className="h-4 w-4 text-neutral-400" />
              <div className="min-w-0">
                <div className="truncate text-sm">样本 #{activeImage?.ordinal}</div>
                <div className="truncate text-xs text-neutral-400">{activeImage?.sourceType}</div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant={isAddingDetection ? "primary" : "secondary"}
                className={cn(
                  "h-9",
                  isAddingDetection ? "dark:bg-lime-300 dark:text-neutral-950" : "dark:border-white/15 dark:bg-white/10 dark:text-white dark:hover:bg-white/15",
                )}
                onClick={() => setIsAddingDetection((current) => !current)}
              >
                <PencilRuler className="mr-2 h-4 w-4" />
                {isAddingDetection ? "正在画框" : "新增框"}
              </Button>
              <Badge>{draftDetections.length} boxes</Badge>
            </div>
          </div>

          <div ref={stageRef} className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden p-5">
            {activeImage && imageViewport && imageViewport.width > 0 && imageViewport.height > 0 ? (
              <div
                ref={viewportRef}
                className={cn("relative select-none", isAddingDetection ? "cursor-crosshair" : "cursor-default")}
                style={{ width: imageViewport.width, height: imageViewport.height }}
                onMouseDown={handleStageMouseDown}
              >
                <AuthImage
                  src={activeImage.previewSvg}
                  alt={activeImage.promptText}
                  className="h-full w-full"
                  draggable={false}
                  onLoad={(event) => {
                    const target = event.currentTarget;
                    setPreviewImageNaturalSize({ width: target.naturalWidth, height: target.naturalHeight });
                  }}
                />
                <div className="pointer-events-none absolute inset-0">
                  {draftDetections.map((detection, index) => {
                    const selected = selectedDetectionIndex === index;
                    const color = selected ? "#bef264" : categoryColor(detection.category, categories);
                    return (
                      <div
                        key={`${detection.category}-${index}`}
                        className={cn(
                          "pointer-events-auto absolute rounded-lg border-2 shadow-[0_0_0_1px_rgba(0,0,0,0.35)]",
                          selected ? "shadow-[0_0_0_9999px_rgba(0,0,0,0.08)]" : "",
                        )}
                        style={{ ...detectionStyle(detection.bbox), borderColor: color }}
                        onMouseDown={(event) => beginDragDetection(index, event)}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedDetectionIndex(index);
                        }}
                      >
                        <div
                          className="absolute left-0 top-0 max-w-full -translate-y-full truncate rounded-t-md px-2 py-1 text-[11px] font-medium text-neutral-950"
                          style={{ backgroundColor: color }}
                        >
                          {detection.category} · {(detection.confidence * 100).toFixed(0)}%
                        </div>
                        {(["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
                          <button
                            key={corner}
                            type="button"
                            title="缩放检测框"
                            className={cn(
                              "absolute h-3.5 w-3.5 rounded-full border border-white bg-neutral-950",
                              corner === "nw"
                                ? "-left-2 -top-2"
                                : corner === "ne"
                                  ? "-right-2 -top-2"
                                  : corner === "sw"
                                    ? "-bottom-2 -left-2"
                                    : "-bottom-2 -right-2",
                            )}
                            onMouseDown={(event) => beginResizeDetection(index, corner, event)}
                          />
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : activeImage ? (
              <AuthImage
                src={activeImage.previewSvg}
                alt={activeImage.promptText}
                className="max-h-full max-w-full object-contain"
                draggable={false}
                onLoad={(event) => {
                  const target = event.currentTarget;
                  setPreviewImageNaturalSize({ width: target.naturalWidth, height: target.naturalHeight });
                }}
              />
            ) : null}
          </div>
        </main>

        <aside className="flex min-h-0 flex-col border-t border-neutral-200 bg-white dark:border-white/10 dark:bg-neutral-950 xl:border-l xl:border-t-0">
          <div className="shrink-0 border-b border-neutral-200 px-4 py-4 dark:border-white/10">
            <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Categories</div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {(categories.length > 0 ? categories : ["object"]).map((category, index) => {
                const active = category === activeCategory;
                return (
                  <button
                    key={category}
                    type="button"
                    className={cn(
                      "flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition",
                      active
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                        : "border-neutral-200 text-neutral-600 hover:bg-neutral-100 dark:border-white/10 dark:text-neutral-300 dark:hover:bg-white/[0.05]",
                    )}
                    onClick={() => {
                      setCurrentCategory(category);
                      if (selectedDetectionIndex !== null) {
                        updateDetectionCategory(selectedDetectionIndex, category);
                      }
                    }}
                  >
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: categoryColor(category, categories) }} />
                    <span className="truncate">{index + 1}. {category}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="shrink-0 border-b border-neutral-200 px-4 py-4 dark:border-white/10">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Current Image</div>
                <div className="mt-1 text-lg text-neutral-900 dark:text-white">#{activeImage?.ordinal}</div>
              </div>
              <Badge>{annotationStatusLabel(activeImage?.annotationStatus ?? "")}</Badge>
            </div>
            <p className="mt-3 line-clamp-4 text-sm leading-6 text-neutral-500 dark:text-neutral-400">{activeImage?.promptText}</p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Annotations</div>
                <div className="text-sm text-neutral-900 dark:text-white">{draftDetections.length} 个检测框</div>
              </div>
              <Button
                variant="secondary"
                className="h-9 px-3"
                onClick={() => {
                  const nextIndex = draftDetections.length;
                  setDraftDetections((current) => [
                    ...current,
                    { category: activeCategory, confidence: 1, bbox: [0.5, 0.5, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE] },
                  ]);
                  setSelectedDetectionIndex(nextIndex);
                }}
              >
                <PencilRuler className="h-4 w-4" />
              </Button>
            </div>

            <div className="space-y-3">
              {draftDetections.map((detection, index) => {
                const selected = selectedDetectionIndex === index;
                return (
                  <div
                    key={`${detection.category}-${index}`}
                    className={cn(
                      "rounded-2xl border p-3 transition",
                      selected
                        ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.06]"
                        : "border-neutral-200 bg-white dark:border-white/10 dark:bg-black/20",
                    )}
                    onClick={() => setSelectedDetectionIndex(index)}
                  >
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: categoryColor(detection.category, categories) }} />
                        <span className="truncate text-sm text-neutral-900 dark:text-white">Box {index + 1}</span>
                      </div>
                      <button
                        type="button"
                        title="删除检测框"
                        className="rounded-full p-1.5 text-neutral-500 transition hover:bg-neutral-200 hover:text-neutral-900 dark:hover:bg-white/10 dark:hover:text-white"
                        onClick={(event) => {
                          event.stopPropagation();
                          removeDetection(index);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="grid gap-3">
                      {categories.length > 0 ? (
                        <Select
                          value={detection.category}
                          onChange={(event) => updateDetectionCategory(index, event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                        >
                          {categories.map((category) => (
                            <option key={category} value={category}>{category}</option>
                          ))}
                        </Select>
                      ) : (
                        <Input
                          value={detection.category}
                          onChange={(event) => updateDetectionCategory(index, event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                        />
                      )}
                      <label className="grid gap-2">
                        <span className="text-[11px] uppercase tracking-[0.18em] text-neutral-500">
                          Confidence {(detection.confidence * 100).toFixed(0)}%
                        </span>
                        <Input
                          type="number"
                          min={0}
                          max={1}
                          step={0.01}
                          value={detection.confidence}
                          onChange={(event) => updateDetectionConfidence(index, Number(event.target.value))}
                          onClick={(event) => event.stopPropagation()}
                        />
                      </label>
                    </div>
                  </div>
                );
              })}
              {draftDetections.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-neutral-200 p-4 text-sm leading-6 text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                  当前图片没有检测框。
                </div>
              ) : null}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
