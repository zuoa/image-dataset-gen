import type { CSSProperties } from "react";

import type { DatasetImage } from "./types";

export const DEFAULT_BOX_SIZE = 0.22;
export const MIN_BOX_SIZE = 0.04;

export type Detection = DatasetImage["detections"][number];
export type ResizeCorner = "nw" | "ne" | "sw" | "se";
export type ImageViewport = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export function detectionStyle([xCenter, yCenter, width, height]: [number, number, number, number]): CSSProperties {
  return {
    left: `${(xCenter - width / 2) * 100}%`,
    top: `${(yCenter - height / 2) * 100}%`,
    width: `${width * 100}%`,
    height: `${height * 100}%`,
  };
}

export function clamp(value: number, min = 0, max = 1) {
  return Math.min(Math.max(value, min), max);
}

export function pointerToStage(rect: DOMRect, clientX: number, clientY: number) {
  return {
    x: clamp((clientX - rect.left) / rect.width),
    y: clamp((clientY - rect.top) / rect.height),
  };
}

export function fitImageViewport(
  containerWidth: number,
  containerHeight: number,
  imageWidth: number,
  imageHeight: number,
): ImageViewport {
  if (containerWidth <= 0 || containerHeight <= 0 || imageWidth <= 0 || imageHeight <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }

  const containerAspect = containerWidth / containerHeight;
  const imageAspect = imageWidth / imageHeight;

  if (imageAspect > containerAspect) {
    const width = containerWidth;
    const height = width / imageAspect;
    return {
      left: 0,
      top: (containerHeight - height) / 2,
      width,
      height,
    };
  }

  const height = containerHeight;
  const width = height * imageAspect;
  return {
    left: (containerWidth - width) / 2,
    top: 0,
    width,
    height,
  };
}

export function boxFromCorners(startX: number, startY: number, endX: number, endY: number): [number, number, number, number] {
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

export function detectionsEqual(left: Detection[], right: Detection[]) {
  return JSON.stringify(left) === JSON.stringify(right);
}
