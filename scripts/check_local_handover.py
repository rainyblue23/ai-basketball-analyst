"""Read-only local handover audit for Windows development machines."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT.parent / "aihoop_assets"
REQUIRED_REPORTS = [
    "CV_SUMMARY_2026-10-16_2126_TO_2026-10-18.md",
    "CV_DELIVERY_2026-10-18_1946_TO_2135.md",
    "CV_GENERAL_STAGE1_2026-10-16.md",
    "CV_STAGE2_PART1_2026-10-18.md",
    "CV_REVIEW_SPARSE_2026-10-18.md",
    "CV_TACTICS_CONTINUITY_2026-10-18.md",
    "CV_CURRENT_JOB_A099_2026-10-17.md",
    "CV_ANNOTATION_PROTOCOL.md",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    result: dict[str, object] = {
        "root": str(ROOT),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "disk_free_gb": round(shutil.disk_usage(ROOT).free / 1024**3, 2),
        "ffmpeg": shutil.which("ffmpeg"),
        "node": shutil.which("node"),
    }
    modules = {}
    for name in ("torch", "cv2", "ultralytics", "numpy", "fastapi", "uvicorn", "pydantic", "httpx", "pytest"):
        try:
            module = importlib.import_module(name)
            modules[name] = getattr(module, "__version__", "installed")
        except Exception as exc:  # audit must report rather than crash
            modules[name] = f"missing: {type(exc).__name__}"
    result["modules"] = modules
    try:
        import torch
        result["cuda"] = {
            "available": bool(torch.cuda.is_available()),
            "torch_cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    except Exception:
        result["cuda"] = {"available": False}

    weights = []
    for rel in (
        "runs/detect/ball/weights/best.pt",
        "runs/detect/rim/weights/best.pt",
        "assets/models/rim_ball_v6.pt",
        "assets/models/rim_ball.pt",
        "assets/models/yolov8s.pt",
    ):
        candidates = [ROOT / rel, ASSETS / rel]
        if rel.startswith("assets/models/"):
            candidates.append(ASSETS / "models" / Path(rel).name)
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        weights.append({
            "path": str(path),
            "exists": path.exists(),
            "size_mb": round(path.stat().st_size / 1024**2, 2) if path.exists() else None,
            "sha256": sha256(path) if path.exists() else None,
        })
    result["weights"] = weights
    result["missing_handover_reports"] = [
        name for name in REQUIRED_REPORTS
        if not any(ROOT.rglob(name)) and not any(ASSETS.rglob(name))
    ]
    result["legacy_server_path_hits"] = []
    for folder in (ROOT / "src", ROOT / "scripts"):
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".ps1", ".bat", ".md"}:
                try:
                    if path.name != Path(__file__).name and "/data/projects" in path.read_text(encoding="utf-8", errors="ignore"):
                        result["legacy_server_path_hits"].append(str(path.relative_to(ROOT)))
                except OSError:
                    pass
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        result["git_head"] = completed.stdout.strip()
    except Exception as exc:
        result["git_head"] = f"unavailable: {exc}"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
