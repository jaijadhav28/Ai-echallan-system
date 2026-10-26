"""Modular violation detection.

Input : a camera frame (plus the source's ground truth for synthetic cameras)
Output: a list of detections, each with violation type, confidence, camera id,
        timestamp and an evidence image path.

Three interchangeable detectors are registered, chosen per call:

``GROQ_VISION``      - real AI. The frame is sent to a Groq vision model, which
                       reports which of the four violations it can see. Used
                       whenever ``GROQ_API_KEY`` is configured.
``OPENCV_HEURISTIC`` - offline computer-vision fallback for real footage. Uses
                       HOG person detection, dense optical flow for direction and
                       HSV colour analysis. Coarse by design; confidences are
                       deliberately capped.
``DEMO_SIMULATOR``   - only for synthetic demo cameras. Reads the scripted ground
                       truth of the rendered scene. Records produced this way are
                       stamped as simulated so they are never mistaken for AI
                       output.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import uuid
from typing import Any

import cv2
import numpy as np

from ..config import EVIDENCE_DIR, settings
from ..constants import (
    DEMO_SOURCE_SYNTHETIC,
    DETECTOR_GROQ,
    DETECTOR_HEURISTIC,
    MODE_DEMO,
    NO_HELMET,
    PROHIBITED_CONTAINER,
    TRIPLE_RIDING,
    VIOLATION_LABELS,
    WRONG_SIDE_DRIVING,
)
from ..utils import utcnow, utcnow_iso
from . import ai_service, gpu_accel
from .camera_manager import encode_jpeg

logger = logging.getLogger("rto.detection")

DETECTOR_SIMULATOR = "DEMO_SIMULATOR"

_hog = cv2.HOGDescriptor()
_hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

_upperbody_cascade: cv2.CascadeClassifier | None = None
_face_cascade: cv2.CascadeClassifier | None = None
_profile_cascade: cv2.CascadeClassifier | None = None


def _get_cascades() -> tuple[cv2.CascadeClassifier | None, cv2.CascadeClassifier | None, cv2.CascadeClassifier | None]:
    global _upperbody_cascade, _face_cascade, _profile_cascade
    if _upperbody_cascade is None:
        try:
            cascade_dir = getattr(cv2, "data", None)
            prefix = cascade_dir.haarcascades if cascade_dir else ""
            _upperbody_cascade = cv2.CascadeClassifier(prefix + "haarcascade_upperbody.xml")
            _face_cascade = cv2.CascadeClassifier(prefix + "haarcascade_frontalface_alt2.xml")
            _profile_cascade = cv2.CascadeClassifier(prefix + "haarcascade_profileface.xml")
        except Exception as exc:
            logger.warning("Could not load Haar cascades: %s", exc)
    return _upperbody_cascade, _face_cascade, _profile_cascade


# previous grayscale frame per camera, for optical-flow direction estimation
_previous_gray: dict[str, np.ndarray] = {}

_DIRECTION_VECTORS = {
    "LEFT_TO_RIGHT": (1.0, 0.0),
    "RIGHT_TO_LEFT": (-1.0, 0.0),
    "TOP_TO_BOTTOM": (0.0, 1.0),
    "BOTTOM_TO_TOP": (0.0, -1.0),
}


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #
def annotate(frame: np.ndarray, detections: list[dict], camera: dict) -> np.ndarray:
    """Draw violation boxes and labels for the stored evidence image."""
    canvas = frame.copy()
    height, width = canvas.shape[:2]

    for index, detection in enumerate(detections):
        box = detection.get("box")
        colour = (40, 60, 230)
        if box and len(box) == 4:
            x, y, box_width, box_height = (int(value) for value in box)
            x, y = max(x, 0), max(y, 0)
            cv2.rectangle(canvas, (x, y), (x + box_width, y + box_height), colour, 2)
            label = VIOLATION_LABELS.get(detection["violation_type"], detection["violation_type"])
            cv2.rectangle(canvas, (x, max(y - 22, 0)), (x + 210, max(y, 22)), colour, -1)
            cv2.putText(
                canvas,
                f"{label} {int(detection['confidence'] * 100)}%",
                (x + 4, max(y - 6, 14)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
            )
        else:
            cv2.putText(
                canvas,
                f"{VIOLATION_LABELS.get(detection['violation_type'], '')} "
                f"{int(detection['confidence'] * 100)}%",
                (12, 60 + index * 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                colour,
                2,
            )

    banner = (
        f"EVIDENCE | {camera.get('camera_id', '')} | {camera.get('location', '')} | "
        f"{utcnow().strftime('%d-%m-%Y %H:%M:%S')} UTC"
    )
    cv2.rectangle(canvas, (0, height - 30), (width, height), (15, 15, 20), -1)
    cv2.putText(
        canvas, banner[:92], (10, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 240), 1
    )
    return canvas


def save_evidence(frame: np.ndarray, detections: list[dict], camera: dict) -> str:
    """Persist the annotated evidence image; returns its file name."""
    annotated = annotate(frame, detections, camera)
    encoded = encode_jpeg(annotated)
    if not encoded:
        return ""
    filename = (
        f"{camera.get('camera_id', 'CAM')}_"
        f"{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
    )
    (EVIDENCE_DIR / filename).write_bytes(encoded)
    return filename


# --------------------------------------------------------------------------- #
# detector 1: simulated (synthetic demo cameras only)
# --------------------------------------------------------------------------- #
def detect_from_ground_truth(ground_truth: dict, camera: dict) -> dict:
    detections: list[dict] = []
    vehicles = ground_truth.get("vehicles") or []

    for vehicle in vehicles:
        box = vehicle.get("box")
        plate = vehicle.get("plate", "")
        base = {
            "box": box,
            "plate_text": plate,
            "vehicle_type": vehicle.get("vehicle_type", ""),
        }
        if vehicle.get("no_helmet"):
            riders = max(int(vehicle.get("riders") or 1), 1)
            without = riders - int(vehicle.get("helmets_worn") or 0)
            detections.append(
                {
                    **base,
                    "violation_type": NO_HELMET,
                    "confidence": round(random.uniform(0.86, 0.97), 3),
                    "reason": f"{without} of {riders} rider(s) without a helmet",
                }
            )
        if vehicle.get("triple_riding"):
            detections.append(
                {
                    **base,
                    "violation_type": TRIPLE_RIDING,
                    "confidence": round(random.uniform(0.88, 0.98), 3),
                    "reason": f"{vehicle.get('riders')} persons on a two-wheeler",
                }
            )
        if vehicle.get("wrong_side"):
            detections.append(
                {
                    **base,
                    "violation_type": WRONG_SIDE_DRIVING,
                    "confidence": round(random.uniform(0.82, 0.95), 3),
                    "reason": "Vehicle travelling against the lane direction",
                }
            )
        if vehicle.get("carries_container"):
            detections.append(
                {
                    **base,
                    "violation_type": PROHIBITED_CONTAINER,
                    "confidence": round(random.uniform(0.78, 0.93), 3),
                    "reason": "Cylinder / inflammable container carried on a two-wheeler",
                }
            )

    return {
        "detector": DETECTOR_SIMULATOR,
        "simulated": True,
        "detections": detections,
        "scene": (
            f"Synthetic demo scene with {ground_truth.get('vehicle_count', 0)} vehicle(s) "
            f"on {camera.get('camera_id', '')}"
        ),
        "vehicle_count": ground_truth.get("vehicle_count", 0),
        "notes": "Scripted demo scenario - not a real AI inference.",
    }


# --------------------------------------------------------------------------- #
# detector 2: OpenCV heuristics (real footage, no API key needed)
# --------------------------------------------------------------------------- #
def _detect_people(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Detect people/riders using multi-scale HOG + Upper Body + Face cascades with NMS."""
    scale = 640 / max(frame.shape[1], 1)
    factor = min(scale, 1.0)
    resized = gpu_accel.gpu_resize(frame, fx=factor, fy=factor)
    gray = gpu_accel.gpu_cvt_color(resized, cv2.COLOR_BGR2GRAY)
    ratio = 1.0 / factor

    candidates: list[list[int]] = []
    scores: list[float] = []

    # 1. HOG person detector with finer stride and lower threshold for seated riders
    try:
        source = gpu_accel.to_umat(resized) if gpu_accel.using_gpu() else resized
        boxes, weights = _hog.detectMultiScale(
            source, winStride=(4, 4), padding=(8, 8), scale=1.05
        )
        if boxes is not None and len(boxes) > 0:
            for (x, y, w, h), weight in zip(boxes, np.array(weights).flatten()):
                if weight >= 0.10:
                    candidates.append([int(x * ratio), int(y * ratio), int(w * ratio), int(h * ratio)])
                    scores.append(float(weight) + 0.3)
    except cv2.error:
        pass

    # 2. Upper body cascade (captures riders seated on two-wheelers where legs are hidden)
    upper_c, face_c, prof_c = _get_cascades()
    if upper_c and not upper_c.empty():
        try:
            upper_bodies = upper_c.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30))
            for (ux, uy, uw, uh) in upper_bodies:
                full_h = int(uh * 1.6)
                candidates.append([int(ux * ratio), int(uy * ratio), int(uw * ratio), int(full_h * ratio)])
                scores.append(0.75)
        except cv2.error:
            pass

    # 3. Face and profile cascades (detects bare-headed or open-helmet riders directly)
    for cascade in (face_c, prof_c):
        if cascade and not cascade.empty():
            try:
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
                for (fx, fy, fw, fh) in faces:
                    person_w = int(fw * 2.2)
                    person_h = int(fh * 4.5)
                    person_x = max(0, int((fx - fw * 0.6) * ratio))
                    person_y = max(0, int((fy - fh * 0.3) * ratio))
                    candidates.append([person_x, person_y, int(person_w * ratio), int(person_h * ratio)])
                    scores.append(0.70)
            except cv2.error:
                pass

    if not candidates:
        return []

    # Non-maximum suppression to eliminate overlapping redundant detections
    try:
        indices = cv2.dnn.NMSBoxes(candidates, scores, score_threshold=0.25, nms_threshold=0.45)
        if len(indices) > 0:
            selected_indices = indices.flatten() if hasattr(indices, "flatten") else [i[0] for i in indices]
            frame_h, frame_w = frame.shape[:2]
            results: list[tuple[int, int, int, int]] = []
            for i in selected_indices:
                cx, cy, cw, ch = candidates[i]
                cx, cy = max(0, cx), max(0, cy)
                cw = min(cw, frame_w - cx)
                if cw > 15 and ch > 25:
                    results.append((cx, cy, cw, ch))
            return _merge_person_boxes(results)
    except Exception:
        pass

    return _merge_person_boxes([tuple(c) for c in candidates[:8]])


def _merge_person_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Merge overlapping boxes that represent the same human rider (e.g. head + torso)."""
    if not boxes:
        return []

    merged: list[list[int]] = []
    for b in boxes:
        bx, by, bw, bh = b
        matched = False
        for m in merged:
            mx, my, mw, mh = m
            bcx, bcy = bx + bw / 2, by + bh / 2
            mcx, mcy = mx + mw / 2, my + mh / 2

            ix1, iy1 = max(bx, mx), max(by, my)
            ix2, iy2 = min(bx + bw, mx + mw), min(by + bh, my + mh)
            iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
            inter_area = iw * ih
            min_area = min(bw * bh, mw * mh)

            horiz_overlap = max(0, min(bx + bw, mx + mw) - max(bx, mx)) / max(min(bw, mw), 1)
            vert_gap = max(0, max(by, my) - min(by + bh, my + mh))

            # Merge if overlapping area > 25%, centers close, or head-above-body alignment
            if (
                (min_area > 0 and inter_area / min_area > 0.25)
                or (abs(bcx - mcx) < min(bw, mw) * 0.70 and abs(bcy - mcy) < min(bh, mh) * 0.70)
                or (horiz_overlap > 0.45 and vert_gap < min(bh, mh) * 0.6)
            ):
                nx1 = min(bx, mx)
                ny1 = min(by, my)
                nx2 = max(bx + bw, mx + mw)
                ny2 = max(by + bh, my + mh)
                m[0], m[1], m[2], m[3] = nx1, ny1, nx2 - nx1, ny2 - ny1
                matched = True
                break
        if not matched:
            merged.append(list(b))

    return [tuple(m) for m in merged]


def _cluster(boxes: list[tuple[int, int, int, int]], gap: int = 90) -> list[list[tuple]]:
    clusters: list[list[tuple]] = []
    for box in sorted(boxes, key=lambda item: item[0]):
        placed = False
        for cluster in clusters:
            last = cluster[-1]
            if abs(box[0] - last[0]) < gap and abs(box[1] - last[1]) < gap:
                cluster.append(box)
                placed = True
                break
        if not placed:
            clusters.append([box])
    return clusters


def _helmet_absent(frame: np.ndarray, box: tuple[int, int, int, int]) -> tuple[bool, float]:
    """Determine whether a helmet is absent using skin tone, facial visibility, crown coverage, and dome geometry."""
    x, y, width, height = box
    frame_h, frame_w = frame.shape[:2]

    # Focus on the head region (top 35% of person bounding box)
    head_y1 = max(y, 0)
    head_y2 = min(frame_h, max(y + int(height * 0.35), head_y1 + 16))
    head_x1 = max(0, x + int(width * 0.08))
    head_x2 = min(frame_w, max(x + int(width * 0.92), head_x1 + 16))
    head = frame[head_y1:head_y2, head_x1:head_x2]

    if head.size < 64:
        return False, 0.0

    head_h, head_w = head.shape[:2]
    crown_cutoff = max(int(head_h * 0.45), 4)
    crown = head[:crown_cutoff, :]

    # 1. Dual-space skin tone analysis (YCrCb + HSV)
    ycrcb = gpu_accel.gpu_cvt_color(head, cv2.COLOR_BGR2YCR_CB)
    skin_ycrcb = (
        (ycrcb[:, :, 1] >= 130) & (ycrcb[:, :, 1] <= 175) &
        (ycrcb[:, :, 2] >= 75) & (ycrcb[:, :, 2] <= 130)
    )
    hsv = gpu_accel.gpu_cvt_color(head, cv2.COLOR_BGR2HSV)
    skin_hsv = (
        (hsv[:, :, 0] >= 0) & (hsv[:, :, 0] <= 28) &
        (hsv[:, :, 1] >= 25) & (hsv[:, :, 1] <= 210) &
        (hsv[:, :, 2] >= 45)
    )
    skin_mask = skin_ycrcb & skin_hsv

    total_skin_ratio = float(np.mean(skin_mask))
    crown_skin_ratio = float(np.mean(skin_mask[:crown_cutoff, :]))
    face_skin_ratio = float(np.mean(skin_mask[int(head_h * 0.28):, :]))

    # 2. Facial visibility check in head ROI
    _, face_c, _ = _get_cascades()
    head_gray = gpu_accel.gpu_cvt_color(head, cv2.COLOR_BGR2GRAY)
    has_detected_face = False
    if face_c and not face_c.empty() and min(head_h, head_w) >= 20:
        try:
            detected_faces = face_c.detectMultiScale(head_gray, scaleFactor=1.1, minNeighbors=3, minSize=(16, 16))
            has_detected_face = len(detected_faces) > 0
        except cv2.error:
            pass

    # 3. Helmet shell smoothness and dome contour
    crown_gray = gpu_accel.gpu_cvt_color(crown, cv2.COLOR_BGR2GRAY)
    crown_edges = cv2.Canny(crown_gray, 50, 150)
    crown_edge_density = float(crown_edges.mean())

    # Helmets (black, matte, white, silver, or bright colored) completely cover the top crown:
    # Bare heads expose face skin + forehead and/or high fibrous hair texture.
    if crown_skin_ratio < 0.02 and (face_skin_ratio < 0.08 or (not has_detected_face and face_skin_ratio < 0.15)):
        # Crown is completely covered by an opaque shell (helmet worn)
        return False, 0.25

    if has_detected_face and (face_skin_ratio > 0.08 or crown_skin_ratio > 0.03):
        # Direct face confirmed exposed without helmet visor/shell
        confidence = min(0.94, 0.76 + face_skin_ratio * 0.25)
        return True, round(confidence, 3)

    if total_skin_ratio >= 0.14 or (face_skin_ratio >= 0.16 and crown_skin_ratio >= 0.03):
        # Strong exposed skin signature across face and forehead
        confidence = min(0.92, 0.70 + total_skin_ratio * 0.35)
        return True, round(confidence, 3)

    if crown_skin_ratio >= 0.07:
        # Forehead / scalp skin directly exposed in the crown
        confidence = min(0.88, 0.68 + crown_skin_ratio * 0.4)
        return True, round(confidence, 3)

    if face_skin_ratio >= 0.20 and crown_edge_density > 10.0:
        # Exposed face with hair edges on top
        confidence = min(0.86, 0.65 + face_skin_ratio * 0.3)
        return True, round(confidence, 3)

    # Default to helmet present if crown is uniform and covered
    return False, 0.30


def _dominant_direction(camera_id: str, frame: np.ndarray) -> tuple[float, float, float]:
    """Return ``(dx, dy, magnitude)`` of the dominant motion via optical flow."""
    small = gpu_accel.gpu_resize(frame, size=(320, 180))
    gray = gpu_accel.gpu_cvt_color(small, cv2.COLOR_BGR2GRAY)
    previous = _previous_gray.get(camera_id)
    _previous_gray[camera_id] = gray
    if previous is None or previous.shape != gray.shape:
        return 0.0, 0.0, 0.0

    try:
        if gpu_accel.using_gpu():
            flow = cv2.calcOpticalFlowFarneback(
                gpu_accel.to_umat(previous),
                gpu_accel.to_umat(gray),
                None,
                0.5,
                3,
                15,
                3,
                5,
                1.2,
                0,
            )
            flow = gpu_accel.from_umat(flow)
        else:
            flow = cv2.calcOpticalFlowFarneback(
                previous, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
    except cv2.error:
        flow = cv2.calcOpticalFlowFarneback(
            previous, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )
    magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    moving = magnitude > 1.0
    if not moving.any():
        return 0.0, 0.0, 0.0

    dx = float(flow[..., 0][moving].mean())
    dy = float(flow[..., 1][moving].mean())
    return dx, dy, float(math.hypot(dx, dy))


def _detect_container(frame: np.ndarray) -> list[dict]:
    hsv = gpu_accel.gpu_cvt_color(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 130, 90), (12, 255, 255)) | cv2.inRange(
        hsv, (168, 130, 90), (180, 255, 255)
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    findings: list[dict] = []
    frame_area = frame.shape[0] * frame.shape[1]
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < frame_area * 0.0012 or area > frame_area * 0.08:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if height == 0:
            continue
        aspect = width / height
        fill = area / max(width * height, 1)
        if 0.35 <= aspect <= 1.5 and fill > 0.55:
            findings.append(
                {
                    "violation_type": PROHIBITED_CONTAINER,
                    "confidence": round(min(0.72, 0.45 + fill * 0.3), 3),
                    "box": [x, y, width, height],
                    "reason": "Compact high-saturation cylindrical object detected",
                }
            )
    return findings[:2]


def detect_with_opencv(frame: np.ndarray, camera: dict) -> dict:
    camera_id = str(camera.get("camera_id", ""))
    detections: list[dict] = []

    people = _detect_people(frame)
    clusters = _cluster(people)

    for cluster in clusters:
        if len(cluster) >= 3:
            xs = [box[0] for box in cluster]
            ys = [box[1] for box in cluster]
            widths = [box[0] + box[2] for box in cluster]
            heights = [box[1] + box[3] for box in cluster]
            detections.append(
                {
                    "violation_type": TRIPLE_RIDING,
                    "confidence": round(min(0.8, 0.55 + 0.07 * len(cluster)), 3),
                    "box": [min(xs), min(ys), max(widths) - min(xs), max(heights) - min(ys)],
                    "reason": f"{len(cluster)} persons detected on one vehicle footprint",
                }
            )

    for box in people[:6]:
        absent, confidence = _helmet_absent(frame, box)
        if absent:
            detections.append(
                {
                    "violation_type": NO_HELMET,
                    "confidence": confidence,
                    "box": list(box),
                    "reason": "Rider without helmet: exposed face/forehead skin detected in head region",
                }
            )

    allowed = (camera.get("allowed_direction") or "ANY").upper()
    dx, dy, magnitude = _dominant_direction(camera_id, frame)
    if allowed in _DIRECTION_VECTORS and magnitude > 1.2:
        expected_x, expected_y = _DIRECTION_VECTORS[allowed]
        alignment = (dx * expected_x + dy * expected_y) / (magnitude or 1)
        if alignment < -0.45:
            detections.append(
                {
                    "violation_type": WRONG_SIDE_DRIVING,
                    "confidence": round(min(0.82, 0.5 + abs(alignment) * 0.35), 3),
                    "box": None,
                    "reason": (
                        f"Dominant motion opposes the permitted direction "
                        f"({allowed.replace('_', ' ').lower()})"
                    ),
                }
            )

    # Note: PROHIBITED_CONTAINER is handled via synthetic ground truth or AI vision.
    # Omitted from OpenCV heuristic on real frames to avoid false positives on red vehicles/clothes.

    return {
        "detector": DETECTOR_HEURISTIC,
        "simulated": False,
        "detections": detections,
        "scene": f"{len(people)} person(s), motion magnitude {magnitude:.2f}",
        "vehicle_count": len(clusters),
        "notes": (
            f"OpenCV heuristic detector (HOG + optical flow + HSV)"
            f"{' on GPU/OpenCL' if gpu_accel.using_gpu() else ' on CPU'}."
        ),
    }


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def choose_detector(camera: dict, ground_truth: dict, preference: str = "auto") -> str:
    preference = (preference or "auto").lower()
    if preference in {"groq", DETECTOR_GROQ.lower()}:
        return DETECTOR_GROQ
    if preference in {"opencv", "heuristic", DETECTOR_HEURISTIC.lower()}:
        return DETECTOR_HEURISTIC
    if preference in {"simulator", DETECTOR_SIMULATOR.lower()}:
        return DETECTOR_SIMULATOR

    if ai_service.is_configured():
        return DETECTOR_GROQ
    is_synthetic = (
        (camera.get("mode") or MODE_DEMO).upper() == MODE_DEMO
        and (camera.get("demo_source_type") or "").upper() == DEMO_SOURCE_SYNTHETIC
        and (ground_truth or {}).get("source") == "SYNTHETIC"
    )
    return DETECTOR_SIMULATOR if is_synthetic else DETECTOR_HEURISTIC


async def analyse(
    camera: dict,
    frame: np.ndarray,
    ground_truth: dict | None = None,
    preference: str = "auto",
) -> dict:
    """Run the selected detector and return a normalised outcome."""
    ground_truth = ground_truth or {}
    detector = choose_detector(camera, ground_truth, preference)
    outcome: dict[str, Any]

    if detector == DETECTOR_GROQ:
        encoded = encode_jpeg(frame) or b""
        context = (
            f"Camera {camera.get('camera_id')} at {camera.get('location') or 'unknown location'}; "
            f"mode {camera.get('mode')}"
        )
        api_result = await ai_service.analyse_frame(encoded, context)
        if api_result["ok"]:
            outcome = {
                "detector": DETECTOR_GROQ,
                "simulated": False,
                "detections": api_result["data"].get("detections", []),
                "scene": api_result["data"].get("scene", ""),
                "vehicle_count": api_result["data"].get("vehicle_count"),
                "notes": f"Groq vision model {api_result['data'].get('model')}",
            }
        else:
            # Never invent an AI result - fall back and say so.
            fallback = await asyncio.to_thread(detect_with_opencv, frame, camera)
            fallback["notes"] = f"Groq unavailable ({api_result['message']}). {fallback['notes']}"
            outcome = fallback
    elif detector == DETECTOR_SIMULATOR:
        outcome = detect_from_ground_truth(ground_truth, camera)
    else:
        outcome = await asyncio.to_thread(detect_with_opencv, frame, camera)

    # normalise + threshold
    minimum = float(settings.detection_min_confidence)
    cleaned: list[dict] = []
    for detection in outcome.get("detections", []):
        confidence = float(detection.get("confidence") or 0)
        if confidence < minimum:
            continue
        cleaned.append(
            {
                "violation_type": detection["violation_type"],
                "confidence": round(confidence, 3),
                "box": detection.get("box"),
                "reason": detection.get("reason", ""),
                "plate_text": (detection.get("plate_text") or "").upper(),
                "vehicle_type": detection.get("vehicle_type", ""),
            }
        )

    outcome["detections"] = cleaned
    outcome["camera_id"] = camera.get("camera_id")
    outcome["analysed_at"] = utcnow_iso()
    outcome["min_confidence"] = minimum
    return outcome


def reset_camera_state(camera_id: str) -> None:
    _previous_gray.pop(str(camera_id), None)
