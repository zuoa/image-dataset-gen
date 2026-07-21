import { useQuery } from "@tanstack/react-query";

import { listTrainingModels } from "../api/training";
import type { TrainingModelCatalog } from "../lib/types";
import { useAuthStore } from "../store/auth";

export const fallbackTrainingModelCatalog: TrainingModelCatalog = {
  source: "preset",
  onlineWorkerCount: 0,
  observedAt: "",
  models: [
    ["yolov8n.pt", "YOLOv8 Nano", "yolov8", true],
    ["yolov8s.pt", "YOLOv8 Small", "yolov8", false],
    ["yolov8m.pt", "YOLOv8 Medium", "yolov8", false],
    ["yolov8l.pt", "YOLOv8 Large", "yolov8", false],
    ["yolov8x.pt", "YOLOv8 XLarge", "yolov8", false],
    ["yolo11n.pt", "YOLO11 Nano", "yolo11", false],
    ["yolo11s.pt", "YOLO11 Small", "yolo11", false],
    ["yolo11m.pt", "YOLO11 Medium", "yolo11", false],
    ["yolo11l.pt", "YOLO11 Large", "yolo11", false],
    ["yolo11x.pt", "YOLO11 XLarge", "yolo11", false],
  ].map(([id, label, framework, recommended]) => ({
    id: String(id),
    label: String(label),
    framework: String(framework),
    task: "detect",
    recommended: Boolean(recommended),
    cached: false,
    availableWorkerCount: 0,
    cachedWorkerCount: 0,
  })),
};

export function useTrainingModels() {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["training-models", token],
    queryFn: ({ signal }) => listTrainingModels(token!, signal),
    enabled: !!token,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  });
}
