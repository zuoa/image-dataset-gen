import { useQuery } from "@tanstack/react-query";

import { listTrainingJobs } from "../api/datasets";
import { useAuthStore } from "../store/auth";

const activeTrainingStatuses = new Set([
  "queued",
  "assigned",
  "preparing",
  "running",
  "uploading",
]);

const POLL_INTERVAL_MS = 8_000;
const HIDDEN_POLL_INTERVAL_MS = 45_000;

export function useTrainingJobs(datasetId: string) {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["training-jobs", datasetId, token],
    queryFn: () => listTrainingJobs(datasetId, token!),
    enabled: !!token && !!datasetId,
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? [];
      const hasActive = jobs.some((job) =>
        activeTrainingStatuses.has(job.status),
      );
      if (!hasActive) return false;
      return document.visibilityState === "hidden"
        ? HIDDEN_POLL_INTERVAL_MS
        : POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: true,
    staleTime: 5_000,
  });
}
