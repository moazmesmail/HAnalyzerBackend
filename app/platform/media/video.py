import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.platform.errors import ApiError


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float | None


def probe_video(path: Path) -> VideoMetadata:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        raise ApiError(422, "INVALID_VIDEO", "The uploaded file does not contain a decodable video stream.")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise ApiError(422, "INVALID_VIDEO", "The uploaded file does not contain a visual video stream.")

    raw_duration = (data.get("format") or {}).get("duration")
    duration = float(raw_duration) if raw_duration else None
    return VideoMetadata(duration_seconds=duration)


def create_silent_preview(source: Path, target: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-movflags",
        "+faststart",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        raise ApiError(500, "PREVIEW_FAILED", "Silent preview generation failed.")


def assert_no_audio_stream(path: Path) -> None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ApiError(500, "PREVIEW_FAILED", "Silent preview validation failed.")

    data = json.loads(result.stdout or "{}")
    if data.get("streams"):
        raise ApiError(500, "PREVIEW_HAS_AUDIO", "Generated preview contains audio.")
