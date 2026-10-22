"""Give OpenCV an H.264 copy when it cannot decode an uploaded video."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path


def _readable(path: Path) -> bool:
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        return bool(ok and frame is not None and frame.size)
    finally:
        cap.release()


def ensure_cv2_decodable(video: str, cache_root: str | Path | None = None) -> str:
    """Return original path or an atomic, reusable H.264 conversion.

    The copy keeps the original basename and frame size so video-bound
    calibration still matches. The source file remains untouched.
    """
    source = Path(video).resolve()
    if not source.is_file():
        raise RuntimeError(f"视频不存在：{source}")
    if _readable(source):
        return str(source)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"OpenCV 无法解码 {source.name}，且未安装 ffmpeg")
    root = Path(cache_root) if cache_root else Path(__file__).resolve().parents[2] / "data/compatible"
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    target_name = source.name if source.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"} else source.stem + ".mp4"
    target = root / digest.hexdigest()[:16] / target_name
    if target.is_file() and _readable(target):
        target.chmod(0o600)
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.mp4")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
               "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", "-vsync", "0",
               str(temporary)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
        if result.returncode or not temporary.is_file() or not _readable(temporary):
            raise RuntimeError(f"视频转码失败：{source.name}：{result.stderr[-500:]}")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


_preview_locks = {}


def ensure_cv2_preview(video: str) -> str:
    """Low-resolution decode cache for shot boundaries; full-resolution analysis is separate."""
    import threading
    source = Path(video).resolve()
    stat = source.stat()
    key = hashlib.sha256(f'{source}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:20]
    root = Path(__file__).resolve().parents[2] / 'data/compatible-preview'
    target = root / (key + '.mp4')
    if target.exists():
        return str(target)
    if _readable(source):
        return str(source)
    lock = _preview_locks.setdefault(key, threading.Lock())
    with lock:
        if target.exists():
            return str(target)
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / (key + '-' + uuid.uuid4().hex + '.mp4')
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise RuntimeError('缺少 FFmpeg，无法读取视频分镜')
        command = [ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(source),
                   '-an','-vf','scale=480:-2,fps=8','-c:v','libx264','-preset','ultrafast',
                   '-crf','28',str(temporary)]
        try:
            result = subprocess.run(command,capture_output=True,text=True,timeout=300)
            if result.returncode or not _readable(temporary):
                raise RuntimeError('分镜预览解码失败：'+result.stderr[-200:])
            temporary.chmod(0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return str(target)
