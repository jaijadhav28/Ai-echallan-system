"""Runtime application settings stored in MongoDB.

``backend/.env`` holds secrets and boot defaults; this collection holds the
operational values an administrator can change from the Settings page (fine
policy, detection interval, SMS behaviour, RTO office identity).
"""

from __future__ import annotations

import time

from ..config import settings as env_settings
from ..database import SETTINGS_COL, coll
from ..utils import utcnow_iso

DOCUMENT_ID = "app_settings"

DEFAULTS: dict = {
    "rto_office_name": "Regional Transport Office",
    "rto_code": "KA-01",
    "state": "Karnataka",
    "contact_number": "",
    "auto_challan": True,
    "detection_interval_seconds": 8.0,
    "detection_cooldown_seconds": 90.0,
    "detection_min_confidence": 0.55,
    "sms_on_challan": True,
    "challan_due_days": 30,
}


_settings_cache: dict | None = None
_settings_cache_at = 0.0


async def get_settings_document() -> dict:
    global _settings_cache, _settings_cache_at
    if _settings_cache and time.monotonic() - _settings_cache_at < 3:
        return dict(_settings_cache)

    document = await coll(SETTINGS_COL).find_one({"_id": DOCUMENT_ID})
    if not document:
        document = {
            "_id": DOCUMENT_ID,
            **DEFAULTS,
            "auto_challan": bool(env_settings.auto_challan),
            "detection_interval_seconds": float(env_settings.detection_interval_seconds),
            "detection_cooldown_seconds": float(env_settings.detection_cooldown_seconds),
            "detection_min_confidence": float(env_settings.detection_min_confidence),
            "updated_at": utcnow_iso(),
        }
        await coll(SETTINGS_COL).update_one(
            {"_id": DOCUMENT_ID}, {"$set": document}, upsert=True
        )
    merged = {**DEFAULTS, **{k: v for k, v in document.items() if v is not None}}
    merged["id"] = DOCUMENT_ID
    merged.pop("_id", None)
    _settings_cache = dict(merged)
    _settings_cache_at = time.monotonic()
    return merged


async def update_settings_document(changes: dict, actor: str = "system") -> dict:
    global _settings_cache, _settings_cache_at
    _settings_cache = None
    _settings_cache_at = 0.0
    payload = {key: value for key, value in changes.items() if value is not None}
    if payload:
        payload["updated_at"] = utcnow_iso()
        payload["updated_by"] = actor
        await coll(SETTINGS_COL).update_one(
            {"_id": DOCUMENT_ID}, {"$set": payload}, upsert=True
        )
    document = await get_settings_document()
    apply_runtime_overrides(document)
    return document


def apply_runtime_overrides(document: dict) -> None:
    """Let stored settings drive the detection pipeline without a restart."""
    env_settings.detection_interval_seconds = float(
        document.get("detection_interval_seconds")
        or env_settings.detection_interval_seconds
    )
    env_settings.detection_cooldown_seconds = float(
        document.get("detection_cooldown_seconds")
        or env_settings.detection_cooldown_seconds
    )
    env_settings.detection_min_confidence = float(
        document.get("detection_min_confidence") or env_settings.detection_min_confidence
    )
    env_settings.auto_challan = bool(document.get("auto_challan"))
