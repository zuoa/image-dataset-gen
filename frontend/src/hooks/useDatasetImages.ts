import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getDataset } from "../api/datasets";
import { useAuthStore } from "../store/auth";
import type { ImageFilter } from "../lib/types";

export function useDatasetImages(
  datasetId: string,
  page: number,
  pageSize: number,
  filter?: ImageFilter,
) {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["dataset-images", datasetId, token, filter, page, pageSize],
    queryFn: async () => {
      const response = await getDataset(datasetId, token!, {
        offset: (page - 1) * pageSize,
        limit: pageSize,
        filter,
      });
      return response.dataset;
    },
    placeholderData: keepPreviousData,
    enabled: !!token && !!datasetId,
    staleTime: 10_000,
  });
}
