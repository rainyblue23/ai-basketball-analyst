import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import ClientDisconnect

from aihoop.upload_chunks import receive_chunk


class Request:
    def __init__(self, offset=0, body=b'abcd', total=8, disconnect=False):
        self.headers = {'x-upload-id':'a'*32, 'x-upload-offset':str(offset),
                        'x-upload-size':str(total), 'x-upload-part-size':'4', 'x-filename':'%E6%AF%94%E8%B5%9B.mp4'}
        self.body = body
        self.disconnect = disconnect

    async def stream(self):
        yield self.body
        if self.disconnect:
            raise ClientDisconnect()


def test_chunks_retry_and_complete(tmp_path, monkeypatch):
    monkeypatch.setattr('aihoop.highlight.probe_info', lambda _p: {'duration':1})
    async def run():
        first = await receive_chunk(Request(), tmp_path, 'alice')
        assert first == {'complete':False, 'received':4}
        assert not list(tmp_path.glob('*.mp4'))
        assert await receive_chunk(Request(), tmp_path, 'alice') == first
        with pytest.raises(HTTPException) as bad:
            await receive_chunk(Request(body=b'wxyz'), tmp_path, 'alice')
        assert bad.value.status_code == 409
        final = await receive_chunk(Request(4,b'efgh'), tmp_path, 'alice')
        assert final['complete'] and Path(final['path']).read_bytes() == b'abcdefgh'
        assert await receive_chunk(Request(4,b'efgh'), tmp_path, 'alice') == final
        assert final['bytes']==8 and '比赛' in final['path']
    asyncio.run(run())


def test_interrupted_chunk_is_not_committed(tmp_path):
    async def run():
        with pytest.raises(HTTPException):
            await receive_chunk(Request(disconnect=True), tmp_path, 'alice')
        result = await receive_chunk(Request(), tmp_path, 'alice')
        assert result['received']==4
        other = await receive_chunk(Request(4,b'efgh'), tmp_path, 'bob')
        assert other['received']==4 and not other['complete']
        with pytest.raises(HTTPException) as too_big:
            await receive_chunk(Request(body=b'x'*(1024*1024+1),total=2000000), tmp_path, 'alice')
        assert too_big.value.status_code==413
    asyncio.run(run())


def test_out_of_order_parts_assemble_in_video_order(tmp_path, monkeypatch):
    monkeypatch.setattr('aihoop.highlight.probe_info', lambda _p: {})
    async def run():
        assert not (await receive_chunk(Request(4,b'efgh'),tmp_path,'alice'))['complete']
        result = await receive_chunk(Request(0,b'abcd'),tmp_path,'alice')
        assert Path(result['path']).read_bytes()==b'abcdefgh'
    asyncio.run(run())
