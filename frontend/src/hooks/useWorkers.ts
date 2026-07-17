import { useQuery } from "@tanstack/react-query";

import { listTrainingWorkers } from "../api/training";
import { useAuthStore } from "../store/auth";

export function useWorkers() {
  const token = useAuthStore((state) => state.token);
  return useQuery({
    queryKey: ["training-workers", token],
    queryFn: ({ signal }) => listTrainingWorkers(token!, signal),
    enabled: !!token,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    staleTime: 5_000,
  });
}
