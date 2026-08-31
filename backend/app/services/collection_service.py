from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Dataset, DatasetCollection, generate_uuid

MAX_COLLECTION_DEPTH = 4


class CollectionError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def collection_path_value(collection_id: str, parent: DatasetCollection | None) -> str:
    if parent is None:
        return f"/{collection_id}/"
    return f"{parent.path}{collection_id}/"


def depth_from_path(path: str) -> int:
    return path.strip("/").count("/") + 1


def collections_by_id_for_user(user_id: str) -> dict[str, DatasetCollection]:
    collections = DatasetCollection.query.filter_by(user_id=user_id).all()
    return {collection.id: collection for collection in collections}


def collection_path_payload(
    collection_id: str | None,
    collections_by_id: dict[str, DatasetCollection] | None = None,
    *,
    user_id: str | None = None,
) -> list[dict[str, str]]:
    if not collection_id:
        return []
    if collections_by_id is None:
        if not user_id:
            collection = DatasetCollection.query.filter_by(id=collection_id).first()
            if collection is None:
                return []
            collections_by_id = collections_by_id_for_user(collection.user_id)
        else:
            collections_by_id = collections_by_id_for_user(user_id)
    parts: list[dict[str, str]] = []
    seen: set[str] = set()
    current_id: str | None = collection_id
    while current_id and current_id not in seen:
        seen.add(current_id)
        collection = collections_by_id.get(current_id)
        if collection is None:
            break
        parts.append({"id": collection.id, "name": collection.name})
        current_id = collection.parent_id
    parts.reverse()
    return parts


def dataset_collection_fields(
    dataset: Dataset,
    collections_by_id: dict[str, DatasetCollection] | None = None,
) -> dict[str, Any]:
    return {
        "collectionId": dataset.collection_id,
        "collectionPath": collection_path_payload(
            dataset.collection_id,
            collections_by_id,
            user_id=dataset.user_id,
        ),
    }


def get_collection_for_user(collection_id: str, user_id: str) -> DatasetCollection:
    return DatasetCollection.query.filter_by(id=collection_id, user_id=user_id).first_or_404()


def resolve_collection_id(collection_id: str | None, user_id: str) -> str | None:
    if collection_id is None or collection_id == "":
        return None
    get_collection_for_user(collection_id, user_id)
    return collection_id


def _sibling_query(user_id: str, parent_id: str | None, exclude_id: str | None = None):
    query = DatasetCollection.query.filter_by(user_id=user_id, parent_id=parent_id)
    if exclude_id:
        query = query.filter(DatasetCollection.id != exclude_id)
    return query


def _ensure_unique_sibling_name(
    user_id: str,
    parent_id: str | None,
    name: str,
    *,
    exclude_id: str | None = None,
) -> None:
    existing = _sibling_query(user_id, parent_id, exclude_id).filter_by(name=name).first()
    if existing is not None:
        raise CollectionError("同一位置已有同名分组。", 409)


def _next_sibling_position(user_id: str, parent_id: str | None) -> int:
    current_max = (
        db.session.query(func.max(DatasetCollection.position))
        .filter_by(user_id=user_id, parent_id=parent_id)
        .scalar()
    )
    return int(current_max or -1) + 1


def _descendant_collections(collection: DatasetCollection) -> list[DatasetCollection]:
    return (
        DatasetCollection.query.filter(
            DatasetCollection.user_id == collection.user_id,
            DatasetCollection.path.startswith(collection.path),
            DatasetCollection.id != collection.id,
        )
        .order_by(DatasetCollection.depth.desc(), DatasetCollection.path.desc())
        .all()
    )


def _datasets_in_collections(user_id: str, collection_ids: list[str]) -> list[Dataset]:
    if not collection_ids:
        return []
    return Dataset.query.filter(
        Dataset.user_id == user_id,
        Dataset.collection_id.in_(collection_ids),
    ).all()


def create_collection(
    user_id: str,
    *,
    name: str,
    description: str = "",
    parent_id: str | None = None,
) -> DatasetCollection:
    parent = get_collection_for_user(parent_id, user_id) if parent_id else None
    depth = 1 if parent is None else parent.depth + 1
    if depth > MAX_COLLECTION_DEPTH:
        raise CollectionError(f"分组深度不能超过 {MAX_COLLECTION_DEPTH} 层。", 400)
    normalized_name = name.strip()
    _ensure_unique_sibling_name(user_id, parent.id if parent else None, normalized_name)

    collection_id = generate_uuid()
    collection = DatasetCollection(
        id=collection_id,
        user_id=user_id,
        parent_id=parent.id if parent else None,
        name=normalized_name,
        description=(description or "").strip(),
        path=collection_path_value(collection_id, parent),
        depth=depth,
        position=_next_sibling_position(user_id, parent.id if parent else None),
    )
    db.session.add(collection)
    try:
        db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        raise CollectionError("同一位置已有同名分组。", 409) from exc
    return collection


def update_collection(
    collection: DatasetCollection,
    *,
    name: str | None = None,
    description: str | None = None,
    parent_id: str | None | object = None,
    position: int | None = None,
    parent_id_provided: bool = False,
) -> DatasetCollection:
    next_name = collection.name if name is None else name.strip()
    if not next_name:
        raise CollectionError("分组名称不能为空。", 400)

    next_parent = collection.parent
    if parent_id_provided:
        if parent_id:
            if parent_id == collection.id:
                raise CollectionError("不能将分组移动到自己下面。", 400)
            next_parent = get_collection_for_user(str(parent_id), collection.user_id)
            if next_parent.path.startswith(collection.path):
                raise CollectionError("不能将分组移动到自己的子分组下。", 400)
        else:
            next_parent = None

    next_parent_id = next_parent.id if next_parent else None
    parent_changed = next_parent_id != collection.parent_id
    if parent_changed or next_name != collection.name:
        _ensure_unique_sibling_name(
            collection.user_id,
            next_parent_id,
            next_name,
            exclude_id=collection.id,
        )

    if parent_changed:
        new_path = collection_path_value(collection.id, next_parent)
        new_depth = depth_from_path(new_path)
        depth_delta = new_depth - collection.depth
        descendants = _descendant_collections(collection)
        for descendant in descendants:
            if descendant.depth + depth_delta > MAX_COLLECTION_DEPTH:
                raise CollectionError(f"分组深度不能超过 {MAX_COLLECTION_DEPTH} 层。", 400)
        old_prefix = collection.path
        collection.parent_id = next_parent_id
        collection.path = new_path
        collection.depth = new_depth
        collection.position = _next_sibling_position(collection.user_id, next_parent_id)
        for descendant in descendants:
            descendant.path = new_path + descendant.path[len(old_prefix) :]
            descendant.depth = descendant.depth + depth_delta

    collection.name = next_name
    if description is not None:
        collection.description = description.strip()
    if position is not None and not parent_changed:
        collection.position = max(0, int(position))

    try:
        db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        raise CollectionError("同一位置已有同名分组。", 409) from exc
    return collection


def collection_is_empty(collection: DatasetCollection) -> bool:
    has_child = (
        DatasetCollection.query.filter_by(parent_id=collection.id).limit(1).first() is not None
    )
    if has_child:
        return False
    has_dataset = Dataset.query.filter_by(collection_id=collection.id).limit(1).first() is not None
    return not has_dataset


def collections_and_datasets_for_delete(
    collection: DatasetCollection,
) -> tuple[list[DatasetCollection], list[Dataset]]:
    descendants = _descendant_collections(collection)
    all_collections = [collection, *descendants]
    datasets = _datasets_in_collections(collection.user_id, [item.id for item in all_collections])
    return all_collections, datasets


def delete_collection_rows(collections: list[DatasetCollection]) -> None:
    for collection in sorted(collections, key=lambda item: item.depth, reverse=True):
        db.session.delete(collection)


def aggregate_collection_stats(
    collections: list[DatasetCollection],
    datasets: list[Any],
) -> dict[str, dict[str, int | float]]:
    stats = {
        collection.id: {
            "datasetCount": 0,
            "imageCount": 0,
            "spentCost": 0.0,
            "directDatasetCount": 0,
            "childCollectionCount": 0,
        }
        for collection in collections
    }
    by_id = {collection.id: collection for collection in collections}
    for collection in collections:
        if collection.parent_id and collection.parent_id in stats:
            stats[collection.parent_id]["childCollectionCount"] += 1

    for dataset in datasets:
        collection_id = dataset.collection_id
        if not collection_id or collection_id not in by_id:
            continue
        if collection_id in stats:
            stats[collection_id]["directDatasetCount"] += 1
        current_id: str | None = collection_id
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            if current_id in stats:
                stats[current_id]["datasetCount"] += 1
                stats[current_id]["imageCount"] += int(dataset.image_count or 0)
                stats[current_id]["spentCost"] = round(
                    float(stats[current_id]["spentCost"]) + float(dataset.spent_cost or 0.0),
                    4,
                )
            parent = by_id.get(current_id)
            current_id = parent.parent_id if parent else None
    return stats


def build_collection_payload(
    collection: DatasetCollection,
    stats: dict[str, int | float] | None = None,
) -> dict[str, Any]:
    payload_stats = stats or {
        "datasetCount": 0,
        "imageCount": 0,
        "spentCost": 0.0,
        "directDatasetCount": 0,
        "childCollectionCount": 0,
    }
    return {
        "id": collection.id,
        "parentId": collection.parent_id,
        "name": collection.name,
        "description": collection.description,
        "path": collection.path,
        "depth": int(collection.depth or 1),
        "position": int(collection.position or 0),
        "stats": {
            "datasetCount": int(payload_stats["datasetCount"]),
            "imageCount": int(payload_stats["imageCount"]),
            "spentCost": float(payload_stats["spentCost"]),
            "directDatasetCount": int(payload_stats["directDatasetCount"]),
            "childCollectionCount": int(payload_stats["childCollectionCount"]),
        },
        "createdAt": collection.created_at.isoformat() if collection.created_at else None,
        "updatedAt": collection.updated_at.isoformat() if collection.updated_at else None,
    }


def list_collection_payloads_for_user(user_id: str) -> list[dict[str, Any]]:
    collections = (
        DatasetCollection.query.filter_by(user_id=user_id)
        .order_by(DatasetCollection.depth.asc(), DatasetCollection.position.asc(), DatasetCollection.name.asc())
        .all()
    )
    datasets = (
        Dataset.query.filter_by(user_id=user_id)
        .with_entities(
            Dataset.id,
            Dataset.collection_id,
            Dataset.image_count,
            Dataset.spent_cost,
        )
        .all()
    )
    dataset_rows = [
        SimpleNamespace(
            collection_id=row.collection_id,
            image_count=row.image_count,
            spent_cost=row.spent_cost,
        )
        for row in datasets
    ]
    stats = aggregate_collection_stats(collections, dataset_rows)
    return [build_collection_payload(collection, stats.get(collection.id)) for collection in collections]
