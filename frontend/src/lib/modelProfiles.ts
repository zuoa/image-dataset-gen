import { defaultModelProfiles } from "./constants";
import type { ModelProfile, ProviderId, TaskConfig } from "./types";

export function getFallbackModelProfile(profileType: ModelProfile["profileType"] = "image"): ModelProfile {
  return (
    defaultModelProfiles.find((profile) => profile.profileType === profileType) ??
    defaultModelProfiles[0]
  );
}

export function filterModelProfilesByType(
  profiles: ModelProfile[],
  profileType: ModelProfile["profileType"],
) {
  return profiles.filter((profile) => profile.profileType === profileType);
}

export function buildTaskConfigFromProfile(
  profile: ModelProfile,
  current?: Pick<TaskConfig, "format" | "jimeng_watermark">,
): Partial<TaskConfig> {
  if (profile.profileType !== "image") {
    return {
      llm_profile_id: profile.id,
    };
  }

  const nextFormat = profile.providerId === "jimeng" ? "jpg" : (current?.format ?? "jpg");

  return {
    model_profile_id: profile.id,
    api_provider: profile.providerId as ProviderId,
    provider_model: profile.model,
    api_key: profile.apiKey,
    concurrency: profile.concurrency,
    batch_size: profile.batchSize,
    jimeng_watermark: profile.providerId === "jimeng"
      ? profile.jimengWatermark
      : (current?.jimeng_watermark ?? true),
    format: nextFormat,
  };
}

export function resolveModelProfile(
  profiles: ModelProfile[],
  config: Pick<TaskConfig, "model_profile_id" | "api_provider" | "provider_model">,
): ModelProfile | null {
  const imageProfiles = filterModelProfilesByType(profiles, "image");
  if (imageProfiles.length === 0) return null;

  if (config.model_profile_id) {
    const matched = imageProfiles.find((profile) => profile.id === config.model_profile_id);
    if (matched) return matched;
  }

  return (
    imageProfiles.find(
      (profile) =>
        profile.providerId === config.api_provider &&
        profile.model === (config.provider_model ?? ""),
    ) ?? null
  );
}

export function resolveLlmProfile(
  profiles: ModelProfile[],
  llmProfileId?: string,
): ModelProfile | null {
  const llmProfiles = filterModelProfilesByType(profiles, "llm");
  if (llmProfiles.length === 0) return null;

  if (llmProfileId) {
    const matched = llmProfiles.find((profile) => profile.id === llmProfileId);
    if (matched) return matched;
  }

  return llmProfiles[0];
}
