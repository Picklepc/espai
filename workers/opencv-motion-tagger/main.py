"""
OpenCV Motion Tagger — ESPAI Worker

Receives image/video paths via ESPAI_INPUTS environment variable.
Outputs a JSON object to stdout on completion.

Full implementation requires OpenCV (cv2) and numpy.
This file contains the stub scaffold — replace the body of `detect_motion`
with your actual detection logic.
"""
import json
import os
import sys


def detect_motion(inputs: dict) -> dict:
    """
    Stub: classify motion in an image or video file.
    Replace with real OpenCV logic.
    """
    try:
        import cv2  # noqa: F401
        # TODO: implement real motion detection
    except ImportError:
        return {
            "ok": False,
            "error": "opencv-python not installed — pip install opencv-python",
            "tags": [],
            "thumbnails": [],
        }

    media_path = inputs.get("path")
    if not media_path:
        return {"ok": False, "error": "No 'path' in inputs", "tags": []}

    # Placeholder result
    return {
        "ok": True,
        "path": media_path,
        "tags": ["motion_detected"],
        "confidence": 0.0,
        "thumbnails": [],
        "notes": "stub — replace with real OpenCV pipeline",
    }


if __name__ == "__main__":
    raw = os.environ.get("ESPAI_INPUTS", "{}")
    try:
        inputs = json.loads(raw)
    except json.JSONDecodeError:
        inputs = {}

    result = detect_motion(inputs)
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)
