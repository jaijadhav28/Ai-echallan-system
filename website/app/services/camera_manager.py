"""Multi-camera capture engine.

Every camera runs in its **own daemon thread** with its own capture handle,
reconnect loop and health counters, so two or three (or ten) cameras stream at
the same time and one camera failing never stops the others - a hard requirement
of this project.

Supported sources per camera:
  * ``LIVE`` - RTSP / IP camera / HTTP MJPEG (IP Webcam)
  * ``DEMO`` + ``SYNTHETIC`` - animated traffic scene (Camera 2)
  * Optional uploaded VIDEO / IMAGE file

The threads never touch the database or any HTTP API: they only produce frames.
Persistence (violations, alerts) happens in the asyncio pipeline, which keeps the
capture loop fast and the data layer single-threaded.
"""

from __future__ import annotations

import base64
import http.client
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import cv2
import numpy as np

from ..constants import (
    DEMO_SOURCE_IMAGE,
    DEMO_SOURCE_SYNTHETIC,
    DEMO_SOURCE_VIDEO,
    MODE_DEMO,
    MODE_LIVE,
    STATUS_CONNECTING,
    STATUS_DISABLED,
    STATUS_OFFLINE,
    STATUS_ONLINE,
)
from ..utils import utcnow_iso
from . import gpu_accel
from .synthetic import SyntheticTrafficSource

logger = logging.getLogger("rto.camera")

# Keep RTSP on TCP and give up on a dead stream instead of blocking forever.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;2000000|max_delay;500000|rw_timeout;2000000",
)

JPEG_QUALITY = 95
UHD_WIDTH = 3840
UHD_HEIGHT = 2160
TARGET_FPS = 30.0
HTTP_TARGET_FPS = 30.0
MAX_READ_FAILURES = 12
RECONNECT_BACKOFF = [1, 2, 3, 5, 8]
HTTP_CONNECT_TIMEOUT = 4.0
HTTP_READ_TIMEOUT = 8.0

# How long a failing camera may keep reporting CONNECTING while it retries.
# After this it stays OFFLINE so health and maintenance alerts do not flap.
OFFLINE_GRACE_SECONDS = 12.0

_PLACEHOLDER_SIZE = (540, 960, 3)
_PLACEHOLDER_URL_MARKERS = (
    "192.168.1.101",
    "192.168.1.102",
    "192.168.1.103",
    "username:password@",
)
_IP_WEBCAM_PORTS = {8080, 8081, 4747, 81}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _is_placeholder_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(marker in lowered for marker in _PLACEHOLDER_URL_MARKERS)


def invalid_ipv4_message(host: str) -> str:
    """Return a plain-language error when a dotted address has a number above 255."""
    raw = (host or "").strip().strip("[]")
    parts = raw.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts) and any(int(part) > 255 for part in parts):
        return (
            f"Camera address {raw} is not valid. "
            "Each number in an IP address must be from 0 to 255. "
            "Open Cameras and enter the address shown in the IP Webcam app."
        )
    return ""


def _host_port(value: str) -> tuple[str, int | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    if "://" in raw:
        parsed = urlparse(raw)
        return parsed.hostname or "", parsed.port
    if raw.count(":") == 1 and "/" not in raw:
        host, port_text = raw.split(":", 1)
        try:
            return host.strip(), int(port_text)
        except ValueError:
            return raw, None
    return raw, None


def build_stream_url(config: dict) -> str:
    """Compose LIVE stream URL for RTSP cameras or Android IP Webcam (HTTP MJPEG)."""
    url = (config.get("rtsp_url") or "").strip()
    username = (config.get("username") or "").strip()
    password = (config.get("password") or "").strip()
    ip_address = (config.get("ip_address") or "").strip()

    if ip_address and (not url or _is_placeholder_url(url)):
        if ip_address.lower().startswith(("http://", "https://", "rtsp://")):
            url = ip_address
        else:
            host, port = _host_port(ip_address)
            if not host:
                url = ""
            elif port in _IP_WEBCAM_PORTS:
                # Android IP Webcam (or similar) HTTP MJPEG endpoint.
                url = f"http://{host}:{port}/video"
            elif port is not None:
                url = f"rtsp://{host}:{port}/stream"
            else:
                # Bare IP with no port → standard RTSP, not IP Webcam.
                url = f"rtsp://{host}:554/stream"

    if not url and ip_address:
        host, port = _host_port(ip_address)
        if host and port in _IP_WEBCAM_PORTS:
            url = f"http://{host}:{port}/video"
        elif host:
            url = f"rtsp://{host}:{port or 554}/stream"

    if not url:
        return ""

    if username and "@" not in url.split("//", 1)[-1].split("/")[0]:
        parsed = urlparse(url)
        credentials = quote(username, safe="")
        if password:
            credentials += f":{quote(password, safe='')}"
        netloc = f"{credentials}@{parsed.netloc}"
        url = urlunparse(parsed._replace(netloc=netloc))
    return url


# Backwards-compatible alias used by older call sites / tests.
build_rtsp_url = build_stream_url


def redact_url(url: str) -> str:
    """Hide credentials before a URL is shown in the UI or a log line."""
    if not url or "@" not in url:
        return url
    scheme, _, rest = url.partition("//")
    credentials, _, host = rest.partition("@")
    user = credentials.split(":")[0]
    return f"{scheme}//{user}:****@{host}"


def resolve_source(config: dict) -> tuple[str, str]:
    """Return ``(kind, target)`` where kind is live|http|video|image|synthetic."""
    mode = (config.get("mode") or MODE_LIVE).upper()
    demo_type = (config.get("demo_source_type") or "").upper()
    path = (config.get("demo_source_path") or "").strip()

    if mode == MODE_DEMO:
        if demo_type == DEMO_SOURCE_VIDEO and path:
            return "video", path
        if demo_type == DEMO_SOURCE_IMAGE and path:
            return "image", path
        return "synthetic", ""

    stream = build_stream_url(config)
    if stream.lower().startswith(("http://", "https://")):
        return "http", stream
    return "live", stream


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _tune_ip_webcam(url: str) -> None:
    """Best-effort: push IP Webcam photo/video quality as high as the device allows."""
    parsed = urlparse(url)
    if not parsed.hostname:
        return
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    headers = {"User-Agent": "RTO-EChallan/1.0"}
    if parsed.username:
        headers["Authorization"] = _basic_auth_header(
            parsed.username, parsed.password or ""
        )

    def _get(path: str) -> None:
        conn = http.client.HTTPConnection(
            parsed.hostname, port, timeout=HTTP_CONNECT_TIMEOUT
        )
        try:
            conn.request("GET", path, headers=headers)
            conn.getresponse().read(256)
        finally:
            conn.close()

    try:
        # Max JPEG quality on the phone side (IP Webcam: 0–100).
        _get("/settings/quality?set=100")
        # Landscape 4K. Do not follow this with a smaller size — that overwrites 4K.
        for path in (
            "/settings/orientation?set=landscape",
            "/settings/video_orientation?set=landscape",
            "/settings/photo_size?set=3840x2160",
            "/settings/video_size?set=3840x2160",
        ):
            try:
                _get(path)
            except Exception:  # noqa: BLE001
                pass
        for path in (
            "/settings/ffc?set=off",
            "/settings/night_vision?set=off",
        ):
            try:
                _get(path)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 - optional optimisation
        pass


def draw_overlay(frame: np.ndarray, worker: "CameraWorker") -> np.ndarray:
    """Burn camera name, mode badge and timestamp into the frame."""
    canvas = frame
    height, width = canvas.shape[:2]
    # Scale chrome with the frame so a 4K picture keeps the same relative text size.
    top_h = max(36, height // 28)
    bot_h = max(28, height // 36)
    font = max(0.55, width / 1400)
    thick = 3 if width >= 3000 else 2 if width >= 1280 else 1

    cv2.rectangle(canvas, (0, 0), (width, top_h), (18, 20, 28), -1)
    cv2.rectangle(canvas, (0, height - bot_h), (width, height), (18, 20, 28), -1)

    name = f"{worker.config.get('camera_id', '')} | {worker.config.get('name', '')}"
    cv2.putText(
        canvas,
        name[:72],
        (12, int(top_h * 0.68)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font,
        (240, 240, 240),
        thick,
    )

    demo = (worker.config.get("mode") or MODE_LIVE).upper() == MODE_DEMO
    badge = "DEMO MODE" if demo else "LIVE"
    badge_colour = (0, 180, 255) if demo else (60, 200, 90)
    badge_width = int(150 * font) if demo else int(90 * font)
    y1, y2 = max(6, top_h // 5), top_h - max(6, top_h // 5)
    cv2.rectangle(
        canvas,
        (width - badge_width - 12, y1),
        (width - 10, y2),
        badge_colour,
        -1,
    )
    cv2.putText(
        canvas,
        badge,
        (width - badge_width - 4, int((y1 + y2) / 2 + 5 * font)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font * 0.85,
        (20, 20, 20),
        thick,
    )

    footer = (
        f"{worker.config.get('location', '') or 'Location not set'}   "
        f"{time.strftime('%d-%m-%Y %H:%M:%S')}   {worker.fps:.1f} FPS   "
        f"{width}x{height}"
    )
    cv2.putText(
        canvas,
        footer[:110],
        (12, height - max(8, bot_h // 3)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font * 0.72,
        (200, 205, 215),
        thick,
    )
    return canvas


def placeholder_frame(title: str, subtitle: str, colour=(30, 34, 46)) -> np.ndarray:
    frame = np.full(_PLACEHOLDER_SIZE, colour, dtype=np.uint8)
    cv2.putText(
        frame, title[:34], (60, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (235, 235, 240), 2
    )
    cv2.putText(
        frame, subtitle[:70], (60, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 160, 180), 1
    )
    return frame


def encode_jpeg(frame: np.ndarray) -> bytes | None:
    success, buffer = cv2.imencode(
        ".jpg",
        frame,
        [
            int(cv2.IMWRITE_JPEG_QUALITY),
            JPEG_QUALITY,
            int(cv2.IMWRITE_JPEG_OPTIMIZE),
            1,
        ],
    )
    return buffer.tobytes() if success else None


def ensure_landscape(frame: np.ndarray) -> np.ndarray:
    """Keep the video cast horizontal (16:9). The website screen stays vertical."""
    if frame is None or frame.size == 0:
        return frame
    height, width = frame.shape[:2]
    if height > width:
        frame = gpu_accel.gpu_rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        height, width = frame.shape[:2]
    target_ratio = 16.0 / 9.0
    current = width / float(height)
    if abs(current - target_ratio) < 0.03:
        return frame
    if current > target_ratio:
        new_h = max(1, int(round(width / target_ratio)))
        canvas = np.zeros((new_h, width, 3), dtype=frame.dtype)
        y = (new_h - height) // 2
        canvas[y : y + height, :] = frame
        return canvas
    new_w = max(1, int(round(height * target_ratio)))
    canvas = np.zeros((height, new_w, 3), dtype=frame.dtype)
    x = (new_w - width) // 2
    canvas[:, x : x + width] = frame
    return canvas


def present_uhd(frame: np.ndarray) -> np.ndarray:
    """Show 3840×2160 on the website. Keep a larger native frame as-is."""
    frame = ensure_landscape(frame)
    if frame is None or frame.size == 0:
        return frame
    height, width = frame.shape[:2]
    if width >= UHD_WIDTH and height >= UHD_HEIGHT:
        return frame
    interpolation = cv2.INTER_LANCZOS4 if width < UHD_WIDTH else cv2.INTER_AREA
    return cv2.resize(frame, (UHD_WIDTH, UHD_HEIGHT), interpolation=interpolation)


def _extract_mjpeg_frame(buffer: bytearray) -> bytes | None:
    """Pull one complete JPEG out of an MJPEG byte buffer (mutates buffer)."""
    # Prefer multipart Content-Length so we never cut the JPEG early.
    header_end = buffer.find(b"\r\n\r\n")
    if header_end >= 0:
        header = bytes(buffer[:header_end]).decode("latin-1", errors="ignore").lower()
        length = None
        for line in header.split("\r\n"):
            if line.startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = None
                break
        if length is not None and length > 0:
            start = header_end + 4
            if len(buffer) < start + length:
                return None
            jpeg = bytes(buffer[start : start + length])
            del buffer[: start + length]
            if buffer.startswith(b"\r\n"):
                del buffer[:2]
            if jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9") and len(jpeg) >= 500:
                return jpeg
            return None

    # Fallback: SOI → first plausible EOI (skip tiny false markers).
    start = buffer.find(b"\xff\xd8")
    if start < 0:
        if len(buffer) > 2:
            del buffer[:-2]
        return None
    if start > 0:
        del buffer[:start]
        start = 0

    search_from = 2
    while True:
        end = buffer.find(b"\xff\xd9", search_from)
        if end < 0:
            return None
        size = end + 2
        if size >= 2000:
            jpeg = bytes(buffer[:size])
            del buffer[:size]
            return jpeg
        search_from = end + 2


# --------------------------------------------------------------------------- #
# worker
# --------------------------------------------------------------------------- #
class CameraWorker(threading.Thread):
    """Captures frames from a single camera, forever, independently."""

    FINGERPRINT_FIELDS = (
        "mode",
        "rtsp_url",
        "ip_address",
        "username",
        "password",
        "demo_source_type",
        "demo_source_path",
        "enabled",
    )

    def __init__(self, config: dict):
        super().__init__(daemon=True, name=f"camera-{config.get('camera_id')}")
        self.config = dict(config)
        self.camera_id: str = str(config.get("camera_id"))
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._frame: np.ndarray | None = None
        self._ground_truth: dict = {}

        self.status = STATUS_CONNECTING
        self.last_error = ""
        self.last_frame_at: str | None = None
        self.last_seen: str | None = None
        self.offline_since: str | None = None
        self._offline_monotonic: float | None = None
        self.started_at = utcnow_iso()
        self.fps = 0.0
        self.frame_count = 0
        self.last_frame_monotonic: float | None = None
        self.reconnect_attempts = 0
        self.violation_count = 0
        self.detections_run = 0
        self.last_detection_at: str | None = None
        self.resolution = ""
        self.source_kind, target = resolve_source(self.config)
        self.source_label = redact_url(target) if self.source_kind == "live" else target

    # ------------------------------------------------------------------ #
    def fingerprint(self) -> tuple:
        return tuple(str(self.config.get(field, "")) for field in self.FINGERPRINT_FIELDS)

    def update_config(self, config: dict) -> None:
        """Apply changes that do not need the capture session to restart."""
        with self._lock:
            self.config.update(config)

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    def run(self) -> None:  # pragma: no cover - long running loop
        attempt = 0
        while not self._stop_event.is_set():
            try:
                self._publish_status_frame(STATUS_CONNECTING, "Connecting to source...")
                self._run_session()
                attempt = 0
            except Exception as exc:  # noqa: BLE001 - a camera must never crash the app
                text = str(exc).strip()
                if text.startswith("Camera address") or text.startswith("Cannot find camera"):
                    message = text
                elif "getaddrinfo" in text:
                    host = urlparse(self.source_label or "").hostname or (
                        self.config.get("ip_address") or ""
                    )
                    message = invalid_ipv4_message(host) or (
                        f"Cannot find camera address {host}. "
                        "Check the IP Webcam address and that this PC is on the same Wi-Fi."
                    )
                else:
                    message = f"{type(exc).__name__}: {text}"
                self._mark_offline(message)
                logger.warning("[%s] capture error: %s", self.camera_id, message)

            if self._stop_event.is_set():
                break

            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            self.reconnect_attempts += 1
            self._stop_event.wait(delay)

        self.status = STATUS_DISABLED
        logger.info("[%s] capture thread stopped", self.camera_id)

    # ------------------------------------------------------------------ #
    def _run_session(self) -> None:
        kind, target = resolve_source(self.config)
        self.source_kind = kind
        self.source_label = redact_url(target) if kind == "live" else target

        if kind == "synthetic":
            self._loop_synthetic()
        elif kind == "image":
            self._loop_image(target)
        elif kind == "video":
            self._loop_video(target)
        elif kind == "http":
            self._loop_http(target)
        else:
            self._loop_live(target)

    # -------------------------- source loops -------------------------- #
    def _loop_synthetic(self) -> None:
        source = SyntheticTrafficSource(camera_label=self.camera_id)
        interval = 1.0 / TARGET_FPS
        while not self._stop_event.is_set():
            started = time.time()
            frame, ground_truth = source.read()
            self._publish(frame, ground_truth)
            self._stop_event.wait(max(0.0, interval - (time.time() - started)))

    def _loop_http(self, url: str) -> None:
        """Android IP Webcam / HTTP MJPEG — avoids OpenCV hang on /video."""
        if not url:
            raise RuntimeError("No HTTP stream URL configured for this camera")

        _tune_ip_webcam(url)
        parsed = urlparse(url)
        if not parsed.hostname:
            raise RuntimeError(f"Invalid HTTP camera URL: {redact_url(url)}")
        problem = invalid_ipv4_message(parsed.hostname)
        if problem:
            raise RuntimeError(problem)

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/video"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        headers = {
            "User-Agent": "RTO-EChallan/1.0",
            "Connection": "keep-alive",
            "Accept": "multipart/x-mixed-replace,image/jpeg,*/*",
        }
        if parsed.username is not None:
            headers["Authorization"] = _basic_auth_header(
                parsed.username, parsed.password or ""
            )

        # shot.jpg is a complete JPEG per request — avoids corrupt MJPEG banding.
        ip_webcam = port in _IP_WEBCAM_PORTS or path.rstrip("/").endswith("/video")
        if ip_webcam:
            try:
                self._poll_http_shots(parsed.hostname, port, headers)
                return
            except Exception as shot_error:  # noqa: BLE001
                logger.info(
                    "[%s] shot.jpg failed (%s) — trying MJPEG",
                    self.camera_id,
                    shot_error,
                )

        self._stream_http_mjpeg(parsed.hostname, port, path, headers)

    def _stream_http_mjpeg(
        self, host: str, port: int, path: str, headers: dict
    ) -> None:
        conn = http.client.HTTPConnection(host, port, timeout=HTTP_CONNECT_TIMEOUT)
        try:
            conn.connect()
            conn.sock.settimeout(HTTP_READ_TIMEOUT)
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            if response.status >= 400:
                raise RuntimeError(
                    f"HTTP {response.status} from {host}:{port}{path}"
                )

            buffer = bytearray()
            failures = 0
            min_interval = 1.0 / HTTP_TARGET_FPS
            last_publish = 0.0
            while not self._stop_event.is_set():
                try:
                    chunk = response.read(16384)
                except socket.timeout:
                    failures += 1
                    if failures >= MAX_READ_FAILURES:
                        raise RuntimeError("IP Webcam stopped sending frames")
                    continue
                if not chunk:
                    raise RuntimeError("IP Webcam closed the video stream")
                failures = 0
                buffer.extend(chunk)
                # A 4K JPEG is often several megabytes. Cutting the buffer mid-frame
                # decodes as gray noise, so only drop bytes before the next JPEG start.
                if len(buffer) > 24_000_000:
                    start = buffer.rfind(b"\xff\xd8")
                    if start > 0:
                        del buffer[:start]
                    else:
                        del buffer[:-2]

                while True:
                    jpeg = _extract_mjpeg_frame(buffer)
                    if jpeg is None:
                        break
                    now = time.time()
                    if now - last_publish < min_interval:
                        continue
                    frame = cv2.imdecode(
                        np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
                    )
                    if frame is None or frame.shape[0] < 48 or frame.shape[1] < 48:
                        continue
                    last_publish = now
                    self._publish(frame, {"source": "HTTP_MJPEG"})
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def _poll_http_shots(self, host: str, port: int, headers: dict) -> None:
        interval = 1.0 / HTTP_TARGET_FPS
        failures = 0
        while not self._stop_event.is_set():
            started = time.time()
            try:
                conn = http.client.HTTPConnection(
                    host, port, timeout=HTTP_CONNECT_TIMEOUT
                )
                conn.request("GET", "/shot.jpg", headers=headers)
                response = conn.getresponse()
                data = response.read()
                conn.close()
                if response.status >= 400 or not data:
                    raise RuntimeError(f"shot.jpg HTTP {response.status}")
                if not (data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")):
                    raise RuntimeError("shot.jpg returned an incomplete JPEG")
                frame = cv2.imdecode(
                    np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if frame is None or frame.shape[0] < 48 or frame.shape[1] < 48:
                    raise RuntimeError("shot.jpg could not be decoded")
                failures = 0
                self._publish(frame, {"source": "HTTP_SHOT"})
            except Exception as exc:  # noqa: BLE001
                failures += 1
                if failures >= 2:
                    raise RuntimeError(f"IP Webcam shot.jpg failed: {exc}") from exc
            elapsed = time.time() - started
            self._stop_event.wait(max(0.0, interval - elapsed))

    def _loop_image(self, path: str) -> None:
        image = cv2.imread(path)
        if image is None:
            raise RuntimeError(f"Uploaded image could not be read: {Path(path).name}")
        while not self._stop_event.is_set():
            self._publish(image.copy(), {"source": "IMAGE", "path": path})
            self._stop_event.wait(1.0)

    def _loop_video(self, path: str) -> None:
        if not Path(path).exists():
            raise RuntimeError(f"Demo video not found: {path}")
        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            raise RuntimeError(f"OpenCV could not open the video file: {Path(path).name}")

        native_fps = capture.get(cv2.CAP_PROP_FPS) or TARGET_FPS
        interval = 1.0 / max(min(native_fps, 30.0), 5.0)
        try:
            failures = 0
            while not self._stop_event.is_set():
                success, frame = capture.read()
                if not success or frame is None:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop the clip
                    failures += 1
                    if failures > 3:
                        raise RuntimeError("Video file ended and could not be rewound")
                    continue
                failures = 0
                self._publish(frame, {"source": "VIDEO", "path": path})
                self._stop_event.wait(interval)
        finally:
            capture.release()

    def _loop_live(self, url: str) -> None:
        if not url:
            raise RuntimeError(
                "No RTSP URL or IP address configured for this camera in LIVE mode"
            )
        # OpenCV can block forever on bad RTSP — open with a short watchdog.
        capture = {"handle": None}

        def _open() -> None:
            capture["handle"] = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

        opener = threading.Thread(target=_open, daemon=True)
        opener.start()
        opener.join(HTTP_CONNECT_TIMEOUT + 2.0)
        if opener.is_alive() or capture["handle"] is None:
            raise RuntimeError(f"Timed out connecting to {redact_url(url)}")
        handle = capture["handle"]
        try:
            handle.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass
        if not handle.isOpened():
            handle.release()
            raise RuntimeError(f"Unable to connect to {redact_url(url)}")

        try:
            failures = 0
            while not self._stop_event.is_set():
                success, frame = handle.read()
                if not success or frame is None:
                    failures += 1
                    if failures >= MAX_READ_FAILURES:
                        raise RuntimeError("Stream stopped delivering frames")
                    self._stop_event.wait(0.2)
                    continue
                failures = 0
                self._publish(frame, {"source": "RTSP"})
        finally:
            handle.release()

    # ---------------------------- publishing -------------------------- #
    def _publish(self, frame: np.ndarray, ground_truth: dict) -> None:
        frame = present_uhd(frame)
        self.fps = TARGET_FPS
        self.last_frame_monotonic = time.time()
        self.frame_count += 1
        self.resolution = f"{frame.shape[1]}x{frame.shape[0]}"

        annotated = draw_overlay(frame.copy(), self)
        encoded = encode_jpeg(annotated)

        with self._lock:
            self._frame = frame
            self._ground_truth = ground_truth
            if encoded:
                self._jpeg = encoded

        self.status = STATUS_ONLINE
        self.last_error = ""
        self.offline_since = None
        self._offline_monotonic = None
        self.last_frame_at = utcnow_iso()
        self.last_seen = self.last_frame_at

    def _mark_offline(self, error: str) -> None:
        self.status = STATUS_OFFLINE
        self.last_error = error[:300]
        self.fps = 0.0
        if not self.offline_since:
            self.offline_since = utcnow_iso()
            self._offline_monotonic = time.monotonic()
        self._publish_status_frame(STATUS_OFFLINE, error)

    def _publish_status_frame(self, status: str, message: str) -> None:
        if status == STATUS_OFFLINE:
            frame = placeholder_frame(
                f"{self.camera_id} OFFLINE", message, colour=(28, 24, 46)
            )
        else:
            frame = placeholder_frame(f"{self.camera_id} CONNECTING", message)
        encoded = encode_jpeg(draw_overlay(frame, self))
        with self._lock:
            if encoded:
                self._jpeg = encoded
        if status == STATUS_CONNECTING and self.status != STATUS_ONLINE:
            failing_for = (
                time.monotonic() - self._offline_monotonic
                if self._offline_monotonic is not None
                else 0.0
            )
            if self.offline_since and failing_for >= OFFLINE_GRACE_SECONDS:
                self.status = STATUS_OFFLINE
            else:
                self.status = STATUS_CONNECTING

    # ------------------------------ reads ----------------------------- #
    def snapshot_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def snapshot_frame(self) -> tuple[np.ndarray | None, dict]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
            return frame, dict(self._ground_truth)

    def health(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "name": self.config.get("name"),
            "location": self.config.get("location"),
            "ip_address": self.config.get("ip_address"),
            "mode": (self.config.get("mode") or MODE_LIVE).upper(),
            "demo_source_type": self.config.get("demo_source_type"),
            "status": self.status,
            "online": self.status == STATUS_ONLINE,
            "fps": self.fps,
            "resolution": self.resolution,
            "frames_captured": self.frame_count,
            "last_frame_at": self.last_frame_at,
            "last_seen": self.last_seen,
            "offline_since": self.offline_since,
            "connection_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "violation_count": self.violation_count,
            "detections_run": self.detections_run,
            "last_detection_at": self.last_detection_at,
            "source_kind": self.source_kind,
            "source": self.source_label,
            "detection_enabled": bool(self.config.get("detection_enabled", True)),
            "thread_alive": self.is_alive(),
            "started_at": self.started_at,
        }


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #
class CameraManager:
    """Owns one :class:`CameraWorker` per enabled camera."""

    def __init__(self) -> None:
        self.workers: dict[str, CameraWorker] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def sync(self, cameras: list[dict]) -> dict:
        """Start, stop and restart workers so they match the database."""
        report = {"started": [], "stopped": [], "restarted": [], "running": []}
        wanted = {
            str(camera.get("camera_id")): camera
            for camera in cameras
            if camera.get("enabled", True)
        }

        with self._lock:
            for camera_id in list(self.workers):
                if camera_id not in wanted:
                    self.workers.pop(camera_id).stop()
                    report["stopped"].append(camera_id)

            for camera_id, camera in wanted.items():
                worker = self.workers.get(camera_id)
                if worker is None or not worker.is_alive():
                    self._start(camera)
                    report["started"].append(camera_id)
                    continue

                candidate = CameraWorker.FINGERPRINT_FIELDS
                changed = any(
                    str(worker.config.get(field, "")) != str(camera.get(field, ""))
                    for field in candidate
                )
                if changed:
                    worker.stop()
                    self._start(camera)
                    report["restarted"].append(camera_id)
                else:
                    worker.update_config(camera)
                    report["running"].append(camera_id)
        return report

    def _start(self, camera: dict) -> CameraWorker:
        worker = CameraWorker(camera)
        self.workers[str(camera.get("camera_id"))] = worker
        worker.start()
        logger.info(
            "[%s] capture thread started (%s)", worker.camera_id, worker.source_kind
        )
        return worker

    def restart(self, camera: dict) -> None:
        with self._lock:
            existing = self.workers.pop(str(camera.get("camera_id")), None)
            if existing:
                existing.stop()
            if camera.get("enabled", True):
                self._start(camera)

    def stop_camera(self, camera_id: str) -> None:
        with self._lock:
            worker = self.workers.pop(str(camera_id), None)
        if worker:
            worker.stop()

    def update_camera(self, camera: dict) -> None:
        with self._lock:
            worker = self.workers.get(str(camera.get("camera_id")))
            if worker:
                worker.update_config(camera)

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self.workers.values())
            self.workers.clear()
        for worker in workers:
            worker.stop()

    # ------------------------------------------------------------------ #
    def get(self, camera_id: str) -> CameraWorker | None:
        return self.workers.get(str(camera_id))

    def health_all(self) -> list[dict]:
        return [worker.health() for worker in list(self.workers.values())]

    def summary(self) -> dict:
        health = self.health_all()
        online = sum(1 for item in health if item["online"])
        return {
            "total_running": len(health),
            "online": online,
            "offline": len(health) - online,
            "average_fps": round(
                sum(item["fps"] for item in health) / len(health), 2
            )
            if health
            else 0.0,
        }


camera_manager = CameraManager()


# --------------------------------------------------------------------------- #
# connection test (blocking - callers run it in a threadpool)
# --------------------------------------------------------------------------- #
def test_camera_connection(config: dict, timeout: float = 12.0) -> dict:
    """Try to open a camera source and grab one frame."""
    kind, target = resolve_source(config)
    started = time.perf_counter()

    if kind == "synthetic":
        frame, _ = SyntheticTrafficSource().read()
        return {
            "ok": True,
            "mode": "DEMO",
            "source_kind": kind,
            "message": "Synthetic demo animation is ready.",
            "resolution": f"{frame.shape[1]}x{frame.shape[0]}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "source": "Built-in synthetic traffic animation",
        }

    if kind == "image":
        image = cv2.imread(target)
        ok = image is not None
        return {
            "ok": ok,
            "mode": "DEMO",
            "source_kind": kind,
            "message": "Image loaded." if ok else "Image file could not be read.",
            "resolution": f"{image.shape[1]}x{image.shape[0]}" if ok else "",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "source": Path(target).name,
        }

    if not target:
        return {
            "ok": False,
            "mode": "LIVE" if kind == "live" else "DEMO",
            "source_kind": kind,
            "message": "No RTSP URL / file configured for this camera.",
            "resolution": "",
            "latency_ms": 0,
            "source": "",
        }

    capture = (
        cv2.VideoCapture(target, cv2.CAP_FFMPEG)
        if kind == "live"
        else cv2.VideoCapture(target)
    )
    try:
        if not capture.isOpened():
            return {
                "ok": False,
                "mode": "LIVE" if kind == "live" else "DEMO",
                "source_kind": kind,
                "message": (
                    f"Could not connect to {redact_url(target)}. Check the IP address, "
                    "port, credentials and that the camera is on the same network."
                ),
                "resolution": "",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "source": redact_url(target),
            }

        frame = None
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            success, candidate = capture.read()
            if success and candidate is not None:
                frame = candidate
                break

        latency = int((time.perf_counter() - started) * 1000)
        if frame is None:
            return {
                "ok": False,
                "mode": "LIVE" if kind == "live" else "DEMO",
                "source_kind": kind,
                "message": "Connected, but no frame was received before the timeout.",
                "resolution": "",
                "latency_ms": latency,
                "source": redact_url(target),
            }

        return {
            "ok": True,
            "mode": "LIVE" if kind == "live" else "DEMO",
            "source_kind": kind,
            "message": "Connected and received a frame.",
            "resolution": f"{frame.shape[1]}x{frame.shape[0]}",
            "latency_ms": latency,
            "source": redact_url(target),
        }
    finally:
        capture.release()
