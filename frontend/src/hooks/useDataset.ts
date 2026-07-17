import { useQuery } from "@tanstack/react-query";

import { getDataset } from "../api/datasets";
import { useAuthStore } from "../store/auth";

export function useDataset(datasetId: string) {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["dataset", datasetId, token],
    queryFn: () => getDataset(datasetId, token!, { limit: 0 }),
    enabled: !!token && !!datasetId,
    staleTime: 10_000,
  });
}
