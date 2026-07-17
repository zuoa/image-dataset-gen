import { useQuery } from "@tanstack/react-query";

import { listDatasetQualityRuns } from "../api/datasets";
import { useAuthStore } from "../store/auth";

const POLL_INTERVAL_MS = 4_000;

export function useQualityRuns(datasetId: string) {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["quality-runs", datasetId, token],
    queryFn: () => listDatasetQualityRuns(datasetId, token!),
    enabled: !!token && !!datasetId,
    refetchInterval: (query) => {
      const runs = query.state.data?.qualityRuns ?? [];
      const hasActive = runs.some(
        (run) => run.status === "queued" || run.status === "running",
      );
      return hasActive ? POLL_INTERVAL_MS : false;
    },
    staleTime: 5_000,
  });
}
