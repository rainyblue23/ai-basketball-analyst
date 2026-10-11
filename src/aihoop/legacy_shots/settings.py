"""Validated, reproducible legacy detector profiles; no outcome-rule overrides."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

class LegacyDetectOptions(BaseModel):
    ball_roi_recovery: bool = False
    # 筐周围高分辨率复检球（第五轮）：ROI 开在**筐**上而不是球的预测位置。
    # 为什么需要单独一个开关：球被锁在静止误检上时，预测位置就是那个假目标（详见 sources.py 的调用处）。
    ball_rim_recovery: bool = False
    # 静止锁换锚阈值（秒，0=关）。第四轮实现、第五轮才看出它的用处：
    # 它单独用没用（实测指标一样），但和 ball_rim_recovery 组合才有意义 ——
    # 复检**提供**筐附近的真球候选，换锚**让**它顶掉那条锁在静止物上的轨迹。
    ball_static_lock_s: float = Field(0., ge=0., le=10.)
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
                rim_low_conf_guard=True, hint_first_scene_only=True,
                ball_roi_recovery=opt.ball_roi_recovery, ball_rim_recovery=opt.ball_rim_recovery,
                ball_static_lock_s=opt.ball_static_lock_s)

def prediction_options(detect):
    # Keep ball selection at .25; lowering the detector floor only admits rim candidates.
    return dict(imgsz=detect['imgsz'], conf=min(detect['ball_conf'], detect['rim_min_conf']), iou=.5)
