"""First-run bootstrap: demo users, three demo cameras, rules and sample vehicles.

This runs automatically at startup but only creates what is missing, so it is
safe on every restart. ``backend/seed.py`` calls the same helpers and can also
generate sample violations/challans for a demo run.
"""

from __future__ import annotations

import logging

from .constants import (
    MODE_DEMO,
    MODE_LIVE,
    ROLE_ADMIN,
    ROLE_OFFICER,
    STATUS_CONNECTING,
    STATUS_DISABLED,
)
from .database import CAMERAS, USERS, VEHICLES, coll
from .security import hash_password
from .services.rules_service import ensure_rules
from .utils import utcnow_iso

logger = logging.getLogger("rto.bootstrap")

DEMO_USERS = [
    {
        "user_id": "ADMIN001",
        "password": "Admin@123",
        "name": "R. Krishnan",
        "role": ROLE_ADMIN,
        "designation": "RTO Administrator",
        "phone": "9000000001",
        "email": "admin@rto.gov.in",
        "station": "RTO Head Office",
    },
    {
        "user_id": "OFFICER001",
        "password": "Officer@123",
        "name": "S. Meena",
        "role": ROLE_OFFICER,
        "designation": "Traffic Sub-Inspector",
        "phone": "9000000002",
        "email": "officer1@rto.gov.in",
        "station": "City Traffic Police Station",
    },
    {
        "user_id": "OFFICER002",
        "password": "Officer@123",
        "name": "A. Devaraj",
        "role": ROLE_OFFICER,
        "designation": "Traffic Constable",
        "phone": "9000000003",
        "email": "officer2@rto.gov.in",
        "station": "Highway Patrol Unit",
    },
]

DEMO_CAMERAS = [
    {
        "camera_id": "CAM-01",
        "name": "Camera 1",
        "ip_address": "",
        "rtsp_url": "",
        "username": "",
        "password": "",
        "mode": MODE_DEMO,
        "demo_source_type": "SYNTHETIC",
        "location": "MG Road Junction - South Approach",
        "description": "Animated traffic demo scene for Camera 1",
        "allowed_direction": "ANY",
    },
    {
        "camera_id": "CAM-02",
        "name": "Camera 2",
        "ip_address": "",
        "rtsp_url": "",
        "username": "",
        "password": "",
        "mode": MODE_DEMO,
        "demo_source_type": "SYNTHETIC",
        "location": "Ring Road Flyover - Service Lane",
        "description": "Service lane frequently used for wrong side driving.",
        "allowed_direction": "RIGHT_TO_LEFT",
    },
    {
        "camera_id": "CAM-03",
        "name": "Camera 3",
        "ip_address": "192.168.1.103",
        "rtsp_url": "rtsp://192.168.1.103:554/stream",
        "username": "",
        "password": "",
        "location": "Market Street - Bus Stand Entry",
        "description": "High two-wheeler density, helmet and triple riding checks.",
        "allowed_direction": "ANY",
    },
]

RTO_VEHICLES = [
    {
        "plate_number": "MH29AY4115",
        "owner_name": "Om R. Burade",
        "owner_phone": "9067816121",
        "owner_address": "",
        "vehicle_type": "Two Wheeler",
        "make_model": "",
        "colour": "",
    },
    {
        "plate_number": "MH29CE7640",
        "owner_name": "Nivedita Ingole",
        "owner_phone": "9370077413",
        "owner_address": "",
        "vehicle_type": "Two Wheeler",
        "make_model": "",
        "colour": "",
    },
    {
        "plate_number": "MH32N9156",
        "owner_name": "Siddhi Y. Rathod",
        "owner_phone": "7843087959",
        "owner_address": "",
        "vehicle_type": "Two Wheeler",
        "make_model": "",
        "colour": "",
    },
]

DEMO_VEHICLES = [
    {
        "plate_number": "KA05MJ2020",
        "owner_name": "Vinod Kumar",
        "owner_phone": "9000000011",
        "owner_address": "12, 4th Cross, Jayanagar",
        "vehicle_type": "Two Wheeler",
        "make_model": "Honda Activa 6G",
        "colour": "Grey",
    },
    {
        "plate_number": "TN09BX7788",
        "owner_name": "Lakshmi Narayanan",
        "owner_phone": "9000000012",
        "owner_address": "45, Anna Nagar East",
        "vehicle_type": "Two Wheeler",
        "make_model": "TVS Jupiter",
        "colour": "Blue",
    },
    {
        "plate_number": "MH12KL4521",
        "owner_name": "Sameer Patil",
        "owner_phone": "9000000013",
        "owner_address": "7, Kothrud, Pune",
        "vehicle_type": "Two Wheeler",
        "make_model": "Bajaj Pulsar 150",
        "colour": "Black",
    },
]


async def create_demo_users() -> int:
    created = 0
    for entry in DEMO_USERS:
        if await coll(USERS).find_one({"user_id": entry["user_id"]}):
            continue
        await coll(USERS).insert_one(
            {
                "user_id": entry["user_id"],
                "name": entry["name"],
                "role": entry["role"],
                "designation": entry["designation"],
                "phone": entry["phone"],
                "email": entry["email"],
                "station": entry["station"],
                "active": True,
                "password_hash": hash_password(entry["password"]),
                # Seeded demo accounts only: lets the login page show the demo
                # credentials in development builds. Real accounts never store this.
                "is_demo": True,
                "demo_password": entry["password"],
                "login_count": 0,
                "last_login_at": None,
                "created_at": utcnow_iso(),
                "created_by": "bootstrap",
                "updated_at": utcnow_iso(),
            }
        )
        created += 1
    return created


async def create_demo_cameras() -> int:
    created = 0
    for entry in DEMO_CAMERAS:
        if await coll(CAMERAS).find_one({"camera_id": entry["camera_id"]}):
            continue
        await coll(CAMERAS).insert_one(
            {
                **entry,
                # Real-time LIVE IP / RTSP cameras only (no demo synthetic feed).
                "mode": MODE_LIVE,
                "demo_source_type": "",
                "demo_source_path": "",
                "enabled": True,
                "detection_enabled": True,
                "status": STATUS_CONNECTING,
                "fps": 30.0,
                "target_fps": 30.0,
                "resolution": "",
                "violation_count": 0,
                "frames_captured": 0,
                "reconnect_attempts": 0,
                "last_seen": None,
                "last_frame_at": None,
                "offline_since": None,
                "connection_error": "",
                "created_at": utcnow_iso(),
                "created_by": "bootstrap",
                "updated_at": utcnow_iso(),
            }
        )
        created += 1
    return created


async def ensure_rto_vehicles() -> int:
    """Keep the local RTO register owners, even if the plate was saved earlier."""
    saved = 0
    for entry in RTO_VEHICLES:
        plate = entry["plate_number"].upper()
        existing = await coll(VEHICLES).find_one({"plate_number": plate})
        fields = {
            **entry,
            "plate_number": plate,
            "source": "RTO",
            "updated_at": utcnow_iso(),
        }
        if existing:
            await coll(VEHICLES).update_one({"_id": existing["_id"]}, {"$set": fields})
        else:
            await coll(VEHICLES).insert_one(
                {
                    **fields,
                    "registration_date": "",
                    "insurance_valid_till": "",
                    "puc_valid_till": "",
                    "violation_count": 0,
                    "total_fine": 0.0,
                    "total_paid": 0.0,
                    "created_at": utcnow_iso(),
                }
            )
        saved += 1
    return saved


async def create_demo_vehicles() -> int:
    created = 0
    for entry in DEMO_VEHICLES:
        if await coll(VEHICLES).find_one({"plate_number": entry["plate_number"]}):
            continue
        await coll(VEHICLES).insert_one(
            {
                **entry,
                "registration_date": "2021-06-15",
                "insurance_valid_till": "2027-03-31",
                "puc_valid_till": "2026-12-31",
                "source": "SEED",
                "violation_count": 0,
                "total_fine": 0.0,
                "total_paid": 0.0,
                "created_at": utcnow_iso(),
                "updated_at": utcnow_iso(),
            }
        )
        created += 1
    return created


async def normalize_ip_webcam_cameras() -> int:
    """Keep phone IP Webcam on HTTP /video; CAM-02 runs the animated demo scene."""
    updated = 0
    cameras = await coll(CAMERAS).find({}).to_list(50)
    for camera in cameras:
        changes: dict = {}
        ip_address = (camera.get("ip_address") or "").strip()
        rtsp_url = (camera.get("rtsp_url") or "").strip()
        camera_id = str(camera.get("camera_id") or "")

        if camera_id == "CAM-01" and (
            "10.157.212.237" in ip_address
            or "192.0.0.8" in ip_address
            or "10.157.212.237" in rtsp_url
            or not ip_address
            or camera.get("mode") == MODE_DEMO
        ):
            desired = {
                "name": "Camera 1",
                "mode": MODE_DEMO,
                "demo_source_type": "SYNTHETIC",
                "demo_source_path": "",
                "ip_address": "",
                "rtsp_url": "",
                "enabled": True,
                "detection_enabled": True,
                "location": "MG Road Junction - South Approach",
                "description": "Animated traffic demo scene for Camera 1",
                "status": STATUS_CONNECTING,
            }
            for key, value in desired.items():
                if camera.get(key) != value:
                    changes[key] = value
        elif camera_id == "CAM-02":
            desired = {
                "name": "Camera 2",
                "mode": MODE_DEMO,
                "demo_source_type": "SYNTHETIC",
                "demo_source_path": "",
                "ip_address": "",
                "rtsp_url": "",
                "location": "MG Road Junction - North Approach",
                "description": "Animated traffic demo scene for Camera 2",
            }
            if "enabled" not in camera:
                desired["enabled"] = True
            if "detection_enabled" not in camera:
                desired["detection_enabled"] = True
            for key, value in desired.items():
                if camera.get(key) != value:
                    changes[key] = value
        elif camera_id == "CAM-03" and (
            "192.168.1.103" in rtsp_url
            or "username:password@" in rtsp_url
            or ip_address == "192.168.1.103"
        ):
            if camera.get("enabled", True):
                changes["enabled"] = False
                changes["status"] = STATUS_DISABLED
        elif ":8080" in ip_address or rtsp_url.lower().startswith(("http://", "https://")):
            host = ip_address.replace("http://", "").replace("https://", "").split("/")[0]
            if host:
                desired_url = f"http://{host}/video"
                if rtsp_url != desired_url:
                    changes["rtsp_url"] = desired_url
                changes["mode"] = MODE_LIVE
                changes["demo_source_type"] = ""
                changes["demo_source_path"] = ""

        if changes:
            changes["updated_at"] = utcnow_iso()
            await coll(CAMERAS).update_one({"_id": camera["_id"]}, {"$set": changes})
            updated += 1
    return updated


async def _set_camera_fps() -> int:
    result = await coll(CAMERAS).update_many({}, {"$set": {"target_fps": 30.0}})
    return int(getattr(result, "modified_count", 0) or 0)


async def bootstrap_if_empty() -> dict:
    await ensure_rules()
    report = {
        "users_created": await create_demo_users(),
        "cameras_created": await create_demo_cameras(),
        "vehicles_created": await create_demo_vehicles(),
        "rto_vehicles": await ensure_rto_vehicles(),
        "cameras_normalized": await normalize_ip_webcam_cameras(),
        "cameras_fps": await _set_camera_fps(),
    }
    if any(report.values()):
        logger.info("Bootstrap created %s", report)
    return report
