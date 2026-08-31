from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db
from app.schemas import DatasetCollectionSchema, DatasetCollectionUpdateSchema
from app.services.collection_service import (
    CollectionError,
    build_collection_payload,
    collection_is_empty,
    collections_and_datasets_for_delete,
    create_collection,
    delete_collection_rows,
    get_collection_for_user,
    list_collection_payloads_for_user,
    update_collection,
)
from app.api.datasets import _begin_idempotency, _dataset_has_active_work, purge_dataset_row
from app.services.idempotency_service import complete_idempotent_request

collections_bp = Blueprint("dataset_collections", __name__)


def _collection_payload_with_stats(user_id: str, collection_id: str) -> dict:
    for payload in list_collection_payloads_for_user(user_id):
        if payload["id"] == collection_id:
            return payload
    collection = get_collection_for_user(collection_id, user_id)
    return build_collection_payload(collection)


@collections_bp.errorhandler(CollectionError)
def handle_collection_error(error: CollectionError):
    return jsonify({"message": str(error)}), error.status_code


@collections_bp.get("")
@jwt_required()
def list_collections():
    user_id = get_jwt_identity()
    return jsonify({"collections": list_collection_payloads_for_user(user_id)})


@collections_bp.get("/<collection_id>")
@jwt_required()
def get_dataset_collection(collection_id: str):
    user_id = get_jwt_identity()
    get_collection_for_user(collection_id, user_id)
    return jsonify({"collection": _collection_payload_with_stats(user_id, collection_id)})


@collections_bp.post("")
@jwt_required()
def create_dataset_collection():
    user_id = get_jwt_identity()
    payload = DatasetCollectionSchema().load(request.get_json() or {})
    idempotency, replay_response = _begin_idempotency(user_id, "collections.create", payload)
    if replay_response is not None:
        return replay_response
    collection = create_collection(
        user_id,
        name=payload["name"],
        description=payload.get("description") or "",
        parent_id=payload.get("parentId"),
    )
    payload_body = {"collection": _collection_payload_with_stats(user_id, collection.id)}
    complete_idempotent_request(idempotency, payload_body, 201)
    db.session.commit()
    return jsonify(payload_body), 201


@collections_bp.patch("/<collection_id>")
@jwt_required()
def patch_dataset_collection(collection_id: str):
    user_id = get_jwt_identity()
    payload = DatasetCollectionUpdateSchema().load(request.get_json() or {})
    collection = get_collection_for_user(collection_id, user_id)
    collection = update_collection(
        collection,
        name=payload.get("name"),
        description=payload.get("description") if "description" in payload else None,
        parent_id=payload.get("parentId"),
        position=payload.get("position"),
        parent_id_provided="parentId" in payload,
    )
    db.session.commit()
    return jsonify({"collection": _collection_payload_with_stats(user_id, collection.id)})


@collections_bp.delete("/<collection_id>")
@jwt_required()
def delete_dataset_collection(collection_id: str):
    user_id = get_jwt_identity()
    collection = get_collection_for_user(collection_id, user_id)
    cascade = str(request.args.get("cascade") or "").strip().lower() in {"1", "true", "yes"}
    collections, datasets = collections_and_datasets_for_delete(collection)
    if not cascade and not collection_is_empty(collection):
        return jsonify({"message": "分组下还有子分组或数据集，请先移出或使用级联删除。"}), 409

    for dataset in datasets:
        if _dataset_has_active_work(dataset):
            return jsonify({"message": "分组内仍有运行中或排队中的任务，请等待任务结束后再删除。"}), 409

    deleted_dataset_ids = [dataset.id for dataset in datasets]
    for dataset in datasets:
        purge_dataset_row(dataset)
    delete_collection_rows(collections)
    db.session.commit()
    return jsonify(
        {
            "deletedCollectionId": collection_id,
            "deletedDatasetIds": deleted_dataset_ids,
        }
    )
