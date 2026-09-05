import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.platform.errors import ApiError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float | None


@dataclass(frozen=True)
class ExtractedFrame:
    path: Path
    timestamp_seconds: float


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


def extract_sampled_frames(
    source: Path, target_dir: Path, sampling_fps: float, max_frames: int
) -> list[ExtractedFrame]:
    output_pattern = target_dir / "frame-%06d.jpg"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-vf",
        f"fps={sampling_fps},scale='min(512,iw)':-2,showinfo",
        "-frames:v",
        str(max_frames),
        "-q:v",
        "3",
        str(output_pattern),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logger.error(
            "ffmpeg_frame_extraction_failed return_code=%d stderr=%s",
            result.returncode,
            result.stderr[-4000:],
        )
        raise ApiError(500, "FRAME_EXTRACTION_FAILED", "Could not extract analysis frames.")

    paths = sorted(target_dir.glob("frame-*.jpg"))
    if not paths:
        logger.error("ffmpeg_frame_extraction_empty target_dir=%s", target_dir)
        raise ApiError(500, "FRAME_EXTRACTION_EMPTY", "No analysis frames were extracted.")

    logger.info(
        "ffmpeg_frame_extraction_completed frame_count=%d sampling_fps=%s",
        len(paths),
        sampling_fps,
    )

    timestamps = [float(value) for value in re.findall(r"pts_time:([-+0-9.eE]+)", result.stderr)]
    if len(timestamps) < len(paths):
        timestamps = [index / sampling_fps for index in range(len(paths))]
    return [
        ExtractedFrame(path=path, timestamp_seconds=timestamps[index])
        for index, path in enumerate(paths)
    ]


def probe_image_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.error("ffprobe_frame_failed return_code=%d stderr=%s", result.returncode, result.stderr[-2000:])
        raise ApiError(500, "FRAME_PROBE_FAILED", "Could not inspect an extracted frame.")
    streams = (json.loads(result.stdout or "{}").get("streams") or [])
    if not streams:
        raise ApiError(500, "FRAME_PROBE_FAILED", "Could not inspect an extracted frame.")
    return int(streams[0]["width"]), int(streams[0]["height"])
