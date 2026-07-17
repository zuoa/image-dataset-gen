import { useQuery } from "@tanstack/react-query";

import { getDataset } from "../api/datasets";
import { useAuthStore } from "../store/auth";
import type { Dataset, ImageFilter } from "../lib/types";

const activeDatasetTaskStatuses = new Set(["running"]);
const activeDatasetExportStatuses = new Set(["pending", "running"]);

const POLL_INTERVAL_MS = 8_000;
const HIDDEN_POLL_INTERVAL_MS = 45_000;

function hasActiveDatasetWork(dataset: Dataset | null) {
  if (!dataset) return false;
  return (
    dataset.tasks.some((task) => activeDatasetTaskStatuses.has(task.status)) ||
    dataset.annotation?.status === "running" ||
    dataset.exports.some((item) => activeDatasetExportStatuses.has(item.status))
  );
}

export function useDatasetTasks(datasetId: string, filter?: ImageFilter) {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["dataset-tasks", datasetId, token, filter],
    queryFn: () => getDataset(datasetId, token!, { offset: 0, limit: 0, filter }),
    enabled: !!token && !!datasetId,
    refetchInterval: (query) => {
      const dataset = query.state.data?.dataset ?? null;
      if (!hasActiveDatasetWork(dataset)) return false;
      return document.visibilityState === "hidden"
        ? HIDDEN_POLL_INTERVAL_MS
        : POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: true,
    staleTime: 5_000,
  });
}
