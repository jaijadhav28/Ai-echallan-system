"""Operational settings (RTO identity, fine policy, detection behaviour)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import mask_secret, settings as env_settings, update_env_key
from ..database import AUDIT, ALL_COLLECTIONS, coll, database
from ..deps import get_current_user, require_admin
from ..schemas import AnprKeyBody, AppSettingsBody
from ..services.app_settings import get_settings_document, update_settings_document
from ..services.pipeline import pipeline
from ..utils import utcnow_iso

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("")
async def read_settings(_: dict = Depends(get_current_user)) -> dict:
    document = await get_settings_document()
    counts = {}
    for name in ALL_COLLECTIONS:
        try:
            counts[name] = await coll(name).count_documents({})
        except Exception:  # noqa: BLE001
            counts[name] = -1

    return {
        "settings": document,
        "system": {
            "environment": env_settings.app_env,
            "database_backend": database.backend,
            "database_name": env_settings.mongo_db_name,
            "detection_interval_seconds": env_settings.detection_interval_seconds,
            "detection_cooldown_seconds": env_settings.detection_cooldown_seconds,
            "detection_min_confidence": env_settings.detection_min_confidence,
            "auto_challan": env_settings.auto_challan,
            "pipeline": pipeline.status(),
            "collection_counts": counts,
            "groq_ai": {
                "configured": env_settings.ai_configured,
            },
            "anpr": {
                "configured": env_settings.anpr_configured,
                "provider": "Plate Recognizer",
                "regions": env_settings.plate_recognizer_regions,
                "key_hint": mask_secret(env_settings.plate_recognizer_api_key) if env_settings.anpr_configured else "",
            },
        },
        "read_at": utcnow_iso(),
    }


@router.post("/ocr-key")
async def save_ocr_key(body: AnprKeyBody, admin: dict = Depends(require_admin)) -> dict:
    """Store the Plate Recognizer token used to read number plates."""
    token = body.plate_recognizer_api_key.strip()
    update_env_key("PLATE_RECOGNIZER_API_KEY", token)
    await coll(AUDIT).insert_one(
        {
            "action": "OCR_KEY_UPDATED",
            "actor": admin["user_id"],
            "detail": "Number plate OCR API key saved",
            "created_at": utcnow_iso(),
        }
    )
    return {
        "updated": True,
        "configured": env_settings.anpr_configured,
        "key_hint": mask_secret(token),
        "message": "OCR API key saved. Number plates will be read on the next detection.",
    }


@router.put("")
async def write_settings(body: AppSettingsBody, admin: dict = Depends(require_admin)) -> dict:
    document = await update_settings_document(body.model_dump(), actor=admin["user_id"])
    return {
        "updated": True,
        "settings": document,
        "message": "Settings saved. Detection changes apply from the next cycle.",
    }
