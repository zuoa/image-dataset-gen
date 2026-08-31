import type { DatasetCollection, DatasetListItem } from "./types";

export function collectionsById(collections: DatasetCollection[]) {
  return new Map(collections.map((collection) => [collection.id, collection]));
}

export function childCollections(collections: DatasetCollection[], parentId: string | null) {
  return collections
    .filter((collection) => (collection.parentId ?? null) === parentId)
    .slice()
    .sort((left, right) => left.position - right.position || left.name.localeCompare(right.name, "zh-CN"));
}

export function datasetsInCollection(datasets: DatasetListItem[], collectionId: string | null) {
  return datasets.filter((dataset) => (dataset.collectionId ?? null) === collectionId);
}

export function collectionBreadcrumb(
  collections: DatasetCollection[],
  collectionId: string | null,
): DatasetCollection[] {
  if (!collectionId) return [];
  const byId = collectionsById(collections);
  const parts: DatasetCollection[] = [];
  const seen = new Set<string>();
  let current = byId.get(collectionId);
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    parts.unshift(current);
    current = current.parentId ? byId.get(current.parentId) : undefined;
  }
  return parts;
}

export function descendantCollectionIds(collections: DatasetCollection[], collectionId: string) {
  const ids = new Set<string>([collectionId]);
  let added = true;
  while (added) {
    added = false;
    for (const collection of collections) {
      if (collection.parentId && ids.has(collection.parentId) && !ids.has(collection.id)) {
        ids.add(collection.id);
        added = true;
      }
    }
  }
  return ids;
}

export function collectionPathLabel(collection: DatasetCollection | null | undefined, collections: DatasetCollection[]) {
  if (!collection) return "未分组";
  return collectionBreadcrumb(collections, collection.id)
    .map((item) => item.name)
    .join(" / ");
}
