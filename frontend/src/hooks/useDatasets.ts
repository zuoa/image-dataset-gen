import { useQuery } from "@tanstack/react-query";

import { listDatasets } from "../api/datasets";
import { useAuthStore } from "../store/auth";

export function useDatasets() {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["datasets", token],
    queryFn: () => listDatasets(token!),
    enabled: !!token,
    staleTime: 10_000,
  });
}
