"""Validated, reproducible legacy detector profiles; no outcome-rule overrides."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

class LegacyDetectOptions(BaseModel):
    profile: Literal["standard", "night"] = "standard"
    imgsz: Optional[int] = Field(None, ge=320, le=1280, multiple_of=32)
    rim_min_conf: Optional[float] = Field(None, ge=0.1, le=1.0)
    class Config:
        extra = "forbid"

def resolve_detect(value=None):
    opt = LegacyDetectOptions(**(value or {}))
    night = opt.profile == "night"
    return dict(imgsz=opt.imgsz if opt.imgsz is not None else (960 if night else 640),
                rim_min_conf=opt.rim_min_conf if opt.rim_min_conf is not None else (.30 if night else .35),
                rim_low_conf_guard=True, hint_first_scene_only=True)

def prediction_options(detect):
    # Keep ball selection at .25; lowering the detector floor only admits rim candidates.
    return dict(imgsz=detect['imgsz'], conf=min(detect['ball_conf'], detect['rim_min_conf']), iou=.5)
