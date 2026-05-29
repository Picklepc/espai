"""
FFmpeg Compressor — ESPAI Worker

Compresses video files using FFmpeg, extracts a thumbnail, and returns metadata.
Requires ffmpeg and ffprobe on PATH (or set FFMPEG_PATH / FFPROBE_PATH env vars).

Inputs (via ESPAI_INPUTS JSON):
  path          - input video file path                              (required)
  output_path   - output file path; defaults to {stem}_compressed.mp4
  codec         - video codec: h264 | h265 | vp9 | copy             (default: h264)
  crf           - constant rate factor 0–51 (lower = better); h264 default 23
  preset        - encoding speed: ultrafast|superfast|veryfast|faster|fast|
                  medium|slow|slower|veryslow                        (default: fast)
  scale         - output resolution: 1080p|720p|480p|360p|original  (default: original)
  audio         - aac|mp3|copy|none                                  (default: aac)
  thumbnail     - extract a thumbnail image: true|false             (default: true)
  thumb_time    - seconds into video for thumbnail                   (default: 2.0)
  output_dir    - directory for output files; defaults to input dir

Outputs (JSON to stdout):
  ok            - bool
  input_path    - original file
  output_path   - compressed file
  thumbnail     - thumbnail path (or null)
  metadata      - {duration_s, width, height, fps, bitrate_kbps, codec}
  input_size_b  - input file size in bytes
  output_size_b - output file size in bytes
  compression_ratio - input_size / output_size
  events        - ESPAI event list
  error         - set on failure
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"


def _check_tool(binary: str) -> str | None:
    """Return None if binary is available, else an error string."""
    try:
        subprocess.run([binary, "-version"], capture_output=True, timeout=5)
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return f"{binary!r} not found on PATH. Install FFmpeg: https://ffmpeg.org/download.html"


def probe(path: Path) -> dict:
    """Return basic video metadata using ffprobe."""
    cmd = [
        _ffprobe_bin(), "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    fmt = data.get("format", {})
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})

    fps = 0.0
    fr = video.get("r_frame_rate", "0/1")
    if "/" in fr:
        num, den = fr.split("/")
        fps = round(float(num) / max(float(den), 1), 2)

    return {
        "duration_s":    round(float(fmt.get("duration", 0)), 2),
        "width":         video.get("width", 0),
        "height":        video.get("height", 0),
        "fps":           fps,
        "bitrate_kbps":  round(int(fmt.get("bit_rate", 0)) / 1000, 1),
        "codec":         video.get("codec_name", "unknown"),
    }


_SCALE_MAP = {
    "1080p": "1920:1080",
    "720p":  "1280:720",
    "480p":  "854:480",
    "360p":  "640:360",
}

_AUDIO_CODEC = {
    "aac":  ["-c:a", "aac", "-b:a", "128k"],
    "mp3":  ["-c:a", "libmp3lame", "-b:a", "128k"],
    "copy": ["-c:a", "copy"],
    "none": ["-an"],
}


def compress(path: Path, output_path: Path, codec: str, crf: int, preset: str,
             scale: str, audio: str) -> tuple[bool, str]:
    """Run ffmpeg. Returns (success, error_message)."""
    vf = []
    scale_filter = _SCALE_MAP.get(scale)
    if scale_filter:
        vf.append(f"scale={scale_filter}:force_original_aspect_ratio=decrease")

    if codec == "copy":
        video_args = ["-c:v", "copy"]
    elif codec == "h265":
        video_args = ["-c:v", "libx265", "-crf", str(crf), "-preset", preset,
                      "-tag:v", "hvc1"]
    elif codec == "vp9":
        video_args = ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0"]
    else:  # h264
        video_args = ["-c:v", "libx264", "-crf", str(crf), "-preset", preset]

    if vf:
        video_args += ["-vf", ",".join(vf)]

    audio_args = _AUDIO_CODEC.get(audio, _AUDIO_CODEC["aac"])

    cmd = [
        _ffmpeg_bin(), "-y", "-i", str(path),
        *video_args, *audio_args,
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr[-800:] if result.stderr else "ffmpeg returned non-zero exit"
        return False, err
    return True, ""


def extract_thumbnail(path: Path, thumb_path: Path, time_s: float) -> tuple[bool, str]:
    cmd = [
        _ffmpeg_bin(), "-y",
        "-ss", str(time_s),
        "-i", str(path),
        "-vframes", "1",
        "-q:v", "2",
        str(thumb_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return False, result.stderr[-400:] if result.stderr else "thumbnail failed"
    return True, ""


def run(inputs: dict) -> dict:
    err = _check_tool(_ffmpeg_bin())
    if err:
        return {"ok": False, "error": err}

    raw_path = inputs.get("path")
    if not raw_path:
        return {"ok": False, "error": "Input 'path' is required"}

    path = Path(raw_path)
    if not path.exists():
        return {"ok": False, "error": f"Input file not found: {path}"}

    codec   = inputs.get("codec", "h264")
    crf     = int(inputs.get("crf", 23))
    preset  = inputs.get("preset", "fast")
    scale   = inputs.get("scale", "original")
    audio   = inputs.get("audio", "aac")
    do_thumb = str(inputs.get("thumbnail", "true")).lower() != "false"
    thumb_time = float(inputs.get("thumb_time", 2.0))

    out_dir = Path(inputs["output_dir"]) if inputs.get("output_dir") else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    if inputs.get("output_path"):
        output_path = Path(inputs["output_path"])
    else:
        suffix = ".webm" if codec == "vp9" else ".mp4"
        output_path = out_dir / f"{path.stem}_compressed{suffix}"

    # Probe input metadata
    meta_in = probe(path)

    # Compress
    ok, compress_err = compress(path, output_path, codec, crf, preset, scale, audio)
    if not ok:
        return {"ok": False, "error": compress_err}

    # Thumbnail
    thumbnail = None
    if do_thumb and output_path.exists():
        thumb_path = out_dir / f"{path.stem}_thumb.jpg"
        tok, _ = extract_thumbnail(output_path, thumb_path, thumb_time)
        if tok and thumb_path.exists():
            thumbnail = str(thumb_path)

    # Probe output for final metadata
    meta_out = probe(output_path) if output_path.exists() else {}

    input_size  = path.stat().st_size
    output_size = output_path.stat().st_size if output_path.exists() else 0
    ratio = round(input_size / max(output_size, 1), 2)

    return {
        "ok": True,
        "input_path":        str(path),
        "output_path":       str(output_path),
        "thumbnail":         thumbnail,
        "metadata":          meta_out or meta_in,
        "input_size_b":      input_size,
        "output_size_b":     output_size,
        "compression_ratio": ratio,
        "events": [{
            "event_type": "media.compressed",
            "source":     "ffmpeg-compressor",
            "payload": {
                "input":  str(path),
                "output": str(output_path),
                "ratio":  ratio,
                "codec":  codec,
            },
        }],
    }


if __name__ == "__main__":
    raw = os.environ.get("ESPAI_INPUTS", "{}")
    try:
        inputs = json.loads(raw)
    except json.JSONDecodeError:
        inputs = {}

    result = run(inputs)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)
