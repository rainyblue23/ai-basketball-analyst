"""Locate provisioned OCR assets independently of a pinned code directory."""
import os
from pathlib import Path

OCR_FILES=('craft_mlt_25k.pth','english_g2.pth')


def ocr_model_directory(root=None,env_name='AIHOOP_SCOREBOARD_OCR_MODELS'):
    """Explicit paths are authoritative; shared data symlinks identify the project.

    A release under deploy/runtime/<revision> is not the owner of shared models.
    Do not search arbitrary parents, download weights, or silently ignore a bad
    explicit configuration.
    """
    configured=os.environ.get(env_name)
    if configured:return Path(configured).expanduser()
    root=Path(root) if root is not None else Path(__file__).resolve().parents[2]
    shared_root=(root/'data').resolve().parent if (root/'data').is_symlink() else root.resolve()
    candidates=[root/'models/easyocr',shared_root/'models/easyocr',
                shared_root.parent/'aihoop_assets/models/easyocr']
    for path in candidates:
        if all((path/name).is_file() for name in OCR_FILES):return path
    return candidates[-1]
