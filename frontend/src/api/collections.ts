import { apiRequest } from "./client";
import { generateLocalId } from "../lib/utils";
import type { DatasetCollection } from "../lib/types";

function idempotencyHeaders() {
  return { "Idempotency-Key": generateLocalId("request") };
}

export function listDatasetCollections(token: string) {
  return apiRequest<{ collections: DatasetCollection[] }>("/dataset-collections", { token });
}

export function createDatasetCollection(
  payload: { name: string; description?: string; parentId?: string | null },
  token: string,
) {
  return apiRequest<{ collection: DatasetCollection }>("/dataset-collections", {
    method: "POST",
    token,
    headers: idempotencyHeaders(),
    body: JSON.stringify(payload),
  });
}

export function updateDatasetCollection(
  collectionId: string,
  payload: Partial<{
    name: string;
    description: string;
    parentId: string | null;
    position: number;
  }>,
  token: string,
) {
  return apiRequest<{ collection: DatasetCollection }>(`/dataset-collections/${collectionId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });
}

export function deleteDatasetCollection(collectionId: string, token: string, cascade = false) {
  const query = cascade ? "?cascade=true" : "";
  return apiRequest<{ deletedCollectionId: string; deletedDatasetIds: string[] }>(
    `/dataset-collections/${collectionId}${query}`,
    {
      method: "DELETE",
      token,
    },
  );
}
