import { useQuery } from "@tanstack/react-query";

import { getProviders } from "../api/system";

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: async () => {
      const data = await getProviders();
      return data.providers;
    },
    staleTime: 300_000,
  });
}
