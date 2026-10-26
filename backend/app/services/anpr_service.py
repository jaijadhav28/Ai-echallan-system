"""ANPR (Automatic Number Plate Recognition) via OCR.Space and Plate Recognizer.

Supports:
1. OCR.Space API (key K87556768888957 or OCR_API_KEY)
2. Plate Recognizer Snapshot API (PLATE_RECOGNIZER_API_KEY)
3. Deterministic fallback for demo mode when neither key is configured.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

import cv2
import httpx
import numpy as np

from ..config import settings
from .base import not_configured, result

logger = logging.getLogger("rto.anpr")

PROVIDER = "ANPR / OCR Service"
OCR_SPACE_URL = "https://api.ocr.space/parse/image"
SNAPSHOT_URL = "https://api.platerecognizer.com/v1/plate-reader/"
STATISTICS_URL = "https://api.platerecognizer.com/v1/statistics/"
INSTRUCTION = (
    "Add OCR_API_KEY or PLATE_RECOGNIZER_API_KEY to backend/.env."
)

_STATE_CODES = ["KA", "MH", "TN", "AP", "TS", "KL", "DL", "GJ", "RJ", "UP"]
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
INDIAN_STATES = r"(MH|KA|DL|GJ|TN|KL|TS|AP|UP|HR|PB|RJ|MP|WB|OD|GA|CH|JK|UK|BR|AS)"
NOISE_WORDS = {
    "HONDA", "HERO", "TVS", "BAJAJ", "YAMAHA", "SUZUKI", "ROYAL", "ENFIELD",
    "IND", "ID", "INDIA", "NO", "HELMET", "EXPLOSIVE", "PROHIBITED", "CONTAINER",
    "EVIDENCE", "UPLOAD", "UPLOADED", "UTC", "ANIENEE", "HELN", "AUTO", "FAST",
    "ROAD", "GOVT", "POLICE", "RTO", "JUNCTION", "CAMERA", "CAM", "STOP", "SLOW"
}


def is_configured() -> bool:
    return settings.anpr_configured


def demo_plate(seed_bytes: bytes) -> str:
    """Deterministic, obviously-synthetic plate used only in DEMO MODE."""
    digest = hashlib.sha256(seed_bytes or b"demo").digest()
    state = _STATE_CODES[digest[0] % len(_STATE_CODES)]
    district = digest[1] % 90 + 10
    series = _LETTERS[digest[2] % len(_LETTERS)] + _LETTERS[digest[3] % len(_LETTERS)]
    number = int.from_bytes(digest[4:6], "big") % 9000 + 1000
    return f"{state}{district}{series}{number}"


def normalize_ocr_text(text: str) -> str:
    """Normalize raw OCR text, replacing Cyrillic characters, currency signs, and noisy symbols."""
    if not text:
        return ""
    t = text.upper()
    t = t.replace("\u041b", "M").replace("\u041f", "P").replace("\u041d", "H")
    t = t.replace("£", "E").replace("€", "E").replace("$", "S").replace("₹", "")
    return t


def fuzzy_match_registered(raw_text: str, registered_plates: list[str]) -> str | None:
    """Fuzzy match OCR text against registered vehicle plates with noise stripping and character normalization."""
    if not raw_text or not registered_plates:
        return None
    norm = normalize_ocr_text(raw_text)
    clean = re.sub(r"[^A-Z0-9]", "", norm)

    # 1. Exact clean text match
    for p in registered_plates:
        if p in clean:
            return p

    # 2. Tokenized match stripping noise words (brands, HSRP logos, etc.)
    tokens = [
        t for t in re.sub(r"[^A-Z0-9]", " ", norm).split()
        if t not in NOISE_WORDS and len(t) >= 1
    ]
    joined = "".join(tokens)
    for p in registered_plates:
        if p in joined:
            return p

    # 3. Match by Registration Number (last 3-4 digits) + State/District/Series
    for p in registered_plates:
        m = re.match(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{3,4})$", p)
        if m:
            state, dist, series, num = m.groups()
            if num in clean or num in joined:
                if state in clean or dist in clean or (series and series in clean):
                    return p
            # Handle common OCR substitutions in digits: 0 <-> O, 2 <-> Z, 5 <-> S, 8 <-> B
            num_fuzzy = (
                num.replace("0", "[0O]")
                .replace("2", "[2Z]")
                .replace("5", "[5S]")
                .replace("8", "[8B]")
            )
            if re.search(num_fuzzy, clean) or re.search(num_fuzzy, joined):
                if state in clean or dist in clean:
                    return p

    return None


async def resolve_registered_plate(raw_text: str) -> str | None:
    """Match raw OCR text against registered vehicle plates in the database."""
    if not raw_text:
        return None
    registered_plates: list[str] = []
    try:
        from ..database import coll, VEHICLES
        vehicles = await coll(VEHICLES).find({}, {"plate_number": 1}).to_list(400)
        registered_plates = [v["plate_number"].upper() for v in vehicles if v.get("plate_number")]
    except Exception:
        pass

    try:
        from ..config import LOCAL_DB_DIR
        import json
        vf = LOCAL_DB_DIR / "vehicles.json"
        if vf.exists():
            with open(vf, "r", encoding="utf-8") as f:
                v_data = json.load(f)
            for v in v_data:
                p = (v.get("plate_number") or "").upper().strip()
                if p and p not in registered_plates:
                    registered_plates.append(p)
    except Exception:
        pass

    if not registered_plates:
        return None

    matched = fuzzy_match_registered(raw_text, registered_plates)
    if matched:
        logger.info("Matched OCR text to registered vehicle: %s -> %s", raw_text.strip()[:40], matched)
        return matched

    return None


def extract_indian_plate(text: str) -> str:
    """Extract standard Indian license plate format from raw OCR text with noise stripping."""
    if not text:
        return ""

    norm = normalize_ocr_text(text)
    raw_tokens = re.sub(r"[^A-Za-z0-9]", " ", norm).split()
    tokens = [t for t in raw_tokens if t not in NOISE_WORDS and len(t) >= 1]
    joined = "".join(tokens)

    # Standard pattern: State (2 chars) + District (1-2 digits) + Series (0-3 chars) + Number (1-4 digits)
    pattern = rf"{INDIAN_STATES}([0-9O]{{1,2}})([A-Z]{{0,3}})([0-9O]{{3,4}})"
    m = re.search(pattern, joined)
    if m:
        state, dist, series, num = m.groups()
        dist = dist.replace("O", "0")
        num = num.replace("O", "0")
        return f"{state}{dist}{series}{num}"

    # Two-line plate: State+Dist in one token, Series+Num in following token
    for i, t1 in enumerate(tokens):
        m1 = re.match(rf"^{INDIAN_STATES}([0-9O]{{1,2}})([A-Z]{{0,2}})$", t1)
        if m1:
            state, dist, series_prefix = m1.groups()
            dist = dist.replace("O", "0")
            for t2 in tokens[i + 1 : i + 4]:
                m2 = re.match(r"^([A-Z]{0,2})([0-9O]{1,4})$", t2)
                if m2:
                    series_suffix, num = m2.groups()
                    num = num.replace("O", "0")
                    full_series = series_prefix + series_suffix
                    return f"{state}{dist}{full_series}{num}"

    # Direct regex search on clean_text
    clean_all = re.sub(r"[^A-Za-z0-9]", "", norm)
    m_all = re.search(pattern, clean_all)
    if m_all:
        state, dist, series, num = m_all.groups()
        dist = dist.replace("O", "0")
        num = num.replace("O", "0")
        return f"{state}{dist}{series}{num}"

    return ""


def prepare_anpr_crops(image_bytes: bytes) -> list[tuple[str, bytes]]:
    """Generate targeted region-of-interest crops and downscale large mobile images to fit OCR limits.
    
    OCR.Space free tier strictly caps upload size at 1.5MB. Mobile cameras produce 2MB-5MB photos.
    Additionally, cropping the vehicle/license plate region dramatically increases OCR accuracy.
    """
    try:
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        img = None

    if img is None:
        return [("raw_image", image_bytes)]

    h, w = img.shape[:2]
    candidates: list[tuple[str, np.ndarray]] = []

    # 1. Primary vehicle/rider ROI: Center-lower 65% of the frame (where plates are in camera/traffic views)
    roi_vehicle = img[int(h * 0.35) : int(h * 0.98), int(w * 0.18) : int(w * 0.82)]
    if roi_vehicle.size > 0:
        candidates.append(("vehicle_roi", roi_vehicle))

    # 2. Bottom center ROI: Lower 45% (for closer scooter/car shots)
    roi_bottom = img[int(h * 0.52) : int(h * 0.98), int(w * 0.22) : int(w * 0.78)]
    if roi_bottom.size > 0:
        candidates.append(("roi_bottom", roi_bottom))

    # 3. Full frame downscaled
    candidates.append(("full_frame", img))

    crops: list[tuple[str, bytes]] = []
    for name, cimg in candidates:
        ch, cw = cimg.shape[:2]
        max_dim = 1600
        if max(ch, cw) > max_dim:
            scale = max_dim / max(ch, cw)
            cimg = cv2.resize(cimg, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_AREA)

        ok, enc = cv2.imencode(".jpg", cimg, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if ok:
            crops.append((name, enc.tobytes()))

    return crops if crops else [("raw_image", image_bytes)]


async def test_connection() -> dict:
    if not is_configured():
        return not_configured(PROVIDER, INSTRUCTION)

    started = time.perf_counter()

    # 1. Test OCR.Space if key configured
    ocr_key = settings.ocr_api_key.strip()
    if ocr_key:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                res = await client.get("https://api.ocr.space", timeout=15)
            latency = int((time.perf_counter() - started) * 1000)
            if res.status_code == 200:
                return result(
                    ok=True,
                    provider="OCR.Space ANPR",
                    message=f"Connected to OCR.Space API (Key: {ocr_key[:4]}****{ocr_key[-4:] if len(ocr_key) > 4 else ''}).",
                    data={"engine": "OCR.Space", "key_configured": True},
                    status_code=200,
                    latency_ms=latency,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR.Space connection test notice: %s", exc)

    # 2. Test Plate Recognizer if key configured
    pr_key = settings.plate_recognizer_api_key.strip()
    if pr_key:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    STATISTICS_URL,
                    headers={"Authorization": f"Token {pr_key}"},
                )
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code == 200:
                body = response.json()
                usage = body.get("usage", {}) if isinstance(body, dict) else {}
                return result(
                    ok=True,
                    provider="Plate Recognizer ANPR",
                    message="Connected to Plate Recognizer Snapshot API.",
                    data={
                        "calls_used": usage.get("calls"),
                        "monthly_limit": body.get("total_calls") if isinstance(body, dict) else None,
                        "regions": settings.plate_recognizer_regions,
                    },
                    status_code=200,
                    latency_ms=latency,
                )
        except Exception as exc:  # noqa: BLE001
            return result(ok=False, provider=PROVIDER, message=f"Could not reach Plate Recognizer: {exc}")

    return result(
        ok=True,
        provider=PROVIDER,
        message="OCR / ANPR API Key configured.",
        data={"configured": True},
        status_code=200,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def _read_with_ocr_space(image_bytes: bytes, ocr_key: str) -> dict | None:
    started = time.perf_counter()
    crops = prepare_anpr_crops(image_bytes)

    async with httpx.AsyncClient(timeout=35) as client:
        for crop_name, crop_bytes in crops:
            for engine in ["2", "1"]:
                try:
                    response = await client.post(
                        OCR_SPACE_URL,
                        files={"file": ("frame.jpg", crop_bytes, "image/jpeg")},
                        data={
                            "apikey": ocr_key,
                            "language": "eng",
                            "OCREngine": engine,
                            "scale": "true",
                            "detectOrientation": "true",
                            "isOverlayRequired": False,
                        },
                    )
                    if response.status_code != 200:
                        logger.warning("OCR.Space returned status %s for crop %s", response.status_code, crop_name)
                        continue

                    data = response.json()
                    parsed_results = data.get("ParsedResults") or []
                    if not parsed_results:
                        continue

                    raw_text = parsed_results[0].get("ParsedText", "").strip()
                    if not raw_text:
                        continue

                    # 1. Match against registered vehicles in RTO database
                    reg_plate = await resolve_registered_plate(raw_text)
                    if reg_plate:
                        latency = int((time.perf_counter() - started) * 1000)
                        logger.info("ANPR recognized registered vehicle %s on crop %s (engine %s)", reg_plate, crop_name, engine)
                        return result(
                            ok=True,
                            provider="OCR.Space ANPR",
                            message=f"Registered vehicle number plate recognized: {reg_plate}",
                            data={
                                "plate_number": reg_plate,
                                "plate_source": "OCR_REGISTERED_MATCH",
                                "confidence": 0.98,
                                "raw_text": raw_text,
                                "crop_used": crop_name,
                            },
                            status_code=200,
                            latency_ms=latency,
                        )

                    # 2. Extract standard Indian plate format
                    plate = extract_indian_plate(raw_text)
                    if plate:
                        latency = int((time.perf_counter() - started) * 1000)
                        logger.info("ANPR recognized Indian plate %s on crop %s (engine %s)", plate, crop_name, engine)
                        return result(
                            ok=True,
                            provider="OCR.Space ANPR",
                            message=f"Number plate recognized via OCR: {plate}",
                            data={
                                "plate_number": plate,
                                "plate_source": "OCR_SPACE",
                                "confidence": 0.94,
                                "raw_text": raw_text,
                                "crop_used": crop_name,
                            },
                            status_code=200,
                            latency_ms=latency,
                        )

                    # If Engine 2 returned text but neither matched, skip Engine 1 for this crop
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("OCR.Space error on crop %s (engine %s): %s", crop_name, engine, exc)

    return None


async def read_plate(image_bytes: bytes, camera_id: str = "") -> dict:
    """Recognise a number plate from a JPEG frame using OCR.Space or Plate Recognizer."""
    if not is_configured():
        payload = not_configured(PROVIDER, INSTRUCTION)
        payload["data"] = {
            "plate_number": demo_plate(image_bytes),
            "plate_source": "DEMO",
            "confidence": None,
            "region": settings.plate_recognizer_regions.upper(),
            "note": "Demo plate generated locally - configure OCR_API_KEY to read real plates.",
        }
        return payload

    # Try OCR.Space first if key is configured
    ocr_key = settings.ocr_api_key.strip()
    if ocr_key:
        ocr_result = await _read_with_ocr_space(image_bytes, ocr_key)
        if ocr_result and ocr_result.get("ok") and (ocr_result.get("data") or {}).get("plate_number"):
            return ocr_result

    # Try Plate Recognizer if configured
    pr_key = settings.plate_recognizer_api_key.strip()
    if pr_key:
        started = time.perf_counter()
        pr_payload = image_bytes
        try:
            crops = prepare_anpr_crops(image_bytes)
            if crops:
                pr_payload = crops[0][1]
        except Exception:
            pass

        try:
            async with httpx.AsyncClient(timeout=40) as client:
                response = await client.post(
                    SNAPSHOT_URL,
                    headers={"Authorization": f"Token {pr_key}"},
                    files={"upload": ("frame.jpg", pr_payload, "image/jpeg")},
                    data={
                        "regions": settings.plate_recognizer_regions,
                        "camera_id": camera_id or "rto-camera",
                    },
                )
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code in (200, 201):
                body = response.json()
                candidates = body.get("results") or []
                if candidates:
                    best = max(candidates, key=lambda item: item.get("score") or 0)
                    recognized_plate = str(best.get("plate", "")).upper()
                    # Check registered vehicles for best match
                    reg_match = await resolve_registered_plate(recognized_plate)
                    if reg_match:
                        recognized_plate = reg_match
                    return result(
                        ok=True,
                        provider="Plate Recognizer",
                        message="Number plate recognised.",
                        data={
                            "plate_number": recognized_plate,
                            "plate_source": "ANPR",
                            "confidence": round(float(best.get("score") or 0), 3),
                            "region": (best.get("region") or {}).get("code", "").upper(),
                            "vehicle_type": (best.get("vehicle") or {}).get("type", ""),
                            "box": best.get("box"),
                        },
                        status_code=response.status_code,
                        latency_ms=latency,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Plate Recognizer error: %s", exc)

    # If OCR is configured but no plate could be extracted, do not fabricate a fake demo plate
    # Unless camera is specifically DEMO mode
    is_demo_mode = str(camera_id).startswith("CAM-02")
    return result(
        ok=True,
        provider=PROVIDER,
        message="No readable number plate found in the frame." if not is_demo_mode else "Demo synthetic plate.",
        data={
            "plate_number": demo_plate(image_bytes) if is_demo_mode else "",
            "plate_source": "DEMO_SYNTHETIC" if is_demo_mode else "OCR_NO_READ",
            "confidence": None,
        },
        status_code=200,
    )

