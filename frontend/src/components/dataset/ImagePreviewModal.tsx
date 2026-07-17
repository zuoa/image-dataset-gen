import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { ChevronLeft, ChevronRight, Trash2, X } from "lucide-react";
import { Button, Drawer, Input, Space, Tag, Typography } from "antd";

import { AuthImage } from "../AuthImage";
import {
  boxFromCorners,
  DEFAULT_BOX_SIZE,
  detectionStyle,
  fitImageViewport,
  minimumBoxSizeForImage,
  pointerToStage,
  type ImageViewport,
  type ResizeCorner,
} from "../../lib/annotation";
import type { Dataset, DatasetImage } from "../../lib/types";

interface ImagePreviewModalProps {
  open: boolean;
  onClose: () => void;
  previewImage: DatasetImage | null;
  images: DatasetImage[];
  dataset: Dataset;
  draftDetections: DatasetImage["detections"];
  setDraftDetections: React.Dispatch<
    React.SetStateAction<DatasetImage["detections"]>
  >;
  selectedDetectionIndex: number | null;
  setSelectedDetectionIndex: React.Dispatch<
    React.SetStateAction<number | null>
  >;
  isAddingDetection: boolean;
  setIsAddingDetection: (value: boolean) => void;
  isSavingAnnotations: boolean;
  onSaveAnnotations: () => void;
  onDeleteImage: (image: DatasetImage) => void;
  onPreviewChange: (imageId: string) => void;
  onConfirmDiscardChanges: () => Promise<boolean>;
}

export function ImagePreviewModal({
  open,
  onClose,
  previewImage,
  images,
  dataset,
  draftDetections,
  setDraftDetections,
  selectedDetectionIndex,
  setSelectedDetectionIndex,
  isAddingDetection,
  setIsAddingDetection,
  isSavingAnnotations,
  onSaveAnnotations,
  onDeleteImage,
  onPreviewChange,
  onConfirmDiscardChanges,
}: ImagePreviewModalProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [previewImageNaturalSize, setPreviewImageNaturalSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [imageViewport, setImageViewport] = useState<ImageViewport | null>(null);

  const previewIndex = previewImage
    ? images.findIndex((image) => image.id === previewImage.id)
    : -1;

  useEffect(() => {
    setDraftDetections(previewImage?.detections ?? []);
    setSelectedDetectionIndex(null);
    setIsAddingDetection(false);
  }, [previewImage?.id]);

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

    const handleKeydown = async (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (isAddingDetection) {
          setIsAddingDetection(false);
          return;
        }
        if (await onConfirmDiscardChanges()) {
          onClose();
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
  }, [
    images,
    isAddingDetection,
    previewImage,
    previewIndex,
    selectedDetectionIndex,
    onConfirmDiscardChanges,
    onClose,
  ]);

  async function movePreview(direction: -1 | 1) {
    if (!previewImage) return;
    const nextIndex = previewIndex + direction;
    if (nextIndex < 0 || nextIndex >= images.length) return;
    if (!(await onConfirmDiscardChanges())) return;
    onPreviewChange(images[nextIndex].id);
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
          const nextX = Math.min(
            Math.max(origin.bbox[0] + deltaX, width / 2),
            1 - width / 2,
          );
          const nextY = Math.min(
            Math.max(origin.bbox[1] + deltaY, height / 2),
            1 - height / 2,
          );
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
      const bbox = boxFromCorners(
        anchorX,
        anchorY,
        pointer.x,
        pointer.y,
        minBoxSize.width,
        minBoxSize.height,
      );
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
      {
        category,
        confidence: 0.8,
        bbox: [start.x, start.y, DEFAULT_BOX_SIZE, DEFAULT_BOX_SIZE],
      },
    ]);
    setSelectedDetectionIndex(nextIndex);

    const handleMove = (moveEvent: MouseEvent) => {
      const pointer = pointerToStage(rect, moveEvent.clientX, moveEvent.clientY);
      const bbox = boxFromCorners(
        start.x,
        start.y,
        pointer.x,
        pointer.y,
        minBoxSize.width,
        minBoxSize.height,
      );
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
          return {
            ...detection,
            category: String(value).slice(0, 120) || "object",
          };
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
    setDraftDetections((current) => current.filter((_, detectionIndex) => detectionIndex !== index),
    );
    setSelectedDetectionIndex((current) => {
      if (current === null) return null;
      if (current === index) return null;
      return current > index ? current - 1 : current;
    });
  }

  if (!previewImage) return null;

  return (
    <Drawer
      open={open}
      onClose={async () => {
        if (await onConfirmDiscardChanges()) {
          onClose();
        }
      }}
      width="100%"
      styles={{ body: { padding: 0 } }}
      closable={false}
      title={null}
    >
      <div className="relative flex h-full w-full flex-col xl:flex-row">
        <button
          type="button"
          className="absolute right-5 top-5 z-10 rounded-full bg-black/10 p-2 transition hover:bg-black/20 dark:bg-white/10 dark:hover:bg-white/20"
          onClick={async () => {
            if (await onConfirmDiscardChanges()) {
              onClose();
            }
          }}
        >
          <X className="h-5 w-5" />
        </button>

        <div className="relative flex-1 bg-neutral-950 p-4">
          <button
            type="button"
            className="absolute left-5 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/12 p-3 text-white transition hover:bg-white/20"
            onClick={() => void movePreview(-1)}
            disabled={previewIndex <= 0}
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            className="absolute right-5 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/12 p-3 text-white transition hover:bg-white/20"
            onClick={() => void movePreview(1)}
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
                className={`relative ${
                  isAddingDetection ? "cursor-crosshair" : "cursor-default"
                }`}
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
                        selectedDetectionIndex === index
                          ? "border-lime-300 shadow-[0_0_0_9999px_rgba(0,0,0,0.08)]"
                          : "border-white/90"
                      }`}
                      style={detectionStyle(detection.bbox)}
                      onMouseDown={(event) => beginDragDetection(index, event)}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedDetectionIndex(index);
                      }}
                    >
                      <div className="absolute left-0 top-0 -translate-y-full rounded-t-lg bg-black/72 px-2 py-1 text-[11px] text-white">
                        {detection.category} ·{" "}
                        {(detection.confidence * 100).toFixed(0)}%
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
          <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
            Image Inspector
          </div>
          <Typography.Title level={3} className="mt-2 !text-2xl">
            样本 #{previewImage.ordinal}
          </Typography.Title>
          <Typography.Text className="block text-sm leading-7 text-neutral-500 dark:text-neutral-400">
            {previewImage.promptText}
          </Typography.Text>
          <div className="mt-4 flex flex-wrap gap-2">
            <Tag bordered>{previewImage.sourceType}</Tag>
            <Tag bordered>{previewImage.annotationStatus}</Tag>
          </div>

          <Space className="mt-6">
            <Button onClick={() => setIsAddingDetection(!isAddingDetection)}>
              {isAddingDetection ? "取消新增框" : "新增框"}
            </Button>
            <Button
              type="primary"
              onClick={() => void onSaveAnnotations()}
              loading={isSavingAnnotations}
            >
              保存标注
            </Button>
            <Button
              danger
              icon={<Trash2 className="h-4 w-4" />}
              onClick={() => onDeleteImage(previewImage)}
              disabled={isSavingAnnotations}
            >
              删除样本
            </Button>
          </Space>

          <div className="mt-6 space-y-3">
            {draftDetections.map((detection, index) => (
              <div
                key={`${detection.category}-${index}`}
                className={`rounded-2xl border p-4 ${
                  selectedDetectionIndex === index
                    ? "border-neutral-900 bg-neutral-100 dark:border-white dark:bg-white/[0.04]"
                    : "border-neutral-200 bg-white dark:border-white/10 dark:bg-black/20"
                }`}
                onClick={() => setSelectedDetectionIndex(index)}
              >
                <div className="grid gap-3">
                  <Input
                    value={detection.category}
                    onChange={(event) =>
                      updateDetectionField(index, "category", event.target.value)
                    }
                  />
                  <Input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={detection.confidence}
                    onChange={(event) =>
                      updateDetectionField(
                        index,
                        "confidence",
                        Number(event.target.value),
                      )
                    }
                  />
                  <Button onClick={() => removeDetection(index)}>删除框</Button>
                </div>
              </div>
            ))}
            {draftDetections.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-neutral-200 p-4 text-sm text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                当前没有检测框。可以点击“新增框”后直接在图片上拖拽创建。
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </Drawer>
  );
}
