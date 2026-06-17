import { useContext, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ImageOff,
  ListFilter,
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
import { segmentedButtonClasses, segmentedGroupClasses } from "../components/ui/segmentedStyles";
import {
  boxFromCorners,
  DEFAULT_BOX_SIZE,
  detectionStyle,
  detectionsEqual,
  fitImageViewport,
  minimumBoxSizeForImage,
  pointerToStage,
  type Detection,
  type ImageViewport,
  type ResizeCorner,
} from "../lib/annotation";
import type { Dataset, DatasetImage, ImageFilter } from "../lib/types";
import { cn } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const categoryPalette = ["#38bdf8", "#f59e0b", "#84cc16", "#fb7185", "#a78bfa", "#2dd4bf", "#f97316", "#e879f9", "#94a3b8"];
const unsavedAnnotationMessage = "当前图片有未保存的标注改动，确认放弃并继续？";
const PAGE_SIZE = 100;
type AnnotationFilter = "" | "annotated" | "unannotated";
const annotationFilterOptions: Array<{ value: AnnotationFilter; label: string }> = [
  { value: "", label: "全部" },
  { value: "unannotated", label: "未标注" },
  { value: "annotated", label: "已处理" },
];

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

function buildAnnotationImageFilter(annotationFilter: AnnotationFilter): ImageFilter | undefined {
  return annotationFilter ? { annotation: annotationFilter } : undefined;
}

function imageMatchesAnnotationFilter(image: DatasetImage, annotationFilter: AnnotationFilter) {
  if (!annotationFilter) return true;
  const processed = isProcessed(image.annotationStatus);
  return annotationFilter === "annotated" ? processed : !processed;
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
  const [loadedImages, setLoadedImages] = useState<DatasetImage[]>([]);
  const [imagesTotal, setImagesTotal] = useState(0);
  const [imagesCursor, setImagesCursor] = useState(0);
  const [hasMoreImages, setHasMoreImages] = useState(false);
  const [isLoadingFirstPage, setIsLoadingFirstPage] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [activeImageId, setActiveImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<Detection[]>([]);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [deletingImageId, setDeletingImageId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [currentCategory, setCurrentCategory] = useState("object");
  const [annotationFilter, setAnnotationFilter] = useState<AnnotationFilter>("");
  const [previewImageNaturalSize, setPreviewImageNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [imageViewport, setImageViewport] = useState<ImageViewport | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const queueScrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadedImagesRef = useRef<DatasetImage[]>([]);
  loadedImagesRef.current = loadedImages;
  const cursorRef = useRef(0);
  cursorRef.current = imagesCursor;
  const hasMoreRef = useRef(false);
  hasMoreRef.current = hasMoreImages;
  const isLoadingMoreRef = useRef(false);
  isLoadingMoreRef.current = isLoadingMore;
  const annotationFilterRef = useRef<AnnotationFilter>("");
  annotationFilterRef.current = annotationFilter;
  const loadersRef = useRef<{
    reloadFirstPage: (preferredImageId?: string | null) => Promise<DatasetImage[] | null>;
    loadMore: () => Promise<DatasetImage[] | null>;
  }>({ reloadFirstPage: async () => null, loadMore: async () => null });

  const images = loadedImages;
  const categories = dataset?.categories ?? [];
  const annotationImageFilter = useMemo(() => buildAnnotationImageFilter(annotationFilter), [annotationFilter]);
  const activeIndex = activeImageId ? images.findIndex((image) => image.id === activeImageId) : images.length > 0 ? 0 : -1;
  const activeImage = activeIndex >= 0 ? images[activeIndex] : null;
  const processedCount = useMemo(
    () => images.filter((image) => isProcessed(image.annotationStatus)).length,
    [images],
  );
  const annotationCounts = dataset?.imageAnnotationCounts;
  const totalImageCount = dataset?.imageCount ?? imagesTotal;
  const annotatedTotal = annotationCounts?.annotated ?? processedCount;
  const unannotatedTotal = annotationCounts?.unannotated ?? Math.max(totalImageCount - annotatedTotal, 0);
  const queueLabel =
    annotationFilter === "unannotated"
      ? `${imagesTotal} 张未标注`
      : annotationFilter === "annotated"
        ? `${imagesTotal} 张已处理`
        : `${imagesTotal} 张样本`;
  const activeCategory = currentCategory || categories[0] || "object";
  const hasAnnotationChanges = activeImage !== null && !detectionsEqual(activeImage.detections, draftDetections);
  const canSave = activeImage !== null && !deletingImageId && (hasAnnotationChanges || !isProcessed(activeImage.annotationStatus));
  const isDeletingActiveImage = Boolean(activeImage && deletingImageId === activeImage.id);

  function applyDatasetPage(nextDataset: Dataset, preferredImageId?: string | null) {
    const pageImages = nextDataset.images ?? [];
    const nextTotal = nextDataset.imagesTotal ?? pageImages.length;
    setDataset(nextDataset);
    setLoadedImages(pageImages);
    setImagesTotal(nextTotal);
    setImagesCursor(pageImages.length);
    setHasMoreImages(pageImages.length < nextTotal);
    setActiveImageId((current) => {
      if (preferredImageId && pageImages.some((image) => image.id === preferredImageId)) return preferredImageId;
      if (current && pageImages.some((image) => image.id === current)) return current;
      return pageImages[0]?.id ?? null;
    });
  }

  useEffect(() => {
    if (!token || !datasetId) return;

    let disposed = false;
    setIsLoadingFirstPage(true);
    void getDataset(datasetId, token, { offset: 0, limit: PAGE_SIZE, filter: annotationImageFilter })
      .then((response) => {
        if (disposed) return;
        applyDatasetPage(response.dataset);
        setActionError(null);
      })
      .catch((error) => {
        if (!disposed) {
          setActionError((error as Error).message);
        }
      })
      .finally(() => {
        if (!disposed) setIsLoadingFirstPage(false);
      });

    return () => {
      disposed = true;
    };
  }, [annotationImageFilter, datasetId, token]);

  useEffect(() => {
    loadersRef.current.reloadFirstPage = async (preferredImageId?: string | null) => {
      if (!token || !datasetId) return null;
      setIsLoadingFirstPage(true);
      try {
        const response = await getDataset(datasetId, token, { offset: 0, limit: PAGE_SIZE, filter: annotationImageFilter });
        const pageImages = response.dataset.images ?? [];
        applyDatasetPage(response.dataset, preferredImageId);
        setActionError(null);
        return pageImages;
      } catch (error) {
        setActionError((error as Error).message);
        return null;
      } finally {
        setIsLoadingFirstPage(false);
      }
    };

    loadersRef.current.loadMore = async () => {
      if (!token || !datasetId) return null;
      if (isLoadingMoreRef.current || !hasMoreRef.current) return null;
      const offset = cursorRef.current;
      setIsLoadingMore(true);
      try {
        const response = await getDataset(datasetId, token, { offset, limit: PAGE_SIZE, filter: buildAnnotationImageFilter(annotationFilterRef.current) });
        const pageImages = response.dataset.images ?? [];
        setDataset(response.dataset);
        setImagesTotal(response.dataset.imagesTotal ?? imagesTotal);
        setImagesCursor(offset + pageImages.length);
        setHasMoreImages(offset + pageImages.length < (response.dataset.imagesTotal ?? imagesTotal));
        if (pageImages.length > 0) {
          setLoadedImages((current) => {
            const seen = new Set(current.map((image) => image.id));
            const merged = [...current];
            for (const image of pageImages) {
              if (!seen.has(image.id)) {
                merged.push(image);
                seen.add(image.id);
              }
            }
            return merged;
          });
        }
        return pageImages;
      } catch (error) {
        setActionError((error as Error).message);
        return null;
      } finally {
        setIsLoadingMore(false);
      }
    };
  }, [annotationImageFilter, datasetId, imagesTotal, token]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = queueScrollRef.current;
    if (!sentinel || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void loadersRef.current.loadMore();
        }
      },
      { root, rootMargin: "200px", threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [dataset, hasMoreImages]);

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
    const handleKeydown = (event: KeyboardEvent) => {
      const isSaveShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (isSaveShortcut) {
        event.preventDefault();
        if (activeImage) void saveAnnotations();
        return;
      }
      if (event.key === "Enter" && !isEditableTarget(event.target)) {
        event.preventDefault();
        if (activeImage) void saveAnnotations();
        return;
      }

      if (isEditableTarget(event.target)) return;

      const key = event.key.toLowerCase();
      if (key === "a" || key === "b") {
        event.preventDefault();
        if (!activeImage) return;
        if (event.repeat) return;
        setIsAddingDetection((current) => !current);
        return;
      }
      if (key === "n") {
        event.preventDefault();
        if (!event.repeat) enterAddingDetectionMode();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setIsAddingDetection(false);
        setSelectedDetectionIndex(null);
        return;
      }
      if (key === "u") {
        event.preventDefault();
        if (!event.repeat) changeAnnotationFilter(annotationFilter === "unannotated" ? "" : "unannotated");
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
        if (activeImage) moveActiveImage(-1);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        if (activeImage) moveActiveImage(1);
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
  }, [activeImage, annotationFilter, canSave, categories, draftDetections, isSaving, selectedDetectionIndex]);

  function confirmDiscardChanges() {
    if (!hasAnnotationChanges) return true;
    return window.confirm(unsavedAnnotationMessage);
  }

  function selectImage(imageId: string) {
    if (!confirmDiscardChanges()) return;
    setActiveImageId(imageId);
    setActionError(null);
  }

  function changeAnnotationFilter(nextFilter: AnnotationFilter) {
    if (nextFilter === annotationFilter) return;
    if (!confirmDiscardChanges()) return;
    setAnnotationFilter(nextFilter);
    setActiveImageId(null);
    setActionError(null);
    queueScrollRef.current?.scrollTo({ top: 0 });
  }

  async function moveActiveImage(direction: -1 | 1) {
    if (!activeImage) return;
    const nextIndex = activeIndex + direction;
    if (nextIndex < 0) return;
    if (nextIndex >= images.length) {
      if (hasMoreImages) {
        const page = await loadersRef.current.loadMore();
        const after = page ? loadedImagesRef.current : loadedImagesRef.current;
        const target = after[nextIndex];
        if (target) {
          selectImage(target.id);
        }
        return;
      }
      return;
    }
    selectImage(images[nextIndex].id);
  }

  async function saveAnnotations() {
    if (!token || !datasetId || !activeImage || deletingImageId || isSaving || !canSave) return;
    setIsSaving(true);
    try {
      const response = await updateDatasetImageAnnotations(datasetId, activeImage.id, token, draftDetections);
      const updatedImage = response.image;
      setDataset((current) => (current ? { ...current, ...response.dataset } : response.dataset));
      if (imageMatchesAnnotationFilter(updatedImage, annotationFilterRef.current)) {
        setLoadedImages((current) =>
          current.map((image) => (image.id === updatedImage.id ? { ...image, ...updatedImage } : image)),
        );
        setActiveImageId(updatedImage.id);
      } else {
        await loadersRef.current.reloadFirstPage();
      }
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
      setDataset((current) => (current ? { ...current, ...response.dataset } : response.dataset));
      setImagesTotal((current) => Math.max(0, current - deletedIdSet.size));
      setImagesCursor((current) => Math.max(0, current - deletedIdSet.size));
      const deletedIndex = loadedImagesRef.current.findIndex((candidate) => candidate.id === image.id);
      setLoadedImages((current) => current.filter((candidate) => !deletedIdSet.has(candidate.id)));
      setActiveImageId((current) => {
        if (current && !deletedIdSet.has(current)) return current;
        const after = loadedImagesRef.current.filter((candidate) => !deletedIdSet.has(candidate.id));
        const fallbackIndex = deletedIndex >= 0 ? Math.min(deletedIndex, after.length - 1) : 0;
        return after[fallbackIndex]?.id ?? null;
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
    if (!viewportRef.current) return;
    if (!isAddingDetection) {
      setSelectedDetectionIndex(null);
      return;
    }

    event.preventDefault();
    const rect = viewportRef.current.getBoundingClientRect();
    const start = pointerToStage(rect, event.clientX, event.clientY);
    const nextIndex = draftDetections.length;
    const minBoxSize = minimumBoxSizeForImage(
      previewImageNaturalSize?.width ?? rect.width,
      previewImageNaturalSize?.height ?? rect.height,
    );

    setDraftDetections((current) => [
      ...current,
      { category: activeCategory, confidence: 1, bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE] },
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

  function enterAddingDetectionMode() {
    if (!activeImage) return;
    setIsAddingDetection(true);
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

  if (totalImageCount === 0 && !isLoadingFirstPage) {
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
            <Badge>{annotatedTotal} / {totalImageCount}</Badge>
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
            <Button variant="secondary" className="h-9 px-3" onClick={() => void moveActiveImage(-1)} disabled={activeIndex <= 0 || Boolean(deletingImageId)}>
              <ChevronLeft className="mr-1.5 h-4 w-4" />
              上一张
            </Button>
            <Button
              variant="secondary"
              className="h-9 px-3"
              onClick={() => void moveActiveImage(1)}
              disabled={(activeIndex >= images.length - 1 && !hasMoreImages) || Boolean(deletingImageId) || isLoadingMore}
            >
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
                <div className="text-sm text-neutral-900 dark:text-white">{queueLabel}</div>
              </div>
              <CheckCircle2 className="h-5 w-5 text-neutral-400" />
            </div>
            <div className="mt-3 flex min-w-0 items-center gap-2">
              <ListFilter className="h-4 w-4 shrink-0 text-neutral-400" />
              <div className={cn(segmentedGroupClasses, "min-w-0 flex-1 justify-between")}>
                {annotationFilterOptions.map((option) => {
                  const active = annotationFilter === option.value;
                  const count =
                    option.value === "unannotated"
                      ? unannotatedTotal
                      : option.value === "annotated"
                        ? annotatedTotal
                        : totalImageCount;
                  return (
                    <button
                      key={option.value || "all"}
                      type="button"
                      className={segmentedButtonClasses(active, "min-w-0 flex-1 basis-0 px-2 py-1.5 text-xs")}
                      onClick={() => changeAnnotationFilter(option.value)}
                      title={option.value === "unannotated" ? "快捷键 U" : undefined}
                    >
                      <span className="min-w-0 truncate whitespace-nowrap">{option.label}</span>
                      <span className={cn("shrink-0 text-[11px] tabular-nums", active ? "text-current" : "text-neutral-400")}>{count}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
          <div ref={queueScrollRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
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
            {images.length === 0 && !isLoadingFirstPage ? (
              <div className="rounded-2xl border border-dashed border-neutral-200 p-4 text-sm leading-6 text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                当前筛选没有图片。
              </div>
            ) : hasMoreImages ? (
              <div ref={sentinelRef} className="flex items-center justify-center gap-2 py-3 text-xs text-neutral-500">
                {isLoadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {isLoadingMore ? "加载更多..." : "向下滚动加载更多"}
              </div>
            ) : images.length > 0 ? (
              <div className="py-3 text-center text-xs text-neutral-400">已加载全部 {imagesTotal} 张</div>
            ) : null}
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
                title="快捷键 A / B"
                disabled={!activeImage}
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
            ) : isLoadingFirstPage ? (
              <div className="flex min-h-0 flex-1 items-center justify-center gap-2 px-5 text-center text-sm text-neutral-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                加载图片...
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center px-5 text-center text-sm text-neutral-400">
                当前筛选没有图片。
              </div>
            )}
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
                <div className="mt-1 text-lg text-neutral-900 dark:text-white">
                  {activeImage ? `#${activeImage.ordinal}` : "—"}
                </div>
              </div>
              <Badge>{activeImage ? annotationStatusLabel(activeImage.annotationStatus) : "无图片"}</Badge>
            </div>
            <p className="mt-3 line-clamp-4 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
              {activeImage?.promptText ?? "当前筛选没有图片。"}
            </p>
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
                onClick={enterAddingDetectionMode}
                disabled={!activeImage}
                title="进入画框状态，快捷键 N"
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
