import { useContext, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleMinus,
  CirclePlus,
  Eye,
  EyeOff,
  ImageOff,
  Keyboard,
  Loader2,
  Maximize2,
  Menu,
  MoreHorizontal,
  MousePointer2,
  PanelRight,
  PencilRuler,
  Redo2,
  Save,
  ScanSearch,
  Trash2,
  Undo2,
  ZoomIn,
  ZoomOut,
  X,
} from "lucide-react";
import { Link, UNSAFE_NavigationContext, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Grid,
  Modal,
  Select,
  Tag,
  Tooltip,
  Typography,
} from "antd";

import {
  createSegmentAssistSession,
  deleteDatasetImage,
  deleteSegmentAssistSession,
  getDataset,
  predictSegmentAssistSession,
  updateDatasetImageAnnotations,
} from "../api/datasets";
import { AuthImage } from "../components/AuthImage";
import { AnnotationInspectorPanel } from "../components/annotation/AnnotationInspectorPanel";
import { AnnotationQueuePanel } from "../components/annotation/AnnotationQueuePanel";
import type { AnnotationFilter } from "../components/annotation/types";
import { EmptyState } from "../components/common/EmptyState";
import { LoadingState } from "../components/common/LoadingState";
import { useConfirm } from "../hooks/useConfirm";
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
import type {
  Dataset,
  DatasetImage,
  ImageFilter,
  SegmentAssistPoint,
  SegmentAssistPrediction,
  SegmentAssistSession,
} from "../lib/types";
import { cn } from "../lib/utils";
import { useAuthStore } from "../store/auth";

const categoryPalette = ["#64748b", "#4f6b73", "#6b7c74", "#7c8794", "#5b7080", "#7d8884", "#52636d", "#88949b", "#94a3b8"];
const unsavedAnnotationMessage = "当前图片有未保存的标注改动，确认放弃并继续？";
const PAGE_SIZE = 100;
const MAX_HISTORY_LENGTH = 50;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

type AnnotationTool = "smart-select" | "box";
type ActiveSegmentSession = SegmentAssistSession & { imageId: string };

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

function isInteractiveTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(target.closest("input, textarea, select, button, a, [role='button'], [contenteditable='true']"));
}

function isDetectionArray(value: unknown): value is Detection[] {
  if (!Array.isArray(value)) return false;
  return value.every((item) => {
    if (!item || typeof item !== "object") return false;
    const detection = item as Partial<Detection>;
    return (
      typeof detection.category === "string" &&
      typeof detection.confidence === "number" &&
      Array.isArray(detection.bbox) &&
      detection.bbox.length === 4 &&
      detection.bbox.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate))
    );
  });
}

export function DatasetAnnotatePage() {
  const token = useAuthStore((state) => state.token);
  const { datasetId } = useParams();
  const navigate = useNavigate();
  const navigation = useContext(UNSAFE_NavigationContext);
  const screens = Grid.useBreakpoint();
  const confirm = useConfirm();

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loadedImages, setLoadedImages] = useState<DatasetImage[]>([]);
  const [imagesTotal, setImagesTotal] = useState(0);
  const [hasMoreImages, setHasMoreImages] = useState(false);
  const [isLoadingFirstPage, setIsLoadingFirstPage] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [activeImageId, setActiveImageId] = useState<string | null>(null);
  const [draftDetections, setDraftDetections] = useState<Detection[]>([]);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [isAddingDetection, setIsAddingDetection] = useState(false);
  const [annotationTool, setAnnotationTool] = useState<AnnotationTool>("box");
  const [segmentSession, setSegmentSession] = useState<ActiveSegmentSession | null>(null);
  const [segmentPoints, setSegmentPoints] = useState<SegmentAssistPoint[]>([]);
  const [segmentPointLabel, setSegmentPointLabel] = useState<SegmentAssistPoint["label"]>("positive");
  const [segmentPrediction, setSegmentPrediction] = useState<SegmentAssistPrediction | null>(null);
  const [isPreparingSegment, setIsPreparingSegment] = useState(false);
  const [isPredictingSegment, setIsPredictingSegment] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [deletingImageId, setDeletingImageId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [currentCategory, setCurrentCategory] = useState("object");
  const [annotationFilter, setAnnotationFilter] = useState<AnnotationFilter>("");
  const [previewImageNaturalSize, setPreviewImageNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [imageViewport, setImageViewport] = useState<ImageViewport | null>(null);
  const [queueOpen, setQueueOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [boxesVisible, setBoxesVisible] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [saveAnnouncement, setSaveAnnouncement] = useState("");
  const [draftRecovered, setDraftRecovered] = useState(false);
  const [, setHistoryRevision] = useState(0);

  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const queueScrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadedImagesRef = useRef<DatasetImage[]>([]);
  loadedImagesRef.current = loadedImages;
  const imagesTotalRef = useRef(0);
  imagesTotalRef.current = imagesTotal;
  const nextImagesCursorRef = useRef<string | null>(null);
  const queueRevisionRef = useRef(0);
  const loadMorePromiseRef = useRef<Promise<DatasetImage[] | null> | null>(null);
  const hasMoreRef = useRef(false);
  hasMoreRef.current = hasMoreImages;
  const annotationFilterRef = useRef<AnnotationFilter>("");
  annotationFilterRef.current = annotationFilter;
  const undoStackRef = useRef<Detection[][]>([]);
  const redoStackRef = useRef<Detection[][]>([]);
  const segmentSessionRef = useRef<ActiveSegmentSession | null>(null);
  const segmentRequestRevisionRef = useRef(0);
  const segmentBusyRef = useRef(false);
  const activeImageIdRef = useRef<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const draftOwnerImageIdRef = useRef<string | null>(null);
  const loadersRef = useRef<{
    reloadFirstPage: (preferredImageId?: string | null) => Promise<DatasetImage[] | null>;
    loadMore: () => Promise<DatasetImage[] | null>;
  }>({ reloadFirstPage: async () => null, loadMore: async () => null });

  const images = loadedImages;
  const categories = dataset?.categories ?? [];
  const annotationImageFilter = useMemo(() => buildAnnotationImageFilter(annotationFilter), [annotationFilter]);
  const activeIndex = activeImageId ? images.findIndex((image) => image.id === activeImageId) : images.length > 0 ? 0 : -1;
  const activeImage = activeIndex >= 0 ? images[activeIndex] : null;
  const processedCount = useMemo(() => images.filter((image) => isProcessed(image.annotationStatus)).length, [images]);
  const annotationCounts = dataset?.imageAnnotationCounts;
  const totalImageCount = dataset?.imageCount ?? imagesTotal;
  const annotatedTotal = annotationCounts?.annotated ?? processedCount;
  const unannotatedTotal = annotationCounts?.unannotated ?? Math.max(totalImageCount - annotatedTotal, 0);
  const activeCategory = currentCategory || categories[0] || "object";
  const hasAnnotationChanges = activeImage !== null && !detectionsEqual(activeImage.detections, draftDetections);
  const canSave = activeImage !== null && !deletingImageId && (hasAnnotationChanges || !isProcessed(activeImage.annotationStatus));
  const isDeletingActiveImage = Boolean(activeImage && deletingImageId === activeImage.id);
  const isDesktop = Boolean(screens.xl);
  const isTablet = Boolean(screens.md);
  const canUndo = undoStackRef.current.length > 0;
  const canRedo = redoStackRef.current.length > 0;
  const segmentAssistAvailable = Boolean(dataset?.segmentAssistAvailable);
  const activeAnnotationTool: AnnotationTool = segmentAssistAvailable ? annotationTool : "box";
  const draftStorageKey = activeImage && datasetId ? `dataset-forge:annotation-draft:${datasetId}:${activeImage.id}` : null;

  segmentSessionRef.current = segmentSession;
  activeImageIdRef.current = activeImage?.id ?? null;
  tokenRef.current = token;

  useEffect(() => {
    setQueueOpen(false);
    setInspectorOpen(false);
  }, [isDesktop, isTablet]);

  useEffect(() => {
    const existingSession = segmentSessionRef.current;
    segmentRequestRevisionRef.current += 1;
    segmentBusyRef.current = false;
    segmentSessionRef.current = null;
    setSegmentSession(null);
    setSegmentPoints([]);
    setSegmentPrediction(null);
    setSegmentPointLabel("positive");
    setIsPreparingSegment(false);
    setIsPredictingSegment(false);
    const cleanupToken = tokenRef.current;
    if (existingSession && cleanupToken && datasetId) {
      void deleteSegmentAssistSession(
        datasetId,
        existingSession.imageId,
        existingSession.sessionId,
        cleanupToken,
      ).catch(() => undefined);
    }
  }, [activeImage?.id, datasetId]);

  useEffect(() => () => {
    segmentRequestRevisionRef.current += 1;
    segmentBusyRef.current = false;
    activeImageIdRef.current = null;
    const existingSession = segmentSessionRef.current;
    const cleanupToken = tokenRef.current;
    if (existingSession && cleanupToken && datasetId) {
      void deleteSegmentAssistSession(
        datasetId,
        existingSession.imageId,
        existingSession.sessionId,
        cleanupToken,
      ).catch(() => undefined);
    }
  }, [datasetId]);

  function applyDatasetPage(nextDataset: Dataset, preferredImageId?: string | null) {
    const pageImages = nextDataset.images ?? [];
    const nextTotal = nextDataset.imagesTotal ?? pageImages.length;
    const nextCursor = nextDataset.imagesNextCursor ?? null;
    const nextHasMore = Boolean(nextCursor) || pageImages.length < nextTotal;
    loadedImagesRef.current = pageImages;
    imagesTotalRef.current = nextTotal;
    nextImagesCursorRef.current = nextCursor;
    hasMoreRef.current = nextHasMore;
    setDataset(nextDataset);
    setLoadedImages(pageImages);
    setImagesTotal(nextTotal);
    setHasMoreImages(nextHasMore);
    setActiveImageId((current) => {
      if (preferredImageId && pageImages.some((image) => image.id === preferredImageId)) return preferredImageId;
      if (current && pageImages.some((image) => image.id === current)) return current;
      return pageImages[0]?.id ?? null;
    });
  }

  useEffect(() => {
    if (!token || !datasetId) return;

    let disposed = false;
    const requestRevision = queueRevisionRef.current + 1;
    queueRevisionRef.current = requestRevision;
    loadMorePromiseRef.current = null;
    setIsLoadingMore(false);
    setIsLoadingFirstPage(true);
    void getDataset(datasetId, token, { offset: 0, limit: PAGE_SIZE, filter: annotationImageFilter })
      .then((response) => {
        if (disposed || queueRevisionRef.current !== requestRevision) return;
        applyDatasetPage(response.dataset);
        setActionError(null);
      })
      .catch((error) => {
        if (!disposed && queueRevisionRef.current === requestRevision) {
          setActionError((error as Error).message);
        }
      })
      .finally(() => {
        if (!disposed && queueRevisionRef.current === requestRevision) {
          setIsLoadingFirstPage(false);
        }
      });

    return () => {
      disposed = true;
      if (queueRevisionRef.current === requestRevision) {
        queueRevisionRef.current += 1;
        loadMorePromiseRef.current = null;
      }
    };
  }, [annotationImageFilter, datasetId, token]);

  useEffect(() => {
    loadersRef.current.reloadFirstPage = async (preferredImageId?: string | null) => {
      if (!token || !datasetId) return null;
      const requestRevision = queueRevisionRef.current + 1;
      queueRevisionRef.current = requestRevision;
      loadMorePromiseRef.current = null;
      setIsLoadingMore(false);
      setIsLoadingFirstPage(true);
      try {
        const response = await getDataset(datasetId, token, { offset: 0, limit: PAGE_SIZE, filter: annotationImageFilter });
        if (queueRevisionRef.current !== requestRevision) return null;
        const pageImages = response.dataset.images ?? [];
        applyDatasetPage(response.dataset, preferredImageId);
        setActionError(null);
        return pageImages;
      } catch (error) {
        if (queueRevisionRef.current === requestRevision) {
          setActionError((error as Error).message);
        }
        return null;
      } finally {
        if (queueRevisionRef.current === requestRevision) {
          setIsLoadingFirstPage(false);
        }
      }
    };

    loadersRef.current.loadMore = async () => {
      if (!token || !datasetId) return null;
      if (loadMorePromiseRef.current) return loadMorePromiseRef.current;
      if (!hasMoreRef.current) return null;
      const cursor = nextImagesCursorRef.current;
      const offset = loadedImagesRef.current.length;
      const requestRevision = queueRevisionRef.current;
      setIsLoadingMore(true);
      const request = (async () => {
        try {
          const response = await getDataset(datasetId, token, {
            cursor: cursor ?? undefined,
            offset: cursor ? undefined : offset,
            limit: PAGE_SIZE,
            filter: buildAnnotationImageFilter(annotationFilterRef.current),
          });
          if (queueRevisionRef.current !== requestRevision) return null;
          const pageImages = response.dataset.images ?? [];
          const current = loadedImagesRef.current;
          const seen = new Set(current.map((image) => image.id));
          const merged = [...current];
          if (pageImages.length > 0) {
            for (const image of pageImages) {
              if (!seen.has(image.id)) {
                merged.push(image);
                seen.add(image.id);
              }
            }
          }
          const total = response.dataset.imagesTotal ?? imagesTotalRef.current;
          const nextCursor = response.dataset.imagesNextCursor ?? null;
          const nextHasMore = Boolean(nextCursor) || merged.length < total;
          loadedImagesRef.current = merged;
          imagesTotalRef.current = total;
          nextImagesCursorRef.current = nextCursor;
          hasMoreRef.current = nextHasMore;
          setDataset(response.dataset);
          setLoadedImages(merged);
          setImagesTotal(total);
          setHasMoreImages(nextHasMore);
          return pageImages;
        } catch (error) {
          if (queueRevisionRef.current === requestRevision) {
            setActionError((error as Error).message);
          }
          return null;
        }
      })();
      loadMorePromiseRef.current = request;
      try {
        return await request;
      } finally {
        if (loadMorePromiseRef.current === request) {
          setIsLoadingMore(false);
          loadMorePromiseRef.current = null;
        }
      }
    };
  }, [annotationImageFilter, datasetId, token]);

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
  }, [dataset, hasMoreImages, isDesktop, queueOpen]);

  useEffect(() => {
    if (categories.length === 0) {
      setCurrentCategory("object");
      return;
    }
    setCurrentCategory((current) => (categories.includes(current) ? current : categories[0]));
  }, [categories]);

  useEffect(() => {
    if (!activeImage) {
      draftOwnerImageIdRef.current = null;
      setDraftDetections([]);
      setDraftRecovered(false);
      setIsAddingDetection(false);
      setAnnotationTool("box");
      return;
    }

    let initialDetections = activeImage.detections;
    let recovered = false;
    if (draftStorageKey) {
      try {
        const stored = window.sessionStorage.getItem(draftStorageKey);
        if (stored) {
          const parsed = JSON.parse(stored) as unknown;
          if (isDetectionArray(parsed)) {
            initialDetections = parsed;
            recovered = !detectionsEqual(parsed, activeImage.detections);
          }
        }
      } catch {
        window.sessionStorage.removeItem(draftStorageKey);
      }
    }

    draftOwnerImageIdRef.current = null;
    setDraftDetections(initialDetections);
    setDraftRecovered(recovered);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(false);
    setAnnotationTool("box");
    setBoxesVisible(true);
    setZoom(1);
    undoStackRef.current = [];
    redoStackRef.current = [];
    setHistoryRevision((current) => current + 1);
  }, [activeImage?.id, draftStorageKey]);

  useEffect(() => {
    if (!activeImage || !draftStorageKey) return;
    if (draftOwnerImageIdRef.current !== activeImage.id) {
      draftOwnerImageIdRef.current = activeImage.id;
      return;
    }
    if (hasAnnotationChanges) {
      window.sessionStorage.setItem(draftStorageKey, JSON.stringify(draftDetections));
    } else {
      window.sessionStorage.removeItem(draftStorageKey);
      setDraftRecovered(false);
    }
  }, [activeImage, draftDetections, draftStorageKey, hasAnnotationChanges]);

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
          Math.max(rect.width - 32, 0),
          Math.max(rect.height - 32, 0),
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
    const confirmNavigation = () =>
      confirm({
        title: "未保存的改动",
        content: unsavedAnnotationMessage,
        okText: "放弃",
        cancelText: "取消",
        okDanger: true,
      });

    navigator.push = (...args) => {
      void confirmNavigation().then((ok) => {
        if (ok) originalPush.apply(navigator, args);
      });
    };
    navigator.replace = (...args) => {
      void confirmNavigation().then((ok) => {
        if (ok) originalReplace.apply(navigator, args);
      });
    };
    navigator.go = (...args) => {
      void confirmNavigation().then((ok) => {
        if (ok) originalGo.apply(navigator, args);
      });
    };

    return () => {
      navigator.push = originalPush;
      navigator.replace = originalReplace;
      navigator.go = originalGo;
    };
  }, [confirm, hasAnnotationChanges, navigation.navigator]);

  useEffect(() => {
    const handleKeydown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      const hasCommandModifier = event.metaKey || event.ctrlKey;
      if (hasCommandModifier && key === "z") {
        if (isInteractiveTarget(event.target)) return;
        event.preventDefault();
        if (event.shiftKey) redoDetectionChange();
        else undoDetectionChange();
        return;
      }
      const isSaveShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (isSaveShortcut) {
        event.preventDefault();
        if (activeImage) void saveAnnotations();
        return;
      }
      if (event.key === "Enter" && !isInteractiveTarget(event.target)) {
        event.preventDefault();
        if (segmentPrediction) confirmSegmentPrediction();
        else if (activeImage) void confirmAndAdvance();
        return;
      }

      if (isInteractiveTarget(event.target)) return;

      if (key === "?") {
        event.preventDefault();
        setHelpOpen((current) => !current);
        return;
      }
      if (key === "b") {
        event.preventDefault();
        if (!activeImage) return;
        if (event.repeat) return;
        if (activeAnnotationTool !== "box") changeAnnotationTool("box");
        else setIsAddingDetection((current) => !current);
        return;
      }
      if (key === "s" && segmentAssistAvailable) {
        event.preventDefault();
        if (!activeImage || event.repeat) return;
        changeAnnotationTool("smart-select");
        return;
      }
      if (key === "=" || key === "+") {
        event.preventDefault();
        setZoom((current) => Math.min(MAX_ZOOM, current + ZOOM_STEP));
        return;
      }
      if (key === "-") {
        event.preventDefault();
        setZoom((current) => Math.max(MIN_ZOOM, current - ZOOM_STEP));
        return;
      }
      if (key === "0") {
        event.preventDefault();
        setZoom(1);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        if (activeAnnotationTool === "smart-select") {
          finishSmartSelect();
          return;
        }
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
  }, [
    activeAnnotationTool,
    activeImage,
    annotationFilter,
    canSave,
    categories,
    draftDetections,
    isSaving,
    segmentAssistAvailable,
    segmentPrediction,
    selectedDetectionIndex,
  ]);

  async function confirmDiscardChanges(): Promise<boolean> {
    if (!hasAnnotationChanges) return true;
    return confirm({
      title: "未保存的改动",
      content: unsavedAnnotationMessage,
      okText: "放弃",
      cancelText: "取消",
      okDanger: true,
    });
  }

  async function selectImage(imageId: string) {
    if (!(await confirmDiscardChanges())) return false;
    setActiveImageId(imageId);
    setActionError(null);
    return true;
  }

  async function changeAnnotationFilter(nextFilter: AnnotationFilter) {
    if (nextFilter === annotationFilter) return;
    if (!(await confirmDiscardChanges())) return;
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
        await loadersRef.current.loadMore();
        const target = loadedImagesRef.current[nextIndex];
        if (target) {
          await selectImage(target.id);
        }
        return;
      }
      return;
    }
    await selectImage(images[nextIndex].id);
  }

  async function advanceAfterImageLeavesQueue(removedImageId: string) {
    const previousImages = loadedImagesRef.current;
    const removedIndex = previousImages.findIndex((image) => image.id === removedImageId);
    if (removedIndex < 0) {
      await loadersRef.current.reloadFirstPage();
      return;
    }

    const remainingImages = previousImages.filter((image) => image.id !== removedImageId);
    const nextTotal = Math.max(0, imagesTotalRef.current - 1);
    const followingImage = remainingImages[removedIndex] ?? null;
    const previousImage = remainingImages[removedIndex - 1] ?? null;
    const nextHasMore = Boolean(nextImagesCursorRef.current) || remainingImages.length < nextTotal;
    loadedImagesRef.current = remainingImages;
    imagesTotalRef.current = nextTotal;
    hasMoreRef.current = nextHasMore;
    setLoadedImages(remainingImages);
    setImagesTotal(nextTotal);
    setHasMoreImages(nextHasMore);

    if (followingImage) {
      setActiveImageId(followingImage.id);
      return;
    }
    if (nextHasMore) {
      await loadersRef.current.loadMore();
    }
    setActiveImageId(loadedImagesRef.current[removedIndex]?.id ?? previousImage?.id ?? null);
  }

  async function advanceAfterSavedImage(savedImageId: string) {
    let savedIndex = loadedImagesRef.current.findIndex((image) => image.id === savedImageId);
    let target = savedIndex >= 0 ? loadedImagesRef.current[savedIndex + 1] ?? null : null;
    if (!target && hasMoreRef.current) {
      await loadersRef.current.loadMore();
      savedIndex = loadedImagesRef.current.findIndex((image) => image.id === savedImageId);
      target = savedIndex >= 0 ? loadedImagesRef.current[savedIndex + 1] ?? null : null;
    }
    if (target) {
      setActiveImageId(target.id);
      return true;
    }
    return false;
  }

  async function saveAnnotations(options: { advance?: boolean; detections?: Detection[] } = {}) {
    const detectionsToSave = options.detections ?? draftDetections;
    const hasChangesToSave = activeImage !== null && !detectionsEqual(activeImage.detections, detectionsToSave);
    const canSaveCurrent = activeImage !== null && (hasChangesToSave || !isProcessed(activeImage.annotationStatus));
    if (!token || !datasetId || !activeImage || deletingImageId || isSaving || !canSaveCurrent) return false;
    setIsSaving(true);
    setSaveAnnouncement("正在保存当前图片的标注…");
    try {
      const response = await updateDatasetImageAnnotations(datasetId, activeImage.id, token, detectionsToSave);
      const updatedImage = response.image;
      if (draftStorageKey) window.sessionStorage.removeItem(draftStorageKey);
      setDraftRecovered(false);
      setDataset((current) => (current ? { ...current, ...response.dataset } : response.dataset));
      if (imageMatchesAnnotationFilter(updatedImage, annotationFilterRef.current)) {
        const nextImages = loadedImagesRef.current.map((image) => (
          image.id === updatedImage.id ? { ...image, ...updatedImage } : image
        ));
        loadedImagesRef.current = nextImages;
        setLoadedImages(nextImages);
        setDraftDetections(updatedImage.detections);
        undoStackRef.current = [];
        redoStackRef.current = [];
        setHistoryRevision((current) => current + 1);
        if (options.advance) {
          const advanced = await advanceAfterSavedImage(updatedImage.id);
          setSaveAnnouncement(advanced ? "标注已保存，已进入下一张。" : "标注已保存，已到达队列末尾。");
        } else {
          setActiveImageId(updatedImage.id);
          setSaveAnnouncement("当前图片的标注已保存。");
        }
      } else {
        await advanceAfterImageLeavesQueue(updatedImage.id);
        setSaveAnnouncement("标注已保存，已进入下一张待处理图片。");
      }
      setActionError(null);
      return true;
    } catch (error) {
      setActionError((error as Error).message);
      setSaveAnnouncement("保存失败，请检查错误信息后重试。");
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function confirmAndAdvance() {
    if (!activeImage) return;
    if (canSave) {
      await saveAnnotations({ advance: true });
      return;
    }
    await moveActiveImage(1);
  }

  async function markEmptyAndAdvance() {
    if (!activeImage) return;
    const alreadyEmpty = activeImage.annotationStatus === "empty" && draftDetections.length === 0;
    if (alreadyEmpty) {
      await moveActiveImage(1);
      return;
    }
    await saveAnnotations({ advance: true, detections: [] });
  }

  async function removeDatasetImage(image: DatasetImage) {
    if (!token || !datasetId || deletingImageId) return;
    const discardsActiveDraft = image.id === activeImage?.id && hasAnnotationChanges;
    const ok = await confirm({
      title: "删除样本",
      content: `删除样本 #${image.ordinal}？图片文件和标注也会一起移除。${discardsActiveDraft ? " 当前未保存的标注改动也会放弃。" : ""}`,
      okText: "删除",
      cancelText: "取消",
      okDanger: true,
    });
    if (!ok) return;

    setDeletingImageId(image.id);
    try {
      const response = await deleteDatasetImage(datasetId, image.id, token);
      const deletedIdSet = new Set(response.deletedImageIds);
      setDataset((current) => (current ? { ...current, ...response.dataset } : response.dataset));
      const previousImages = loadedImagesRef.current;
      const deletedIndex = previousImages.findIndex((candidate) => candidate.id === image.id);
      const remainingImages = previousImages.filter((candidate) => !deletedIdSet.has(candidate.id));
      const nextTotal = Math.max(0, imagesTotalRef.current - deletedIdSet.size);
      const nextHasMore = Boolean(nextImagesCursorRef.current) || remainingImages.length < nextTotal;
      loadedImagesRef.current = remainingImages;
      imagesTotalRef.current = nextTotal;
      hasMoreRef.current = nextHasMore;
      setLoadedImages(remainingImages);
      setImagesTotal(nextTotal);
      setHasMoreImages(nextHasMore);
      setActiveImageId((current) => {
        if (current && !deletedIdSet.has(current)) return current;
        const fallbackIndex = deletedIndex >= 0 ? Math.min(deletedIndex, remainingImages.length - 1) : 0;
        return remainingImages[fallbackIndex]?.id ?? null;
      });
      setActionError(null);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setDeletingImageId(null);
    }
  }

  function recordHistorySnapshot(snapshot: Detection[]) {
    const lastSnapshot = undoStackRef.current[undoStackRef.current.length - 1];
    if (lastSnapshot && detectionsEqual(lastSnapshot, snapshot)) return;
    undoStackRef.current = [...undoStackRef.current.slice(-(MAX_HISTORY_LENGTH - 1)), snapshot];
    redoStackRef.current = [];
    setHistoryRevision((current) => current + 1);
  }

  function updateDraftDetections(updater: (current: Detection[]) => Detection[]) {
    const next = updater(draftDetections);
    if (detectionsEqual(draftDetections, next)) return;
    recordHistorySnapshot(draftDetections);
    setDraftDetections(next);
  }

  function undoDetectionChange() {
    const previous = undoStackRef.current[undoStackRef.current.length - 1];
    if (!previous) return;
    undoStackRef.current = undoStackRef.current.slice(0, -1);
    redoStackRef.current = [...redoStackRef.current, draftDetections].slice(-MAX_HISTORY_LENGTH);
    setDraftDetections(previous);
    setSelectedDetectionIndex(null);
    setSaveAnnouncement("已撤销上一步标注操作。");
    setHistoryRevision((current) => current + 1);
  }

  function redoDetectionChange() {
    const next = redoStackRef.current[redoStackRef.current.length - 1];
    if (!next) return;
    redoStackRef.current = redoStackRef.current.slice(0, -1);
    undoStackRef.current = [...undoStackRef.current, draftDetections].slice(-MAX_HISTORY_LENGTH);
    setDraftDetections(next);
    setSelectedDetectionIndex(null);
    setSaveAnnouncement("已重做标注操作。");
    setHistoryRevision((current) => current + 1);
  }

  function beginDragDetection(index: number, event: ReactPointerEvent<HTMLDivElement>) {
    if (!viewportRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedDetectionIndex(index);
    const rect = viewportRef.current.getBoundingClientRect();
    const origin = draftDetections[index];
    recordHistorySnapshot(draftDetections);
    const startX = event.clientX;
    const startY = event.clientY;

    const handleMove = (moveEvent: PointerEvent) => {
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
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
  }

  function beginResizeDetection(index: number, corner: ResizeCorner, event: ReactPointerEvent<HTMLButtonElement>) {
    if (!viewportRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedDetectionIndex(index);
    const rect = viewportRef.current.getBoundingClientRect();
    const origin = draftDetections[index];
    recordHistorySnapshot(draftDetections);
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

    const handleMove = (moveEvent: PointerEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(anchorX, anchorY, pointer.x, pointer.y, minBoxSize.width, minBoxSize.height);
      setDraftDetections((current) =>
        current.map((detection, detectionIndex) => (detectionIndex === index ? { ...detection, bbox } : detection)),
      );
    };

    const handleUp = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
  }

  function clearSegmentPrediction() {
    segmentRequestRevisionRef.current += 1;
    segmentBusyRef.current = false;
    setSegmentPoints([]);
    setSegmentPrediction(null);
    setSegmentPointLabel("positive");
    setIsPreparingSegment(false);
    setIsPredictingSegment(false);
  }

  function closeSegmentAssistSession() {
    const existingSession = segmentSessionRef.current;
    segmentSessionRef.current = null;
    setSegmentSession(null);
    clearSegmentPrediction();
    if (existingSession && token && datasetId) {
      void deleteSegmentAssistSession(
        datasetId,
        existingSession.imageId,
        existingSession.sessionId,
        token,
      ).catch(() => undefined);
    }
  }

  function changeAnnotationTool(tool: AnnotationTool) {
    if (tool === activeAnnotationTool) return;
    setAnnotationTool(tool);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(tool === "box");
    if (tool === "box") closeSegmentAssistSession();
  }

  function finishSmartSelect() {
    setAnnotationTool("box");
    setIsAddingDetection(false);
    closeSegmentAssistSession();
  }

  async function addSegmentPoint(point: SegmentAssistPoint) {
    if (!activeImage || !token || !datasetId || segmentBusyRef.current) return;
    segmentBusyRef.current = true;
    const requestImageId = activeImage.id;
    const requestRevision = segmentRequestRevisionRef.current + 1;
    segmentRequestRevisionRef.current = requestRevision;
    let activeSession = segmentSessionRef.current;
    const nextPoints = [...segmentPoints, point];
    setSegmentPoints(nextPoints);

    try {
      if (!activeSession || activeSession.imageId !== requestImageId) {
        setIsPreparingSegment(true);
        const created = await createSegmentAssistSession(datasetId, requestImageId, token);
        const nextSession = { ...created, imageId: requestImageId };
        if (segmentRequestRevisionRef.current !== requestRevision || activeImageIdRef.current !== requestImageId) {
          const cleanupToken = tokenRef.current ?? token;
          void deleteSegmentAssistSession(
            datasetId,
            requestImageId,
            created.sessionId,
            cleanupToken,
          ).catch(() => undefined);
          return;
        }
        activeSession = nextSession;
        segmentSessionRef.current = nextSession;
        setSegmentSession(nextSession);
        setIsPreparingSegment(false);
      }

      setIsPredictingSegment(true);
      const prediction = await predictSegmentAssistSession(
        datasetId,
        requestImageId,
        activeSession.sessionId,
        token,
        nextPoints,
      );
      if (segmentRequestRevisionRef.current !== requestRevision || activeImageIdRef.current !== requestImageId) return;
      setSegmentPrediction(prediction);
      setActionError(null);
      setSaveAnnouncement(`智能点选已生成候选框，mask 评分 ${Math.round(prediction.maskScore * 100)}%。`);
    } catch (error) {
      if (segmentRequestRevisionRef.current !== requestRevision) return;
      const message = (error as Error).message;
      setActionError(`智能点选失败：${message}`);
      setSaveAnnouncement("智能点选失败，可重试或切换为手动画框。");
      if (/session|会话|expired/i.test(message)) {
        segmentSessionRef.current = null;
        setSegmentSession(null);
        setSegmentPoints([]);
        setSegmentPrediction(null);
      }
    } finally {
      if (segmentRequestRevisionRef.current === requestRevision) {
        segmentBusyRef.current = false;
        setIsPreparingSegment(false);
        setIsPredictingSegment(false);
      }
    }
  }

  function confirmSegmentPrediction() {
    if (!segmentPrediction || !activeImage || isPredictingSegment) return;
    const nextDetection: Detection = {
      category: activeCategory,
      confidence: 1,
      bbox: segmentPrediction.bbox,
    };
    recordHistorySnapshot(draftDetections);
    setDraftDetections((current) => [...current, nextDetection]);
    setSelectedDetectionIndex(draftDetections.length);
    finishSmartSelect();
    setSaveAnnouncement("智能候选框已确认并加入当前标注。");
  }

  function handleStagePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!viewportRef.current) return;
    if (activeAnnotationTool === "smart-select") {
      if (isPreparingSegment || isPredictingSegment) return;
      event.preventDefault();
      const rect = viewportRef.current.getBoundingClientRect();
      const point = pointerToStage(rect, event.clientX, event.clientY);
      void addSegmentPoint({ ...point, label: segmentPointLabel });
      return;
    }
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

    recordHistorySnapshot(draftDetections);
    setDraftDetections((current) => [
      ...current,
      { category: activeCategory, confidence: 1, bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE] },
    ]);
    setSelectedDetectionIndex(nextIndex);

    const handleMove = (moveEvent: PointerEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(start.x, start.y, pointer.x, pointer.y, minBoxSize.width, minBoxSize.height);
      setDraftDetections((current) =>
        current.map((detection, detectionIndex) => (detectionIndex === nextIndex ? { ...detection, bbox } : detection)),
      );
    };

    const handleUp = () => {
      setIsAddingDetection(false);
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
  }

  function updateDetectionCategory(index: number, category: string) {
    updateDraftDetections((current) =>
      current.map((detection, detectionIndex) =>
        detectionIndex === index ? { ...detection, category: category.slice(0, 120) || "object" } : detection,
      ),
    );
  }

  function updateDetectionConfidence(index: number, value: number) {
    updateDraftDetections((current) =>
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
    updateDraftDetections((current) => current.filter((_, detectionIndex) => detectionIndex !== index));
    setSelectedDetectionIndex((current) => {
      if (current === null) return null;
      if (current === index) return null;
      return current > index ? current - 1 : current;
    });
  }

  function changeActiveCategory(category: string) {
    setCurrentCategory(category);
    if (selectedDetectionIndex !== null) {
      updateDetectionCategory(selectedDetectionIndex, category);
    }
  }

  const saveStatus = hasAnnotationChanges
    ? "unsaved"
    : activeImage && !isProcessed(activeImage.annotationStatus)
      ? "pending"
      : "synced";

  const shortcuts = [
    { keys: "← / →", action: "上一张 / 下一张" },
    { keys: "B", action: "切换画框模式" },
    ...(segmentAssistAvailable ? [{ keys: "S", action: "启用一次智能点选" }] : []),
    { keys: "Enter", action: segmentPrediction ? "确认智能候选框" : "保存并进入下一张" },
    { keys: "Ctrl / ⌘ + S", action: "保存当前图片" },
    { keys: "Ctrl / ⌘ + Z", action: "撤销" },
    { keys: "Ctrl / ⌘ + Shift + Z", action: "重做" },
    { keys: "Delete / Backspace", action: "删除选中的检测框" },
    { keys: "Esc", action: "取消候选 / 画框 / 选择" },
    { keys: "1-9", action: "选择对应编号的类别" },
    { keys: "U", action: "切换未标注筛选" },
    { keys: "+ / - / 0", action: "放大 / 缩小 / 适应画布" },
    { keys: "?", action: "显示 / 隐藏快捷键帮助" },
  ];

  if (!dataset) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white dark:bg-neutral-950">
        <LoadingState rows={2} className="w-64" />
      </div>
    );
  }

  if (totalImageCount === 0 && !isLoadingFirstPage) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white p-8 dark:bg-neutral-950">
        <div className="text-center">
          <ImageOff className="mx-auto h-12 w-12 text-neutral-400" />
          <EmptyState
            title="暂无可标注图片"
            description="导入或生成样本后再进入标注模式。"
            action={{
              label: (
                <span className="flex items-center gap-2">
                  <ArrowLeft className="h-4 w-4" />
                  返回数据集
                </span>
              ),
              onClick: () => navigate(`/datasets/${dataset.id}`),
            }}
          />
        </div>
      </div>
    );
  }

  const queuePanel = (
    <AnnotationQueuePanel
      activeImageId={activeImage?.id ?? null}
      annotatedTotal={annotatedTotal}
      annotationFilter={annotationFilter}
      hasMoreImages={hasMoreImages}
      images={images}
      imagesTotal={imagesTotal}
      isLoadingFirstPage={isLoadingFirstPage}
      isLoadingMore={isLoadingMore}
      onFilterChange={(filter) => void changeAnnotationFilter(filter)}
      onSelectImage={(imageId) => {
        void selectImage(imageId).then((selected) => {
          if (selected) setQueueOpen(false);
        });
      }}
      queueScrollRef={queueScrollRef}
      sentinelRef={sentinelRef}
      totalImageCount={totalImageCount}
      unannotatedTotal={unannotatedTotal}
    />
  );

  const inspectorPanel = (
    <AnnotationInspectorPanel
      activeImage={activeImage}
      categories={categories}
      categoryColor={(category) => categoryColor(category, categories)}
      detections={draftDetections}
      onDetectionCategoryChange={updateDetectionCategory}
      onDetectionConfidenceChange={updateDetectionConfidence}
      onRemoveDetection={removeDetection}
      onSelectDetection={setSelectedDetectionIndex}
      selectedDetectionIndex={selectedDetectionIndex}
      statusLabel={activeImage ? annotationStatusLabel(activeImage.annotationStatus) : "无图片"}
    />
  );

  const scaledViewport = imageViewport
    ? { width: imageViewport.width * zoom, height: imageViewport.height * zoom }
    : null;
  const suggestedDetections = Boolean(activeImage && !isProcessed(activeImage.annotationStatus) && !hasAnnotationChanges);

  return (
    <div className="flex h-screen min-h-0 w-full flex-col overflow-hidden bg-[var(--df-color-bg-layout)] text-[var(--df-color-text)]">
      <header className="z-20 shrink-0 border-b border-[var(--df-color-border-secondary)] bg-[var(--df-color-bg-container)] px-3 py-2 sm:px-4">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <Link
              to={`/datasets/${dataset.id}`}
              aria-label="返回数据集"
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[var(--df-color-text-secondary)] transition-colors duration-200 hover:bg-[var(--df-color-fill-alter)] hover:text-[var(--df-color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--df-color-primary)]"
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            </Link>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[11px] text-neutral-500 dark:text-neutral-400">
                <PencilRuler aria-hidden="true" className="h-3.5 w-3.5" />
                <span>标注工作台</span>
              </div>
              <Typography.Text className="block max-w-[46vw] truncate text-sm font-semibold sm:max-w-sm sm:text-base">
                {dataset.name}
              </Typography.Text>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <span className="hidden font-mono text-xs tabular-nums text-neutral-500 dark:text-neutral-400 sm:inline">
              完成 {annotatedTotal}/{totalImageCount}
            </span>
            {saveStatus === "unsaved" ? (
              <Tag color="warning" className="!mr-0">未保存</Tag>
            ) : saveStatus === "pending" ? (
              <Tag color="processing" className="!mr-0">待确认</Tag>
            ) : (
              <Tag color="success" className="!mr-0">已保存</Tag>
            )}
            {draftRecovered ? <Tag color="processing" className="hidden !mr-0 md:inline-flex">已恢复草稿</Tag> : null}
          </div>
        </div>
      </header>

      {actionError ? (
        <Alert
          message={actionError}
          description="请检查网络或数据状态后重试。当前草稿仍保留在此浏览器中。"
          type="error"
          showIcon
          closable
          onClose={() => setActionError(null)}
          className="z-10 shrink-0 rounded-none border-x-0 border-t-0"
        />
      ) : null}

      <div className="sr-only" role="status" aria-live="polite">{saveAnnouncement}</div>

      <div className={cn("grid min-h-0 flex-1 overflow-hidden", isDesktop ? "grid-cols-[248px_minmax(0,1fr)_336px]" : "grid-cols-1")}>
        {isDesktop ? <div className="min-h-0 border-r border-[var(--df-color-border-secondary)]">{queuePanel}</div> : null}

        <main id="annotation-canvas" className="relative flex min-h-0 flex-col bg-[#0b0f14]">
          <div className="flex h-[52px] shrink-0 items-center gap-2 border-b border-white/10 px-3 text-white">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              {!isDesktop ? (
                <Button
                  type="text"
                  icon={<Menu aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setQueueOpen(true)}
                  className="!text-white hover:!bg-white/10"
                  aria-label="打开标注队列"
                />
              ) : null}
              <MousePointer2 aria-hidden="true" className="hidden h-4 w-4 shrink-0 text-neutral-500 sm:block" />
              <div className="min-w-0">
                <Typography.Text className="block truncate text-sm font-medium !text-white">
                  <span className="sm:hidden">#{activeImage?.ordinal ?? "—"}</span>
                  <span className="hidden sm:inline">样本 #{activeImage?.ordinal ?? "—"}</span>
                </Typography.Text>
                <Typography.Text className="hidden truncate text-xs !text-neutral-400 sm:block">{activeImage?.sourceType ?? "没有可处理图片"}</Typography.Text>
              </div>
              {suggestedDetections ? <Tag className="hidden !mr-0 lg:inline-flex">模型建议</Tag> : null}
            </div>

            <div className="flex shrink-0 items-center justify-end gap-1.5 sm:gap-2">
              <Select
                aria-label="当前画框类别"
                value={activeCategory}
                className="w-24 sm:w-36"
                options={(categories.length > 0 ? categories : ["object"]).map((category, index) => ({
                  value: category,
                  label: `${index + 1}. ${category}`,
                }))}
                onChange={(value) => changeActiveCategory(value as string)}
              />
              <Tooltip title={boxesVisible ? "隐藏检测框" : "显示检测框"}>
                <Button
                  icon={boxesVisible ? <Eye aria-hidden="true" className="h-4 w-4" /> : <EyeOff aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setBoxesVisible((current) => !current)}
                  aria-label={boxesVisible ? "隐藏检测框" : "显示检测框"}
                />
              </Tooltip>
              {segmentAssistAvailable ? (
                <Tooltip title="启用一次智能点选（S）">
                  <Button
                    type={activeAnnotationTool === "smart-select" ? "primary" : "default"}
                    icon={<ScanSearch aria-hidden="true" className="h-4 w-4" />}
                    onClick={() => {
                      if (activeAnnotationTool === "smart-select") finishSmartSelect();
                      else changeAnnotationTool("smart-select");
                    }}
                    disabled={!activeImage}
                    aria-pressed={activeAnnotationTool === "smart-select"}
                    aria-label="智能点选"
                  >
                    <span className="hidden 2xl:inline">智能点选</span>
                  </Button>
                </Tooltip>
              ) : null}
              <Button
                type={activeAnnotationTool === "box" && isAddingDetection ? "primary" : "default"}
                icon={<PencilRuler aria-hidden="true" className="h-4 w-4" />}
                onClick={() => {
                  if (activeAnnotationTool !== "box") changeAnnotationTool("box");
                  else setIsAddingDetection((current) => !current);
                }}
                disabled={!activeImage}
                aria-pressed={activeAnnotationTool === "box" && isAddingDetection}
                aria-label={activeAnnotationTool === "box" && isAddingDetection ? "结束画框" : "新增框"}
              >
                <span className="hidden sm:inline">
                  {activeAnnotationTool === "box" && isAddingDetection ? "拖动画框" : "新增框"}
                </span>
                <span className="ml-1 rounded bg-black/10 px-1.5 font-mono text-xs tabular-nums dark:bg-white/10">
                  {draftDetections.length}
                </span>
              </Button>
              {!isDesktop ? (
                <Button
                  icon={<PanelRight aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setInspectorOpen(true)}
                  aria-label="检查器"
                />
              ) : null}
            </div>
          </div>

          <div ref={stageRef} className="relative min-h-0 flex-1 overflow-auto overscroll-contain bg-[#0b0f14]">
            {activeAnnotationTool === "smart-select" && activeImage ? (
              <div className="pointer-events-none sticky left-0 top-3 z-20 flex h-0 w-full justify-center px-3">
                <div className="pointer-events-auto flex max-w-full items-center gap-1.5 rounded-xl border border-white/10 bg-black/70 p-1.5 text-xs text-neutral-200 shadow-xl backdrop-blur-md">
                  <Tooltip title="在目标内部添加选择点">
                    <Button
                      type={segmentPointLabel === "positive" ? "primary" : "text"}
                      size="small"
                      icon={<CirclePlus aria-hidden="true" className="h-3.5 w-3.5" />}
                      onClick={() => setSegmentPointLabel("positive")}
                      className={segmentPointLabel === "positive" ? "" : "!text-neutral-200 hover:!bg-white/10"}
                      aria-label="添加正点"
                    >
                      <span className="hidden sm:inline">选择</span>
                    </Button>
                  </Tooltip>
                  <Tooltip title="点击需要从目标中排除的区域">
                    <Button
                      type={segmentPointLabel === "negative" ? "primary" : "text"}
                      size="small"
                      icon={<CircleMinus aria-hidden="true" className="h-3.5 w-3.5" />}
                      onClick={() => setSegmentPointLabel("negative")}
                      disabled={!segmentPoints.some((point) => point.label === "positive")}
                      className={segmentPointLabel === "negative" ? "" : "!text-neutral-200 hover:!bg-white/10"}
                      aria-label="添加排除点"
                    >
                      <span className="hidden sm:inline">排除</span>
                    </Button>
                  </Tooltip>
                  <span className="hidden min-w-24 px-1 text-center text-neutral-300 md:inline">
                    {isPreparingSegment
                      ? "正在准备模型…"
                      : isPredictingSegment
                        ? "正在更新候选…"
                        : segmentPrediction
                          ? `候选 ${Math.round(segmentPrediction.maskScore * 100)}%`
                          : "点击图片中的目标"}
                  </span>
                  <Button
                    type="primary"
                    size="small"
                    icon={isPreparingSegment || isPredictingSegment
                      ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                      : <Check aria-hidden="true" className="h-3.5 w-3.5" />}
                    onClick={confirmSegmentPrediction}
                    disabled={!segmentPrediction || isPreparingSegment || isPredictingSegment}
                    aria-label="确认智能候选框"
                  >
                    确认
                  </Button>
                  <Button
                    type="text"
                    size="small"
                    icon={<X aria-hidden="true" className="h-3.5 w-3.5" />}
                    onClick={finishSmartSelect}
                    className="!text-neutral-200 hover:!bg-white/10"
                    aria-label="取消智能候选框"
                  />
                </div>
              </div>
            ) : null}
            <div className="flex min-h-full min-w-full items-center justify-center p-4">
              {activeImage && scaledViewport && scaledViewport.width > 0 && scaledViewport.height > 0 ? (
                <div
                  ref={viewportRef}
                  data-testid="annotation-viewport"
                  className={cn(
                    "relative shrink-0 select-none touch-none bg-neutral-900 shadow-2xl",
                    activeAnnotationTool === "smart-select" || isAddingDetection ? "cursor-crosshair" : "cursor-default",
                  )}
                  style={{ width: scaledViewport.width, height: scaledViewport.height }}
                  onPointerDown={handleStagePointerDown}
                >
                  <AuthImage
                    src={activeImage.previewSvg}
                    alt={activeImage.promptText}
                    width={previewImageNaturalSize?.width ?? Math.round(scaledViewport.width)}
                    height={previewImageNaturalSize?.height ?? Math.round(scaledViewport.height)}
                    className="h-full w-full"
                    draggable={false}
                    onLoad={(event) => {
                      const target = event.currentTarget;
                      setPreviewImageNaturalSize({ width: target.naturalWidth, height: target.naturalHeight });
                    }}
                  />
                  {segmentPrediction ? (
                    <img
                      src={segmentPrediction.maskDataUrl}
                      alt=""
                      aria-hidden="true"
                      draggable={false}
                      className="pointer-events-none absolute inset-0 h-full w-full"
                    />
                  ) : null}
                  {segmentPrediction ? (
                    <div
                      aria-hidden="true"
                      className="pointer-events-none absolute border-2 border-dashed border-teal-300 shadow-[0_0_0_1px_rgba(0,0,0,0.45)]"
                      style={detectionStyle(segmentPrediction.bbox)}
                    />
                  ) : null}
                  {segmentPoints.map((point, index) => (
                    <span
                      key={`${point.label}-${index}`}
                      aria-hidden="true"
                      className={cn(
                        "pointer-events-none absolute z-10 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-md",
                        point.label === "positive" ? "bg-emerald-500" : "bg-rose-500",
                      )}
                      style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
                    />
                  ))}
                  {boxesVisible ? (
                    <div className="pointer-events-none absolute inset-0">
                      {draftDetections.map((detection, index) => {
                        const selected = selectedDetectionIndex === index;
                        const color = selected ? "#f4f4f5" : categoryColor(detection.category, categories);
                        return (
                          <div
                            key={`${detection.category}-${index}`}
                            role="button"
                            tabIndex={0}
                            aria-label={`选择检测框 ${index + 1}，类别 ${detection.category}`}
                            className={cn(
                              "absolute border-2 shadow-[0_0_0_1px_rgba(0,0,0,0.45)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white",
                              activeAnnotationTool === "smart-select" ? "pointer-events-none" : "pointer-events-auto",
                              suggestedDetections ? "border-dashed" : "border-solid",
                              selected ? "shadow-[0_0_0_9999px_rgba(0,0,0,0.10)]" : "",
                            )}
                            style={{ ...detectionStyle(detection.bbox), borderColor: color }}
                            onPointerDown={(event) => beginDragDetection(index, event)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                setSelectedDetectionIndex(index);
                              } else if (event.key === "Delete" || event.key === "Backspace") {
                                event.preventDefault();
                                removeDetection(index);
                              }
                            }}
                          >
                            <div
                              className="absolute left-0 top-0 max-w-full -translate-y-full truncate px-1.5 py-0.5 font-mono text-[10px] font-medium text-neutral-950"
                              style={{ backgroundColor: color }}
                            >
                              {detection.category} · {(detection.confidence * 100).toFixed(0)}%
                            </div>
                            {selected
                              ? (["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
                                  <button
                                    key={corner}
                                    type="button"
                                    aria-label={`从${corner}方向缩放检测框 ${index + 1}`}
                                    className={cn(
                                      "absolute h-11 w-11 touch-none appearance-none border-0 bg-transparent p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white",
                                      corner === "nw"
                                        ? "-left-[22px] -top-[22px]"
                                        : corner === "ne"
                                          ? "-right-[22px] -top-[22px]"
                                          : corner === "sw"
                                            ? "-bottom-[22px] -left-[22px]"
                                            : "-bottom-[22px] -right-[22px]",
                                    )}
                                    onPointerDown={(event) => beginResizeDetection(index, corner, event)}
                                  >
                                    <span
                                      aria-hidden="true"
                                      className="pointer-events-none absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[#0b0f14]"
                                    />
                                  </button>
                                ))
                              : null}
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              ) : activeImage ? (
                <AuthImage
                  src={activeImage.previewSvg}
                  alt={activeImage.promptText}
                  width={960}
                  height={640}
                  className="max-h-full max-w-full object-contain"
                  draggable={false}
                  onLoad={(event) => {
                    const target = event.currentTarget;
                    setPreviewImageNaturalSize({ width: target.naturalWidth, height: target.naturalHeight });
                  }}
                />
              ) : isLoadingFirstPage ? (
                <div className="flex items-center justify-center gap-2 px-5 text-center text-sm text-neutral-400">
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                  正在加载图片…
                </div>
              ) : (
                <div className="px-5 text-center text-sm text-neutral-400">当前筛选没有图片。</div>
              )}
            </div>
          </div>

          <div className="pointer-events-none absolute bottom-[72px] left-3 z-10 hidden sm:block">
            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              className="pointer-events-auto flex cursor-pointer appearance-none items-center gap-1.5 rounded-lg border border-white/10 bg-black/55 px-2.5 py-2 text-xs text-neutral-300 shadow-lg backdrop-blur-md transition-colors duration-200 hover:bg-black/75 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            >
              <Keyboard aria-hidden="true" className="h-3.5 w-3.5" />
              {segmentAssistAvailable ? "S 智能点选一次 · B 画框" : "B 画框"} · Enter {segmentPrediction ? "确认候选" : "保存下一张"}
            </button>
          </div>

          <div className="pointer-events-none absolute bottom-[72px] right-3 z-10">
            <div className="pointer-events-auto flex items-center gap-0.5 rounded-lg border border-white/10 bg-black/55 p-1 text-xs text-neutral-300 shadow-lg backdrop-blur-md">
              <Button
                type="text"
                size="small"
                icon={<ZoomOut aria-hidden="true" className="h-3.5 w-3.5" />}
                onClick={() => setZoom((current) => Math.max(MIN_ZOOM, current - ZOOM_STEP))}
                disabled={zoom <= MIN_ZOOM}
                className="!text-neutral-300 hover:!bg-white/10"
                aria-label="缩小画布"
              />
              <span className="w-12 text-center font-mono tabular-nums">{Math.round(zoom * 100)}%</span>
              <Button
                type="text"
                size="small"
                icon={<ZoomIn aria-hidden="true" className="h-3.5 w-3.5" />}
                onClick={() => setZoom((current) => Math.min(MAX_ZOOM, current + ZOOM_STEP))}
                disabled={zoom >= MAX_ZOOM}
                className="!text-neutral-300 hover:!bg-white/10"
                aria-label="放大画布"
              />
              <Button
                type="text"
                size="small"
                icon={<Maximize2 aria-hidden="true" className="h-3.5 w-3.5" />}
                onClick={() => setZoom(1)}
                className="!text-neutral-300 hover:!bg-white/10"
                aria-label="适应画布"
              />
            </div>
          </div>

          <footer className="flex h-[60px] shrink-0 items-center justify-between gap-2 border-t border-white/10 bg-[#111317] px-2 text-xs text-neutral-400 sm:px-3">
            <div className="flex shrink-0 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-1">
              <Button
                type="text"
                icon={<ChevronLeft aria-hidden="true" className="h-4 w-4" />}
                onClick={() => void moveActiveImage(-1)}
                disabled={activeIndex <= 0 || Boolean(deletingImageId)}
                className="!text-neutral-200 hover:!bg-white/10"
                aria-label="上一张图片"
              />
              <span className="min-w-12 text-center font-mono text-xs tabular-nums text-neutral-300">
                {activeIndex + 1}/{imagesTotal}
              </span>
              <Button
                type="text"
                icon={<ChevronRight aria-hidden="true" className="h-4 w-4" />}
                onClick={() => void moveActiveImage(1)}
                disabled={(activeIndex >= images.length - 1 && !hasMoreImages) || Boolean(deletingImageId) || isLoadingMore}
                className="!text-neutral-200 hover:!bg-white/10"
                aria-label="下一张图片"
              />
            </div>

            <div className="flex min-w-0 items-center justify-end gap-1.5 sm:gap-2">
              <div className="hidden items-center gap-1 md:flex">
                <Tooltip title="撤销（Ctrl/⌘ + Z）">
                  <Button
                    type="text"
                    icon={<Undo2 aria-hidden="true" className="h-4 w-4" />}
                    onClick={undoDetectionChange}
                    disabled={!canUndo}
                    className="!text-neutral-200 hover:!bg-white/10"
                    aria-label="撤销标注操作"
                  />
                </Tooltip>
                <Tooltip title="重做（Ctrl/⌘ + Shift + Z）">
                  <Button
                    type="text"
                    icon={<Redo2 aria-hidden="true" className="h-4 w-4" />}
                    onClick={redoDetectionChange}
                    disabled={!canRedo}
                    className="!text-neutral-200 hover:!bg-white/10"
                    aria-label="重做标注操作"
                  />
                </Tooltip>
              </div>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    {
                      key: "undo",
                      disabled: !canUndo,
                      icon: <Undo2 aria-hidden="true" className="h-4 w-4" />,
                      label: "撤销",
                    },
                    {
                      key: "redo",
                      disabled: !canRedo,
                      icon: <Redo2 aria-hidden="true" className="h-4 w-4" />,
                      label: "重做",
                    },
                    {
                      key: "shortcuts",
                      icon: <Keyboard aria-hidden="true" className="h-4 w-4" />,
                      label: "快捷键",
                    },
                    { type: "divider" },
                    {
                      key: "delete-image",
                      danger: true,
                      disabled: !activeImage || isSaving || Boolean(deletingImageId),
                      icon: isDeletingActiveImage
                        ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                        : <Trash2 aria-hidden="true" className="h-4 w-4" />,
                      label: "删除当前图片",
                    },
                  ],
                  onClick: ({ key }) => {
                    if (key === "undo") undoDetectionChange();
                    if (key === "redo") redoDetectionChange();
                    if (key === "shortcuts") setHelpOpen(true);
                    if (key === "delete-image" && activeImage) void removeDatasetImage(activeImage);
                  },
                }}
              >
                <Button
                  icon={<MoreHorizontal aria-hidden="true" className="h-4 w-4" />}
                  className="shrink-0"
                  aria-label="更多图片操作"
                />
              </Dropdown>
              <Button
                className="shrink-0"
                onClick={() => void markEmptyAndAdvance()}
                disabled={!activeImage || isSaving}
              >
                <span className="hidden sm:inline">标记为空</span>
                <span className="sm:hidden">空标注</span>
              </Button>
              <Button
                type="primary"
                icon={isSaving
                  ? <Loader2 aria-hidden="true" className="hidden h-4 w-4 animate-spin sm:block" />
                  : <Save aria-hidden="true" className="hidden h-4 w-4 sm:block" />}
                onClick={() => void confirmAndAdvance()}
                disabled={isSaving || !activeImage || Boolean(deletingImageId)}
                className="shrink-0"
              >
                <span className="hidden sm:inline">保存并下一张</span>
                <span className="sm:hidden">保存下一张</span>
              </Button>
            </div>
          </footer>
        </main>

        {isDesktop ? <div className="min-h-0 border-l border-[var(--df-color-border-secondary)]">{inspectorPanel}</div> : null}
      </div>

      {!isDesktop ? (
        <Drawer
          title="标注队列"
          placement="left"
          width="min(320px, calc(100vw - 24px))"
          open={queueOpen}
          onClose={() => setQueueOpen(false)}
          styles={{ body: { padding: 0 }, header: { paddingBlock: 12 } }}
        >
          {queuePanel}
        </Drawer>
      ) : null}

      {!isDesktop ? (
        <Drawer
          title="标注检查器"
          placement={isTablet ? "right" : "bottom"}
          width={isTablet ? 360 : "100%"}
          height={isTablet ? "100%" : "78%"}
          open={inspectorOpen}
          onClose={() => setInspectorOpen(false)}
          styles={{ body: { padding: 0 }, header: { paddingBlock: 12 } }}
        >
          {inspectorPanel}
        </Drawer>
      ) : null}

      <Modal
        title="键盘快捷键"
        open={helpOpen}
        onCancel={() => setHelpOpen(false)}
        footer={
          <Button type="primary" onClick={() => setHelpOpen(false)}>
            知道了
          </Button>
        }
      >
        <div className="grid gap-2 py-2">
          {shortcuts.map((item) => (
            <div key={item.keys} className="flex items-center justify-between rounded-lg bg-neutral-50 px-3 py-2 dark:bg-white/5">
              <Typography.Text className="font-mono text-sm">{item.keys}</Typography.Text>
              <Typography.Text className="text-sm text-neutral-600 dark:text-neutral-300">{item.action}</Typography.Text>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}
