import { useQuery } from "@tanstack/react-query";

import { getAvailableModels } from "../api/system";
import { useAuthStore } from "../store/auth";

export function providerModelsQueryKey(
  token: string | null,
  profileId: string,
  providerId: string,
) {
  return ["provider-models", token, profileId, providerId] as const;
}

export function useProviderModels(
  profileId: string,
  providerId: string,
  enabled: boolean,
) {
  const token = useAuthStore((state) => state.token);

  return useQuery({
    queryKey: providerModelsQueryKey(token, profileId, providerId),
    queryFn: () => {
      if (!token) throw new Error("Not authenticated");
      return getAvailableModels(profileId, token);
    },
    enabled: enabled && !!token && !!profileId && !!providerId,
    staleTime: 10 * 60_000,
  });
}
