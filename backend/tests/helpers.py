from __future__ import annotations

import time
from typing import Any


def wait_for_task(
    client: Any,
    task_id: str,
    headers: dict[str, str],
    *,
    timeout: float = 3.0,
    interval: float = 0.05,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_task: dict[str, Any] | None = None

    while time.time() < deadline:
        response = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        last_task = response.get_json()["task"]
        if last_task["status"] in {"completed", "paused"} or last_task["imagesGenerated"] > 0:
            return last_task
        time.sleep(interval)

    if last_task is None:
        raise AssertionError("task polling did not return a payload")
    return last_task
