"""Cached browser H.264 preview for marking; original analysis video is untouched."""
import hashlib
import os
import subprocess
import threading
import uuid
from pathlib import Path

_locks = {}


def preview_path(video, root=None):
    source = Path(video).resolve()
    stat = source.stat()
    key = hashlib.sha256(f'v2:{source}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:24]
    root = Path(root) if root else Path(__file__).resolve().parents[2] / 'data/mark-preview'
    return root / (key + '.mp4')


def ensure_mark_preview(video, root=None):
    source = Path(video).resolve()
    target = preview_path(source, root)
    if target.is_file():
        return target
    with _locks.setdefault(str(target), threading.Lock()):
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name('.' + uuid.uuid4().hex + '.mp4')
        common = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                  '-map', '0:v:0', '-an', '-vf', "scale='trunc(min(1280,iw)/2)*2':-2",
                  '-pix_fmt', 'yuv420p', '-vsync', '0']
        # NVENC is optional: hosts without it retain the CPU encoder fallback.
        encoders = [
            ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', '30',
             '-b:v', '700k', '-maxrate', '1200k', '-bufsize', '2400k'],
            ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26',
             '-maxrate', '1800k', '-bufsize', '3600k']]
        try:
            for encoder in encoders:
                result = subprocess.run(common + encoder + ['-movflags', '+faststart', str(temporary)],
                                        capture_output=True, text=True, timeout=600)
                if result.returncode == 0 and temporary.is_file() and temporary.stat().st_size > 0:
                    temporary.chmod(0o600)
                    os.replace(temporary, target)
                    return target
            raise RuntimeError('标注预览生成失败：' + result.stderr[-300:])
        finally:
            temporary.unlink(missing_ok=True)
