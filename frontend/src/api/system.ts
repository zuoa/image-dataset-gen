import { apiRequest } from "./client";
import type { ModelProfile, ProviderInfo } from "../lib/types";

function serializeModelProfile(profile: ModelProfile) {
  return {
    profileType: profile.profileType,
    name: profile.name,
    providerId: profile.providerId,
    baseUrl: profile.baseUrl ?? "",
    model: profile.model,
    apiKey: profile.apiKey,
    concurrency: profile.concurrency,
    batchSize: profile.batchSize,
    jimengWatermark: profile.jimengWatermark,
    notes: profile.notes ?? "",
  };
}

export function getProviders() {
  return apiRequest<{ providers: ProviderInfo[] }>("/system/providers");
}

export function getModelProfiles(token: string) {
  return apiRequest<{ profiles: ModelProfile[] }>("/system/model-profiles", { token });
}

export function createModelProfile(profile: ModelProfile, token: string) {
  return apiRequest<{ profile: ModelProfile }>("/system/model-profiles", {
    method: "POST",
    token,
    body: JSON.stringify(serializeModelProfile(profile)),
  });
}

export function updateModelProfile(profileId: string, profile: ModelProfile, token: string) {
  return apiRequest<{ profile: ModelProfile }>(`/system/model-profiles/${profileId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(serializeModelProfile(profile)),
  });
}

export function deleteModelProfile(profileId: string, token: string) {
  return apiRequest<{ deleted: boolean; id: string }>(`/system/model-profiles/${profileId}`, {
    method: "DELETE",
    token,
  });
}
