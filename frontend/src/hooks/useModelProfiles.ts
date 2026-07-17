import { useQuery } from "@tanstack/react-query";

import { useAuthStore } from "../store/auth";
import { useModelProfilesStore } from "../store/modelProfiles";

export function useModelProfiles() {
  const token = useAuthStore((state) => state.token);
  const profiles = useModelProfilesStore((state) => state.profiles);
  const isLoaded = useModelProfilesStore((state) => state.isLoaded);
  const fetchProfiles = useModelProfilesStore((state) => state.fetchProfiles);

  return useQuery({
    queryKey: ["model-profiles", token],
    queryFn: async () => {
      if (!token) throw new Error("Not authenticated");
      await fetchProfiles(token);
      return useModelProfilesStore.getState().profiles;
    },
    enabled: !!token,
    staleTime: 60_000,
    initialData: isLoaded ? profiles : undefined,
  });
}
