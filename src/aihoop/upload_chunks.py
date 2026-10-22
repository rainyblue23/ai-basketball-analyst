"""Bounded, retryable uploads; partial videos never appear in the upload library."""
import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException
from starlette.requests import ClientDisconnect

_locks = {}
MAX_CHUNK = 1024 * 1024


async def receive_chunk(request, directory: Path, owner: str):
    upload_id = request.headers.get('x-upload-id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', upload_id):
        raise HTTPException(400, '上传编号无效')
    try:
        offset = int(request.headers.get('x-upload-offset', '-1'))
        total = int(request.headers.get('x-upload-size', '0'))
    except ValueError:
        raise HTTPException(400, '上传大小无效')
    if offset < 0 or total <= 0 or offset >= total:
        raise HTTPException(400, '上传范围无效')
    name = unquote(request.headers.get('x-filename', 'video.mp4'))
    safe = ''.join(c for c in name if c.isalnum() or c in '._-') or 'video.mp4'
    ext = Path(safe).suffix
    if not ext or len(ext) > 8:
        ext = '.mp4'
    target = directory / (Path(safe).stem[:60] + '_' + upload_id[:10] + ext)
    staging = directory / '.chunks'
    staging.mkdir(parents=True, exist_ok=True)
    # Owner is included in the staging key so accounts cannot resume each other's upload.
    key = hashlib.sha256((owner + ':' + upload_id).encode()).hexdigest()
    target = directory / (Path(safe).stem[:60] + '_' + key[:16] + ext)
    meta_path = staging / (key + '.json')
    partial = staging / (key + '.part')
    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_CHUNK:
                raise HTTPException(413, '单块不能超过 1 MB')
    except ClientDisconnect:
        raise HTTPException(400, '当前上传块中断，可重试')
    if not body or offset + len(body) > total:
        raise HTTPException(400, '上传块大小无效')
    try:
        part_size = int(request.headers.get('x-upload-part-size', str(512 * 1024)))
    except ValueError:
        raise HTTPException(400, '上传块规格无效')
    if not 1 <= part_size <= MAX_CHUNK or offset % part_size or len(body) != min(part_size, total-offset):
        raise HTTPException(400, '上传块规格无效')
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta['total'] != total or meta['name'] != safe or meta.get('part_size',part_size) != part_size:
                raise HTTPException(409, '上传文件信息发生变化')
            target = Path(meta['path'])
        else:
            meta = {'total': total, 'name': safe, 'path': str(target), 'part_size':part_size}
            meta_path.write_text(json.dumps(meta))
        if target.exists():
            with target.open('rb') as file:
                file.seek(offset)
                if file.read(len(body)) != body:
                    raise HTTPException(409, '重复上传块的内容不一致')
            return {'complete':True, 'path':str(target), 'bytes':total, 'info':meta.get('info',{})}
        pieces = staging / key
        pieces.mkdir(exist_ok=True)
        piece = pieces / str(offset)
        if piece.exists():
            if piece.read_bytes() != body:
                raise HTTPException(409, '重复上传块的内容不一致')
        else:
            piece.write_bytes(body)
        received = sum(f.stat().st_size for f in pieces.iterdir())
        if received == total:
            with partial.open('wb') as output:
                for position in range(0,total,part_size):
                    part = pieces / str(position)
                    if not part.exists():
                        raise HTTPException(409, '缺少视频块')
                    output.write(part.read_bytes())
            partial.replace(target)
            from .highlight import probe_info
            try:
                info = probe_info(str(target))
            except Exception:
                info = {}
            meta['info'] = info
            meta_path.write_text(json.dumps(meta))
            for part in pieces.iterdir():
                part.unlink()
            pieces.rmdir()
            return {'complete':True, 'path':str(target), 'bytes':total, 'info':info}
        return {'complete':False, 'received':received}
