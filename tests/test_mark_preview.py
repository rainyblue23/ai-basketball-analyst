from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aihoop.mark_preview import ensure_mark_preview, preview_path


def test_preview_falls_back_without_gpu_and_reuses_valid_source_cache(tmp_path):
    source=tmp_path/'match.mp4';source.write_bytes(b'original')
    root=tmp_path/'cache';commands=[]
    def run(command, **kwargs):
        commands.append(command)
        if 'h264_nvenc' in command:
            return SimpleNamespace(returncode=1,stderr='no GPU encoder')
        Path(command[-1]).write_bytes(b'preview')
        return SimpleNamespace(returncode=0,stderr='')
    with patch('aihoop.mark_preview.subprocess.run',side_effect=run):
        result=ensure_mark_preview(source,root)
        assert result.read_bytes()==b'preview'
        assert source.read_bytes()==b'original'
        assert ensure_mark_preview(source,root)==result
    assert len(commands)==2
    assert '-movflags' in commands[-1] and '+faststart' in commands[-1]
    source.write_bytes(b'updated-original')
    assert preview_path(source,root)!=result
