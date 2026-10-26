"""Dashboard aggregates: cards, charts and the recent violations table.

Aggregation is done in Python (not with MongoDB pipelines) so the behaviour is
identical on real MongoDB and on the bundled local store.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from ..constants import (
    MODE_DEMO,
    MODE_LIVE,
    STATUS_ONLINE,
    VIOLATION_LABELS,
    VIOLATION_PENDING,
    VIOLATION_TYPES,
)
from ..database import ALERTS, CAMERAS, VIOLATIONS, coll
from ..deps import get_current_user
from ..services.camera_manager import camera_manager
from ..services.pipeline import pipeline
from ..utils import day_key, day_start_iso, iso, serialize_many, utcnow

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary")
async def summary(
    days: int = Query(default=7, ge=1, le=30),
    _: dict = Depends(get_current_user),
) -> dict:
    cameras = await coll(CAMERAS).find({}).to_list(200)
    # Cap the scan so the dashboard stays responsive as records grow.
    violations = (
        await coll(VIOLATIONS)
        .find({})
        .sort("detected_at", -1)
        .limit(800)
        .to_list(800)
    )
    open_alerts = await coll(ALERTS).count_documents({"status": "OPEN"})

    live_health = {item["camera_id"]: item for item in camera_manager.health_all()}
    active = sum(
        1
        for camera in cameras
        if camera.get("enabled", True)
        and live_health.get(str(camera.get("camera_id")), {}).get("status") == STATUS_ONLINE
    )
    enabled = sum(1 for camera in cameras if camera.get("enabled", True))

    today = day_start_iso()
    today_violations = [item for item in violations if (item.get("detected_at") or "") >= today]

    by_type = {code: 0 for code in VIOLATION_TYPES}
    for item in violations:
        code = item.get("violation_type", "")
        by_type[code] = by_type.get(code, 0) + 1

    day_labels: list[str] = []
    for offset in range(days - 1, -1, -1):
        day_labels.append(iso(utcnow() - timedelta(days=offset))[:10])

    daily = {
        label: {"date": label, "challans": 0, "violations": 0, "amount": 0.0}
        for label in day_labels
    }
    for item in violations:
        key = day_key(item.get("detected_at"))
        if key in daily:
            daily[key]["violations"] += 1

    camera_activity = []
    for camera in sorted(cameras, key=lambda item: str(item.get("camera_id"))):
        camera_id = str(camera.get("camera_id"))
        health = live_health.get(camera_id, {})
        camera_activity.append(
            {
                "camera_id": camera_id,
                "name": camera.get("name", ""),
                "violations": sum(
                    1 for item in violations if item.get("camera_id") == camera_id
                ),
                "today": sum(
                    1 for item in today_violations if item.get("camera_id") == camera_id
                ),
                "status": health.get("status") or camera.get("status") or "OFFLINE",
                "fps": health.get("fps", 0),
                "mode": camera.get("mode", MODE_DEMO),
            }
        )

    recent = violations[:10]

    return {
        "cards": {
            "total_cameras": len(cameras),
            "active_cameras": active,
            "offline_cameras": max(enabled - active, 0),
            "todays_violations": len(today_violations),
            "total_challans": 0,
            "pending_challans": 0,
            "paid_challans": 0,
            "total_fine_amount": 0,
            "collected_amount": 0,
            "pending_amount": 0,
            "pending_review": sum(
                1 for item in violations if item.get("status") == VIOLATION_PENDING
            ),
            "open_alerts": open_alerts,
            "registered_vehicles": 0,
        },
        "charts": {
            "violations_by_type": [
                {
                    "code": code,
                    "label": VIOLATION_LABELS.get(code, code),
                    "count": count,
                }
                for code, count in by_type.items()
            ],
            "daily": list(daily.values()),
            "payment_status": [],
            "camera_activity": camera_activity,
        },
        "recent_violations": serialize_many(recent),
        "camera_modes": {
            "live": sum(1 for camera in cameras if camera.get("mode") == MODE_LIVE),
            "demo": sum(1 for camera in cameras if camera.get("mode") == MODE_DEMO),
        },
        "pipeline": pipeline.status(),
        "generated_at": iso(utcnow()),
    }
