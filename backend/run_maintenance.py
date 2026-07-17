from __future__ import annotations

import time

from app import create_app
from app.services.asset_gc_service import garbage_collect_deleted_assets, garbage_collect_expired_records


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        while True:
            try:
                purged = garbage_collect_deleted_assets(
                    app.config["STORAGE_ROOT"],
                    retention_hours=int(app.config["ASSET_GC_RETENTION_HOURS"]),
                )
                expired = garbage_collect_expired_records()
                app.logger.info(
                    "maintenance complete",
                    extra={"purged_assets": purged, "purged_expired_records": expired},
                )
            except Exception:
                app.logger.exception("asset garbage collection failed")
            time.sleep(3600)
