from pathlib import Path

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import DatasetTask


def _auth_headers(client, username: str = "collection-user") -> dict[str, str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "Dataset123!"},
    )
    token = register.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _create_collection(client, headers: dict[str, str], name: str, parent_id: str | None = None) -> dict:
    payload = {"name": name, "description": f"{name} grouping"}
    if parent_id:
        payload["parentId"] = parent_id
    response = client.post("/api/v1/dataset-collections", headers=headers, json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["collection"]


def _create_dataset(
    client,
    headers: dict[str, str],
    name: str = "safety helmet dataset",
    collection_id: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "categories": ["helmet", "no_helmet"],
        "description": "leaf dataset",
    }
    if collection_id:
        payload["collectionId"] = collection_id
    response = client.post("/api/v1/datasets", headers=headers, json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["dataset"]


def test_collection_tree_create_list_and_dataset_path(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client)

    root = _create_collection(client, headers, "安全生产")
    child = _create_collection(client, headers, "人员劳动防护", root["id"])
    dataset = _create_dataset(client, headers, "安全帽", child["id"])

    assert root["parentId"] is None
    assert root["depth"] == 1
    assert child["parentId"] == root["id"]
    assert child["depth"] == 2
    assert dataset["collectionId"] == child["id"]
    assert [item["name"] for item in dataset["collectionPath"]] == ["安全生产", "人员劳动防护"]

    listed = client.get("/api/v1/datasets", headers=headers).get_json()
    assert listed["summary"]["totalCollections"] == 2
    assert {item["name"] for item in listed["collections"]} == {"安全生产", "人员劳动防护"}
    listed_dataset = next(item for item in listed["datasets"] if item["id"] == dataset["id"])
    assert listed_dataset["collectionId"] == child["id"]
    root_stats = next(item for item in listed["collections"] if item["id"] == root["id"])
    assert root_stats["stats"]["datasetCount"] == 1
    assert root_stats["stats"]["childCollectionCount"] == 1
    child_stats = next(item for item in listed["collections"] if item["id"] == child["id"])
    assert child_stats["stats"]["directDatasetCount"] == 1


def test_collection_rejects_duplicate_sibling_name_and_cycles(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client)

    root = _create_collection(client, headers, "安全生产")
    duplicate = client.post(
        "/api/v1/dataset-collections",
        headers=headers,
        json={"name": "安全生产"},
    )
    assert duplicate.status_code == 409

    child = _create_collection(client, headers, "人员劳动防护", root["id"])
    grandchild = _create_collection(client, headers, "现场作业", child["id"])

    cycle = client.patch(
        f"/api/v1/dataset-collections/{root['id']}",
        headers=headers,
        json={"parentId": grandchild["id"]},
    )
    assert cycle.status_code == 400
    assert "子分组" in cycle.get_json()["message"]

    self_move = client.patch(
        f"/api/v1/dataset-collections/{root['id']}",
        headers=headers,
        json={"parentId": root["id"]},
    )
    assert self_move.status_code == 400


def test_collection_depth_limit(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "depth-user")

    parent_id = None
    for index in range(4):
        collection = _create_collection(client, headers, f"level-{index + 1}", parent_id)
        parent_id = collection["id"]
        assert collection["depth"] == index + 1

    overflow = client.post(
        "/api/v1/dataset-collections",
        headers=headers,
        json={"name": "level-5", "parentId": parent_id},
    )
    assert overflow.status_code == 400
    assert "4 层" in overflow.get_json()["message"]


def test_collection_move_rewrites_descendant_paths(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "move-user")

    safety = _create_collection(client, headers, "安全生产")
    ppe = _create_collection(client, headers, "人员劳动防护", safety["id"])
    driver = _create_collection(client, headers, "驾驶员不安全行为", safety["id"])
    _create_dataset(client, headers, "安全帽", ppe["id"])

    moved = client.patch(
        f"/api/v1/dataset-collections/{ppe['id']}",
        headers=headers,
        json={"parentId": driver["id"]},
    )
    assert moved.status_code == 200
    payload = moved.get_json()["collection"]
    assert payload["parentId"] == driver["id"]
    assert payload["depth"] == 3
    assert payload["path"].startswith(f"/{safety['id']}/{driver['id']}/{ppe['id']}/")

    dataset = client.get("/api/v1/datasets", headers=headers).get_json()["datasets"][0]
    assert [item["name"] for item in dataset["collectionPath"]] == [
        "安全生产",
        "驾驶员不安全行为",
        "人员劳动防护",
    ]


def test_delete_collection_requires_cascade_when_not_empty(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "delete-user")

    root = _create_collection(client, headers, "安全生产")
    child = _create_collection(client, headers, "人员劳动防护", root["id"])
    dataset = _create_dataset(client, headers, "安全帽", child["id"])

    blocked = client.delete(f"/api/v1/dataset-collections/{root['id']}", headers=headers)
    assert blocked.status_code == 409

    cascaded = client.delete(
        f"/api/v1/dataset-collections/{root['id']}?cascade=true",
        headers=headers,
    )
    assert cascaded.status_code == 200
    body = cascaded.get_json()
    assert body["deletedCollectionId"] == root["id"]
    assert dataset["id"] in body["deletedDatasetIds"]

    listed = client.get("/api/v1/datasets", headers=headers).get_json()
    assert listed["datasets"] == []
    assert listed["collections"] == []


def test_delete_collection_cascade_blocked_by_active_dataset_work(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "active-work-user")

    root = _create_collection(client, headers, "安全生产")
    dataset = _create_dataset(client, headers, "安全帽", root["id"])

    with app.app_context():
        from app.models import Dataset

        db_dataset = db.session.get(Dataset, dataset["id"])
        assert db_dataset is not None
        db.session.add(
            DatasetTask(
                dataset_id=db_dataset.id,
                user_id=db_dataset.user_id,
                task_type="generation",
                task_name="running generation",
                subject="helmet",
                categories=["helmet"],
                image_count=1,
                status="running",
            )
        )
        db.session.commit()

    blocked = client.delete(
        f"/api/v1/dataset-collections/{root['id']}?cascade=true",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert "运行中" in blocked.get_json()["message"]

    listed = client.get("/api/v1/datasets", headers=headers).get_json()
    assert len(listed["datasets"]) == 1
    assert len(listed["collections"]) == 1


def test_patch_dataset_collection_does_not_clear_categories(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "patch-user")

    collection = _create_collection(client, headers, "安全生产")
    dataset = _create_dataset(client, headers, "安全帽")
    assert dataset["collectionId"] is None

    updated = client.patch(
        f"/api/v1/datasets/{dataset['id']}",
        headers=headers,
        json={"collectionId": collection["id"]},
    )
    assert updated.status_code == 200
    payload = updated.get_json()["dataset"]
    assert payload["collectionId"] == collection["id"]
    assert payload["categories"] == ["helmet", "no_helmet"]

    ungrouped = client.patch(
        f"/api/v1/datasets/{dataset['id']}",
        headers=headers,
        json={"collectionId": None},
    )
    assert ungrouped.status_code == 200
    assert ungrouped.get_json()["dataset"]["collectionId"] is None
    assert ungrouped.get_json()["dataset"]["categories"] == ["helmet", "no_helmet"]


def test_collection_is_hidden_from_other_users(tmp_path: Path):
    class CollectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(CollectionConfig)
    client = app.test_client()
    owner = _auth_headers(client, "owner-user")
    other = _auth_headers(client, "other-user")

    collection = _create_collection(client, owner, "安全生产")
    hidden = client.get(f"/api/v1/dataset-collections/{collection['id']}", headers=other)
    assert hidden.status_code == 404

    moved = client.patch(
        f"/api/v1/dataset-collections/{collection['id']}",
        headers=other,
        json={"name": "stolen"},
    )
    assert moved.status_code == 404

    created = client.post(
        "/api/v1/datasets",
        headers=other,
        json={
            "name": "other helmet dataset",
            "categories": ["helmet"],
            "collectionId": collection["id"],
        },
    )
    assert created.status_code == 404
