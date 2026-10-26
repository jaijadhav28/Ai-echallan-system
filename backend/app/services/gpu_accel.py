"""GPU / OpenCL acceleration helpers for camera and detection work.

The pip ``opencv-python`` wheels rarely ship NVIDIA CUDA kernels, but they do
include OpenCL. On Windows with an NVIDIA GPU that surfaces as ``NVD3D11``,
which is what we use for faster resize / colour convert / HOG / optical flow.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import cv2
import numpy as np

logger = logging.getLogger("rto.gpu")


@lru_cache(maxsize=1)
def gpu_status() -> dict:
    """Probe once what acceleration is available on this machine."""
    opencl = False
    opencl_device = ""
    try:
        opencl = bool(cv2.ocl.haveOpenCL())
        if opencl:
            try:
                cv2.ocl.setUseOpenCL(True)
            except Exception:  # noqa: BLE001
                pass
            try:
                opencl_device = str(cv2.ocl.Device.getDefault().name() or "")
            except Exception:  # noqa: BLE001
                opencl_device = "OpenCL device"
    except Exception:  # noqa: BLE001
        opencl = False

    cuda_devices = 0
    try:
        if hasattr(cv2, "cuda"):
            cuda_devices = int(cv2.cuda.getCudaEnabledDeviceCount() or 0)
    except Exception:  # noqa: BLE001
        cuda_devices = 0

    backend = "cpu"
    if cuda_devices > 0:
        backend = "cuda"
    elif opencl:
        backend = "opencl"

    return {
        "enabled": backend != "cpu",
        "backend": backend,
        "opencl": opencl,
        "opencl_device": opencl_device,
        "cuda_devices": cuda_devices,
        "opencv": cv2.__version__,
    }


def enable_gpu(prefer: bool = True) -> dict:
    """Turn OpenCL on/off for this process and return the active status."""
    status = dict(gpu_status())
    if not prefer:
        try:
            cv2.ocl.setUseOpenCL(False)
        except Exception:  # noqa: BLE001
            pass
        status["enabled"] = False
        status["backend"] = "cpu"
        status["preferred"] = False
        logger.info("GPU acceleration disabled — using CPU")
        return status

    status["preferred"] = True
    if status["opencl"]:
        try:
            cv2.ocl.setUseOpenCL(True)
            logger.info(
                "GPU acceleration ON via OpenCL (%s)",
                status["opencl_device"] or "default device",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not enable OpenCL: %s", exc)
            status["enabled"] = False
            status["backend"] = "cpu"
    elif status["cuda_devices"] > 0:
        logger.info("GPU acceleration ON via CUDA (%s device(s))", status["cuda_devices"])
    else:
        logger.warning("No OpenCL/CUDA device found — camera pipeline stays on CPU")
        status["enabled"] = False
        status["backend"] = "cpu"
    return status


def using_gpu() -> bool:
    from ..config import settings

    if not settings.use_gpu:
        return False
    status = gpu_status()
    return bool(status.get("enabled"))


def to_umat(frame: np.ndarray):
    """Upload a BGR frame to OpenCL memory when GPU mode is active."""
    if frame is None or not using_gpu():
        return frame
    try:
        return cv2.UMat(frame)
    except Exception:  # noqa: BLE001
        return frame


def from_umat(image) -> np.ndarray:
    if isinstance(image, cv2.UMat):
        return image.get()
    return image


def gpu_resize(frame: np.ndarray, size: tuple[int, int] | None = None, fx: float = 1.0, fy: float = 1.0):
    if using_gpu():
        try:
            src = to_umat(frame)
            if size is not None:
                return from_umat(cv2.resize(src, size))
            return from_umat(cv2.resize(src, None, fx=fx, fy=fy))
        except Exception:  # noqa: BLE001
            pass
    if size is not None:
        return cv2.resize(frame, size)
    return cv2.resize(frame, None, fx=fx, fy=fy)


def gpu_cvt_color(frame: np.ndarray, code: int) -> np.ndarray:
    if using_gpu():
        try:
            return from_umat(cv2.cvtColor(to_umat(frame), code))
        except Exception:  # noqa: BLE001
            pass
    return cv2.cvtColor(frame, code)


def gpu_rotate(frame: np.ndarray, rotate_code: int) -> np.ndarray:
    if using_gpu():
        try:
            return from_umat(cv2.rotate(to_umat(frame), rotate_code))
        except Exception:  # noqa: BLE001
            pass
    return cv2.rotate(frame, rotate_code)
