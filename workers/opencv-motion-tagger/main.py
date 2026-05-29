"""
OpenCV Motion Tagger — ESPAI Worker

Detects and tags motion in images, image sequences, or video files.

Inputs (via ESPAI_INPUTS JSON):
  path          - single image, video file, or directory of frames  (required)
  threshold     - minimum contour area in pixels to count as motion (default: 500)
  blur_kernel   - Gaussian blur kernel size for noise reduction      (default: 21)
  max_frames    - max video frames to analyse                        (default: 300)
  output_dir    - where to write thumbnails                          (optional)

Outputs (JSON to stdout):
  ok            - bool
  path          - input path analysed
  source_type   - "image" | "video" | "sequence"
  motion_events - list of {frame, timestamp_s, regions:[{x,y,w,h,area}], score}
  total_frames  - frames analysed
  motion_frames - frames with motion detected
  peak_score    - highest single-frame motion score (0.0–1.0)
  thumbnail     - path of the first motion-frame thumbnail (or None)
  thumbnails    - list of thumbnail paths (up to 5)
  tags          - ["motion_detected"] or []
  events        - ESPAI event list (emitted by runner)
  error         - set on failure
"""
import json
import os
import sys
from pathlib import Path

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm"}


def _is_image(p: Path) -> bool:
    return p.suffix.lower() in _IMAGE_EXT


def _is_video(p: Path) -> bool:
    return p.suffix.lower() in _VIDEO_EXT


def _blur_and_gray(cv2, frame, blur_kernel: int):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)


def _diff_score(cv2, np, ref, cur) -> float:
    """Fraction of pixels that changed significantly."""
    delta = cv2.absdiff(ref, cur)
    _, thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)
    return float(np.count_nonzero(thresh)) / thresh.size


def _find_regions(cv2, np, ref, cur, threshold_area: int) -> list[dict]:
    """Return bounding boxes of changed regions above threshold_area."""
    delta = cv2.absdiff(ref, cv2.GaussianBlur(cur, (3, 3), 0))
    _, thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        area = int(cv2.contourArea(c))
        if area >= threshold_area:
            x, y, w, h = cv2.boundingRect(c)
            regions.append({"x": x, "y": y, "w": w, "h": h, "area": area})
    return regions


def _save_thumbnail(cv2, frame, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frame.shape[:2]
    if w > 640:
        scale = 640 / w
        frame = cv2.resize(frame, (640, int(h * scale)))
    cv2.imwrite(str(out_path), frame)
    return str(out_path)


def analyse_video(cv2, np, path: Path, threshold: int, blur_kernel: int,
                  max_frames: int, output_dir: Path | None) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"ok": False, "error": f"Cannot open video: {path}"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    motion_events, thumbnails = [], []
    frame_idx = 0
    prev_bg = None

    while frame_idx < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        cur = _blur_and_gray(cv2, frame, blur_kernel)
        if prev_bg is None:
            prev_bg = cur
            frame_idx += 1
            continue

        regions = _find_regions(cv2, np, prev_bg, cur, threshold)
        if regions:
            score = _diff_score(cv2, np, prev_bg, cur)
            thumb = None
            if output_dir and len(thumbnails) < 5:
                out = output_dir / f"motion_{frame_idx:06d}.jpg"
                thumb = _save_thumbnail(cv2, frame, out)
                thumbnails.append(thumb)
            motion_events.append({
                "frame": frame_idx,
                "timestamp_s": round(frame_idx / fps, 3),
                "regions": regions,
                "score": round(score, 4),
            })
        prev_bg = cur
        frame_idx += 1

    cap.release()
    analysed = min(frame_idx, max_frames)
    return {
        "ok": True,
        "source_type": "video",
        "total_frames": analysed,
        "motion_frames": len(motion_events),
        "motion_events": motion_events[:50],   # cap JSON size
        "peak_score": round(max((e["score"] for e in motion_events), default=0.0), 4),
        "thumbnail": thumbnails[0] if thumbnails else None,
        "thumbnails": thumbnails,
        "tags": ["motion_detected"] if motion_events else [],
    }


def analyse_sequence(cv2, np, frames: list[Path], threshold: int, blur_kernel: int,
                     output_dir: Path | None) -> dict:
    motion_events, thumbnails = [], []
    prev_bg = None
    for idx, img_path in enumerate(sorted(frames)):
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        cur = _blur_and_gray(cv2, frame, blur_kernel)
        if prev_bg is None:
            prev_bg = cur
            continue
        regions = _find_regions(cv2, np, prev_bg, cur, threshold)
        if regions:
            score = _diff_score(cv2, np, prev_bg, cur)
            thumb = None
            if output_dir and len(thumbnails) < 5:
                out = output_dir / f"motion_{idx:06d}.jpg"
                thumb = _save_thumbnail(cv2, frame, out)
                thumbnails.append(thumb)
            motion_events.append({
                "frame": idx,
                "timestamp_s": None,
                "path": str(img_path),
                "regions": regions,
                "score": round(score, 4),
            })
        prev_bg = cur

    return {
        "ok": True,
        "source_type": "sequence",
        "total_frames": len(frames),
        "motion_frames": len(motion_events),
        "motion_events": motion_events[:50],
        "peak_score": round(max((e["score"] for e in motion_events), default=0.0), 4),
        "thumbnail": thumbnails[0] if thumbnails else None,
        "thumbnails": thumbnails,
        "tags": ["motion_detected"] if motion_events else [],
    }


def analyse_image(cv2, np, path: Path, threshold: int, blur_kernel: int,
                  output_dir: Path | None) -> dict:
    """
    Single-image analysis: apply background subtractor seed then detect edges
    as a proxy for motion regions (useful for ESP32-CAM snapshots with a
    clean background expectation).
    """
    frame = cv2.imread(str(path))
    if frame is None:
        return {"ok": False, "error": f"Cannot read image: {path}"}

    gray    = _blur_and_gray(cv2, frame, blur_kernel)
    # Use Canny edge density as a motion-proxy for single images
    edges   = cv2.Canny(gray, 50, 150)
    density = float(np.count_nonzero(edges)) / edges.size
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        area = int(cv2.contourArea(c))
        if area >= threshold:
            x, y, w, h = cv2.boundingRect(c)
            regions.append({"x": x, "y": y, "w": w, "h": h, "area": area})

    thumbnails = []
    if output_dir and regions:
        out = output_dir / f"motion_single.jpg"
        thumb = _save_thumbnail(cv2, frame, out)
        thumbnails.append(thumb)

    motion_events = []
    if regions:
        motion_events.append({
            "frame": 0,
            "timestamp_s": 0.0,
            "regions": regions[:20],
            "score": round(density, 4),
        })

    return {
        "ok": True,
        "source_type": "image",
        "total_frames": 1,
        "motion_frames": 1 if motion_events else 0,
        "motion_events": motion_events,
        "peak_score": round(density, 4),
        "thumbnail": thumbnails[0] if thumbnails else None,
        "thumbnails": thumbnails,
        "tags": ["motion_detected"] if motion_events else [],
    }


def run(inputs: dict) -> dict:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Missing dependency: {exc}. Install: pip install opencv-python numpy",
            "tags": [],
        }

    raw_path = inputs.get("path")
    if not raw_path:
        return {"ok": False, "error": "Input 'path' is required", "tags": []}

    path       = Path(raw_path)
    threshold  = int(inputs.get("threshold", 500))
    blur_kernel = int(inputs.get("blur_kernel", 21))
    max_frames = int(inputs.get("max_frames", 300))
    output_dir = Path(inputs["output_dir"]) if inputs.get("output_dir") else None

    if not path.exists():
        return {"ok": False, "error": f"Path not found: {path}", "tags": []}

    if path.is_dir():
        frames = [f for f in sorted(path.iterdir()) if _is_image(f)]
        if not frames:
            return {"ok": False, "error": f"No image files in directory: {path}", "tags": []}
        result = analyse_sequence(cv2, np, frames, threshold, blur_kernel, output_dir)
    elif _is_video(path):
        result = analyse_video(cv2, np, path, threshold, blur_kernel, max_frames, output_dir)
    elif _is_image(path):
        result = analyse_image(cv2, np, path, threshold, blur_kernel, output_dir)
    else:
        return {"ok": False, "error": f"Unsupported file type: {path.suffix}", "tags": []}

    result["path"] = str(path)

    # Build ESPAI event list for runner to publish
    if result.get("tags"):
        result["events"] = [{
            "event_type": "motion_detected",
            "source":     "opencv-motion-tagger",
            "payload": {
                "path":         result["path"],
                "source_type":  result.get("source_type"),
                "motion_frames":result.get("motion_frames", 0),
                "peak_score":   result.get("peak_score", 0.0),
            },
        }]
    else:
        result["events"] = []

    return result


if __name__ == "__main__":
    raw = os.environ.get("ESPAI_INPUTS", "{}")
    try:
        inputs = json.loads(raw)
    except json.JSONDecodeError:
        inputs = {}

    result = run(inputs)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)
