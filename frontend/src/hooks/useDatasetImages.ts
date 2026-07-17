import { useInfiniteQuery } from "@tanstack/react-query";

import { getDataset } from "../api/datasets";
import { useAuthStore } from "../store/auth";
import type { ImageFilter } from "../lib/types";

const PAGE_SIZE = 100;

type PageParam = { cursor?: string; offset?: number };

export function useDatasetImages(datasetId: string, filter?: ImageFilter) {
  const token = useAuthStore((state) => state.token);
  return useInfiniteQuery({
    queryKey: ["dataset-images", datasetId, token, filter],
    queryFn: async ({ pageParam }) => {
      const response = await getDataset(datasetId, token!, {
        cursor: pageParam?.cursor,
        offset: pageParam?.cursor ? undefined : pageParam?.offset ?? 0,
        limit: PAGE_SIZE,
        filter,
      });
      return response.dataset;
    },
    getNextPageParam: (lastPage): PageParam | undefined => {
      if (!lastPage.imagesNextCursor) return undefined;
      return { cursor: lastPage.imagesNextCursor };
    },
    initialPageParam: { offset: 0 } as PageParam,
    enabled: !!token && !!datasetId,
    staleTime: 10_000,
  });
}
