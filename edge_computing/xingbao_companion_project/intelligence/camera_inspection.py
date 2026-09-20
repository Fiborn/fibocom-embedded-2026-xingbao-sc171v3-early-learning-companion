"""On-demand, in-memory snapshots for Qwen camera inspection."""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import cv2
import numpy as np


CAMERA_STREAM_URL = "http://127.0.0.1:4445/?action=stream"
MAX_IMAGE_EDGE = 1024
JPEG_QUALITY = 80


@dataclass(frozen=True)
class CameraSnapshot:
    data_uri: str
    width: int
    height: int


class CameraInspectionError(RuntimeError):
    """A short stable reason for a failed on-demand camera inspection."""


def fetch_reference_image(
    url: str,
    *,
    http,
    proxies: dict[str, str],
    timeout_seconds: float = 15.0,
) -> CameraSnapshot:
    """Download one bounded public image and normalize it for the touch UI."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CameraInspectionError("invalid_reference_image_url")
    try:
        response = http.get(url, proxies=proxies, timeout=timeout_seconds, stream=True)
        if not bool(response.ok):
            raise CameraInspectionError("reference_image_http_error")
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > 1024 * 1024:
                raise CameraInspectionError("reference_image_too_large")
            chunks.append(chunk)
    except CameraInspectionError:
        raise
    except Exception as exc:
        raise CameraInspectionError("reference_image_download_failed") from exc
    frame = cv2.imdecode(np.frombuffer(b"".join(chunks), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or not getattr(frame, "size", 0):
        raise CameraInspectionError("reference_image_invalid")
    return _encode_snapshot(frame)


def search_reference_image(
    query: str,
    *,
    http,
    proxies: dict[str, str],
    timeout_seconds: float = 15.0,
) -> CameraSnapshot:
    """Use Baidu's structured image results for the exact requested subject."""
    subject = _reference_subject(query)
    try:
        response = http.get(
            "https://image.baidu.com/search/acjson",
            params={
                "tn": "resultjson_com",
                "ipn": "rj",
                "word": subject,
                "rn": "10",
            },
            headers={"User-Agent": "Mozilla/5.0 XingbaoCompanion/1.0"},
            proxies=proxies,
            timeout=timeout_seconds,
        )
        if not bool(response.ok):
            raise CameraInspectionError("reference_image_search_http_error")
        results = response.json().get("data") or []
        image_url = next(
            (
                item.get("thumbURL")
                for item in results
                if isinstance(item, dict) and isinstance(item.get("thumbURL"), str)
            ),
            "",
        )
        if not isinstance(image_url, str) or not image_url:
            raise CameraInspectionError("reference_image_not_found")
    except CameraInspectionError:
        raise
    except Exception as exc:
        raise CameraInspectionError("reference_image_search_failed") from exc
    return fetch_reference_image(image_url, http=http, proxies=proxies, timeout_seconds=timeout_seconds)


def _reference_subject(query: str) -> str:
    """Remove spoken request wording so the search term names the object only."""
    subject = re.sub(r"\s+", "", str(query or ""))
    subject = re.sub(
        r"(长什么样|长啥样|是什么样子|看看?(图片|样子)|给我看(看)?(图片|样子)|"
        r"把.*?(图片|样子).*)[？?。！!]*$",
        "",
        subject,
    )
    return subject.strip("，,。！？?!") or str(query or "").strip()


def capture_current_camera_frame(
    source: str = CAMERA_STREAM_URL,
    timeout_seconds: float = 2.0,
) -> CameraSnapshot:
    """Read one valid stream frame, encode it in memory, then release capture."""
    capture = cv2.VideoCapture(source)
    deadline = time.monotonic() + max(0.01, float(timeout_seconds))
    try:
        while time.monotonic() < deadline:
            ok, frame = capture.read()
            if ok and frame is not None and getattr(frame, "size", 0):
                return _encode_snapshot(frame)
        raise CameraInspectionError("camera_frame_timeout")
    finally:
        capture.release()


def _encode_snapshot(frame) -> CameraSnapshot:
    height, width = frame.shape[:2]
    longest_edge = max(width, height)
    if longest_edge > MAX_IMAGE_EDGE:
        scale = float(MAX_IMAGE_EDGE) / float(longest_edge)
        width = max(1, int(round(width * scale)))
        height = max(1, int(round(height * scale)))
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
    )
    if not ok:
        raise CameraInspectionError("camera_jpeg_encode_failed")
    data_uri = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
    return CameraSnapshot(data_uri=data_uri, width=width, height=height)
