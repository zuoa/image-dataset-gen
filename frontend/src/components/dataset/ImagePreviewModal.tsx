import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { ChevronLeft, ChevronRight, ImageIcon, Plus, Save, Trash2, X } from "lucide-react";
import { Button, Input, Modal, Select, Tag, Typography } from "antd";

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
      setImageViewport(
        fitImageViewport(
          stage.clientWidth,
          stage.clientHeight,
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
      if (event.key === "Escape" && isAddingDetection) {
        event.preventDefault();
        event.stopPropagation();
        setIsAddingDetection(false);
        return;
      }

      if (event.target instanceof HTMLElement && event.target.closest("input, textarea, select, button")) return;

      if (event.key === "ArrowLeft" && previewIndex > 0) {
        event.preventDefault();
        movePreview(-1);
      }
      if (event.key === "ArrowRight" && previewIndex < images.length - 1) {
        event.preventDefault();
        movePreview(1);
      }
      if (event.key === "Delete" && selectedDetectionIndex !== null) {
        event.preventDefault();
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

  async function closePreview() {
    if (await onConfirmDiscardChanges()) {
      onClose();
    }
  }

  if (!previewImage) return null;

  return (
    <Modal
      open={open}
      onCancel={() => void closePreview()}
      footer={null}
      closable={false}
      title={null}
      centered
      width="min(1600px, calc(100vw - 24px))"
      styles={{
        mask: {
          background: "rgba(3, 7, 12, 0.76)",
          backdropFilter: "blur(6px)",
        },
        content: {
          padding: 0,
          overflow: "hidden",
          borderRadius: 16,
        },
        body: {
          height: "min(900px, calc(100dvh - 32px))",
        },
      }}
      keyboard={!isAddingDetection}
    >
      <div className="grid h-full min-h-0 w-full grid-rows-[minmax(0,1fr)_minmax(280px,42%)] bg-white text-neutral-900 dark:bg-[#11151b] dark:text-white lg:grid-cols-[minmax(0,1fr)_360px] lg:grid-rows-1">
        <section className="relative min-h-0 overflow-hidden bg-[#080c11]" aria-label="图片画布">
          <div className="pointer-events-none absolute left-3 right-3 top-3 z-20 flex items-center justify-between gap-3 sm:left-4 sm:right-4 sm:top-4">
            <div className="pointer-events-auto flex min-w-0 items-center gap-2 rounded-xl border border-white/10 bg-black/55 px-3 py-2 text-white shadow-lg backdrop-blur-md">
              <ImageIcon aria-hidden="true" className="h-4 w-4 shrink-0 text-sky-300" />
              <span className="truncate text-sm font-medium">样本 #{previewImage.ordinal}</span>
              <span className="font-mono text-xs tabular-nums text-neutral-400">
                {previewIndex + 1}/{images.length}
              </span>
              <span className="hidden h-4 w-px bg-white/15 sm:block" />
              <span className="hidden font-mono text-xs text-neutral-300 sm:block">
                {draftDetections.length} 个框
              </span>
            </div>

            <div className="pointer-events-auto flex shrink-0 items-center gap-1 rounded-xl border border-white/10 bg-black/55 p-1 shadow-lg backdrop-blur-md">
              <button
                type="button"
                aria-label="上一张图片"
                className="flex h-11 w-11 cursor-pointer appearance-none items-center justify-center rounded-lg border-0 bg-transparent p-0 text-white transition-colors duration-200 hover:bg-white/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-30"
                onClick={() => void movePreview(-1)}
                disabled={previewIndex <= 0}
              >
                <ChevronLeft aria-hidden="true" className="h-5 w-5" />
              </button>
              <button
                type="button"
                aria-label="下一张图片"
                className="flex h-11 w-11 cursor-pointer appearance-none items-center justify-center rounded-lg border-0 bg-transparent p-0 text-white transition-colors duration-200 hover:bg-white/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-30"
                onClick={() => void movePreview(1)}
                disabled={previewIndex >= images.length - 1}
              >
                <ChevronRight aria-hidden="true" className="h-5 w-5" />
              </button>
              <span className="mx-0.5 h-6 w-px bg-white/15" />
              <button
                type="button"
                aria-label="关闭图片详情"
                className="flex h-11 w-11 cursor-pointer appearance-none items-center justify-center rounded-lg border-0 bg-transparent p-0 text-white transition-colors duration-200 hover:bg-white/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                onClick={() => void closePreview()}
              >
                <X aria-hidden="true" className="h-5 w-5" />
              </button>
            </div>
          </div>

          <div
            ref={stageRef}
            data-testid="image-preview-stage"
            className="absolute inset-x-3 bottom-3 top-[68px] flex items-center justify-center overflow-hidden sm:inset-x-5 sm:bottom-5 sm:top-20"
          >
            {imageViewport && imageViewport.width > 0 && imageViewport.height > 0 ? (
              <div
                ref={viewportRef}
                className={`relative shrink-0 bg-neutral-900 shadow-[0_24px_80px_rgba(0,0,0,0.45)] ${
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
                  width={previewImageNaturalSize?.width ?? Math.round(imageViewport.width)}
                  height={previewImageNaturalSize?.height ?? Math.round(imageViewport.height)}
                  className="h-full w-full object-contain"
                  draggable={false}
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
                      className={`pointer-events-auto absolute rounded-sm border-2 shadow-[0_0_0_1px_rgba(0,0,0,0.65)] ${
                        selectedDetectionIndex === index
                          ? "border-lime-300 shadow-[0_0_0_9999px_rgba(0,0,0,0.12)]"
                          : "border-sky-400"
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
                      {selectedDetectionIndex === index
                        ? (["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
                            <button
                              key={corner}
                              type="button"
                              aria-label={`从${corner}方向缩放检测框 ${index + 1}`}
                              className={`absolute h-11 w-11 rounded-full border-0 bg-transparent p-0 ${
                                corner === "nw"
                                  ? "-left-[22px] -top-[22px]"
                                  : corner === "ne"
                                    ? "-right-[22px] -top-[22px]"
                                    : corner === "sw"
                                      ? "-bottom-[22px] -left-[22px]"
                                      : "-bottom-[22px] -right-[22px]"
                              }`}
                              onMouseDown={(event) => beginResizeDetection(index, corner, event)}
                            >
                              <span className="absolute left-1/2 top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-neutral-950" />
                            </button>
                          ))
                        : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <AuthImage
                src={previewImage.previewSvg}
                alt={previewImage.promptText}
                className="h-full w-full object-contain"
                draggable={false}
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
          {isAddingDetection ? (
            <div className="pointer-events-none absolute bottom-5 left-1/2 z-20 -translate-x-1/2 rounded-full border border-sky-300/30 bg-sky-400/15 px-4 py-2 text-sm text-sky-100 shadow-lg backdrop-blur-md">
              在图片上拖拽创建检测框 · Esc 取消
            </div>
          ) : null}
        </section>

        <aside className="flex min-h-0 flex-col border-t border-neutral-200 bg-white dark:border-white/10 dark:bg-[#11151b] lg:border-l lg:border-t-0" aria-label="图片标注信息">
          <div className="shrink-0 border-b border-neutral-200 px-4 py-3 dark:border-white/10 sm:px-5 sm:py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs font-medium text-neutral-500 dark:text-neutral-400">图片详情</div>
                <Typography.Title level={4} className="!mb-0 !mt-1">
                  样本 #{previewImage.ordinal}
                </Typography.Title>
              </div>
              <Button
                type="text"
                danger
                icon={<Trash2 aria-hidden="true" className="h-4 w-4" />}
                onClick={() => onDeleteImage(previewImage)}
                disabled={isSavingAnnotations}
                aria-label={`删除样本 #${previewImage.ordinal}`}
              />
            </div>
            <Typography.Paragraph className="!mb-0 !mt-2 line-clamp-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
              {previewImage.promptText}
            </Typography.Paragraph>
            <div className="mt-3 flex flex-wrap gap-2">
              <Tag bordered={false}>{previewImage.sourceType}</Tag>
              <Tag bordered={false}>{previewImage.annotationStatus}</Tag>
            </div>
          </div>

          <div className="shrink-0 border-b border-neutral-200 p-3 dark:border-white/10 sm:px-4">
            <div className="grid grid-cols-2 gap-2">
              <Button
                icon={<Plus aria-hidden="true" className="h-4 w-4" />}
                onClick={() => setIsAddingDetection(!isAddingDetection)}
              >
                {isAddingDetection ? "取消新增框" : "新增框"}
              </Button>
              <Button
                type="primary"
                icon={<Save aria-hidden="true" className="h-4 w-4" />}
                onClick={() => void onSaveAnnotations()}
                loading={isSavingAnnotations}
              >
                保存标注
              </Button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4">
            <div className="mb-3 flex items-center justify-between px-1">
              <Typography.Text className="text-sm font-semibold">检测对象</Typography.Text>
              <Typography.Text className="font-mono text-xs text-neutral-500 dark:text-neutral-400">
                {draftDetections.length} 个框
              </Typography.Text>
            </div>
            <div className="space-y-2">
              {draftDetections.map((detection, index) => (
                <section
                key={`${detection.category}-${index}`}
                className={`rounded-xl border p-3 transition-colors duration-200 ${
                  selectedDetectionIndex === index
                    ? "border-blue-500 bg-blue-50/70 ring-1 ring-blue-500/15 dark:bg-blue-400/10"
                    : "border-neutral-200 bg-white hover:border-neutral-300 dark:border-white/10 dark:bg-black/10 dark:hover:border-white/20"
                }`}
                onClick={() => setSelectedDetectionIndex(index)}
                aria-label={`检测框 ${index + 1}`}
              >
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-neutral-100 font-mono text-xs dark:bg-white/10">
                      {index + 1}
                    </span>
                    <span className="truncate text-sm font-medium">{detection.category}</span>
                  </div>
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<Trash2 aria-hidden="true" className="h-4 w-4" />}
                    onClick={(event) => {
                      event.stopPropagation();
                      removeDetection(index);
                    }}
                    aria-label={`删除检测框 ${index + 1}`}
                  />
                </div>
                <div className="grid gap-3">
                  <label className="grid gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                    类别
                    {dataset.categories.length > 0 ? (
                      <Select
                        aria-label={`检测框 ${index + 1} 的类别`}
                        value={detection.category}
                        options={dataset.categories.map((category) => ({ value: category, label: category }))}
                        onChange={(value) => updateDetectionField(index, "category", value as string)}
                      />
                    ) : (
                      <Input
                        aria-label={`检测框 ${index + 1} 的类别`}
                        value={detection.category}
                        onChange={(event) => updateDetectionField(index, "category", event.target.value)}
                      />
                    )}
                  </label>
                  <label className="grid gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                    <span className="flex items-center justify-between">
                      <span>置信度</span>
                      <span className="font-mono tabular-nums">{(detection.confidence * 100).toFixed(0)}%</span>
                    </span>
                    <Input
                      aria-label={`检测框 ${index + 1} 的置信度`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={detection.confidence}
                      onChange={(event) => updateDetectionField(index, "confidence", Number(event.target.value))}
                    />
                  </label>
                </div>
                </section>
              ))}
              {draftDetections.length === 0 ? (
                <div className="rounded-xl border border-dashed border-neutral-300 p-4 text-center text-sm leading-6 text-neutral-500 dark:border-white/15 dark:text-neutral-400">
                  当前没有检测框。可以点击“新增框”后直接在图片上拖拽创建。
                </div>
              ) : null}
            </div>
          </div>
        </aside>
      </div>
    </Modal>
  );
}
