"""Validated, reproducible legacy detector profiles; no outcome-rule overrides."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

class RimRefinementOptions(BaseModel):
    contour_diagnostics: bool = False
    min_width_ratio: float = Field(.5, gt=0, le=2)
    max_width_ratio: float = Field(1.5, gt=0, le=3)
    min_width_px: int = Field(6, ge=3, le=100)
    min_aspect: float = Field(1.8, ge=1, le=10)
    max_aspect: float = Field(9., ge=1, le=20)
    min_color_fill: float = Field(.08, ge=0, le=1)
    max_color_fill: float = Field(.8, ge=0, le=1)
    center_offset_ratio: float = Field(.4, ge=0, le=2)
    vertical_margin_ratio: float = Field(.5, ge=0, le=2)
    top_offset_ratio: float = Field(.45, ge=0, le=1)
    @model_validator(mode='after')
    def ordered_ranges(self):
        if (self.min_width_ratio > self.max_width_ratio or self.min_aspect > self.max_aspect
                or self.min_color_fill > self.max_color_fill):
            raise ValueError('Refinement minimums must not exceed maximums')
        return self
    class Config:
        extra = "forbid"

class ShotEvidenceOptions(BaseModel):
    release_binding_mode: Literal['contact_sequence','legacy_nearest_feet'] = 'contact_sequence'
    ball_geometry_mode: Literal['measured','median3'] = 'measured'
    release_lookback_s: float = Field(2.,gt=0,le=4.)
    release_min_contact_frames: int = Field(2,ge=2,le=10)
    release_min_departure_frames: int = Field(2,ge=2,le=10)
    release_contact_max_gap_s: float = Field(.25,gt=0,le=.5)
    release_departure_max_gap_s: float = Field(.25,gt=0,le=.5)
    release_ambiguity_s: float = Field(.1,ge=0,le=1.)
    release_contact_x_pad_ratio: float = Field(.25,ge=0,le=.5)
    release_contact_top_ratio: float = Field(-.2,ge=-.5,le=.3)
    release_contact_bottom_ratio: float = Field(.75,ge=.4,le=.9)
    class Config:
        extra = 'forbid'

class GeneralVisionOptions(BaseModel):
    adaptive_ball: bool = False
    dynamic_rim: bool = False
    camera_feature_cache: bool = False
    camera_demand_only: bool = False
    release_shadow: bool = False
    role_shadow: bool = False
    replay_shadow: bool = False
    adaptive_min_side_px: float = Field(2.,ge=2,le=4)
    adaptive_max_short_side_ratio: float = Field(.22,gt=0,le=.35)
    adaptive_person_height_ratio: float = Field(.22,gt=0,le=.4)
    adaptive_rim_width_ratio: float = Field(.9,gt=0,le=2)
    adaptive_growth_ratio: float = Field(1.6,ge=1,le=2)
    adaptive_support_frames: int = Field(3,ge=3,le=8)
    adaptive_window_s: float = Field(.3,gt=0,le=.5)
    adaptive_motion_px: float = Field(2.,gt=0,le=20)
    camera_max_side: int = Field(640,ge=320,le=960)
    camera_min_matches: int = Field(20,ge=12,le=100)
    camera_min_ratio: float = Field(.6,ge=.45,le=1)
    camera_min_grid_cells: int = Field(4,ge=3,le=6)
    camera_max_scale_change: float = Field(.25,gt=0,le=.5)
    rim_prediction_s: float = Field(.25,gt=0,le=.5)
    rim_measurement_alpha: float = Field(1.,gt=0,le=1)
    release_window_s: float = Field(1.2,gt=.2,le=3)
    release_contact_bottom: float = Field(.55,ge=.3,le=.75)
    release_context_s: float = Field(.7,gt=.2,le=1.5)
    release_gap_s: float = Field(.25,gt=0,le=.5)
    release_repossession_frames: int = Field(4,ge=3,le=10)
    release_strong_contact_frames: int = Field(3,ge=2,le=10)
    release_prior_free_frames: int = Field(3,ge=3,le=10)
    release_rise_body_ratio: float = Field(.12,gt=0,le=.5)
    near_rim_widths: float = Field(4.,gt=0,le=8)
    role_min_votes: int = Field(3,ge=2,le=10)
    role_iou: float = Field(.5,gt=0,le=1)
    role_detector_conf: float = Field(.6,ge=.4,le=1)
    replay_hamming: int = Field(5,ge=0,le=12)
    replay_min_motion: int = Field(4,ge=2,le=20)
    @model_validator(mode='after')
    def validate_shadow_dependencies(self):
        if self.replay_shadow and not self.release_shadow:
            raise ValueError('replay_shadow requires release_shadow candidate input')
        return self
    class Config:
        extra = 'forbid'


class LegacyDetectOptions(BaseModel):
    general: GeneralVisionOptions = Field(default_factory=GeneralVisionOptions)
    shot_evidence: ShotEvidenceOptions = Field(default_factory=ShotEvidenceOptions)
    ball_conf: float = Field(.25, ge=.05, le=1.)
    ball_candidate_conf: float = Field(.25, ge=.05, le=1.)
    ball_low_conf_confirm: bool = False
    ball_low_conf_max_candidates: int = Field(16, ge=1, le=100)
    ball_low_conf_min_frames: int = Field(3, ge=3, le=10)
    ball_low_conf_window_s: float = Field(.25, gt=0, le=1.)
    ball_low_conf_min_motion_px: float = Field(2., gt=0, le=50.)
    ball_low_conf_near_rim_widths: float = Field(3., gt=0, le=10.)
    ball_candidate_nms_iou: float = Field(.5, gt=0, le=1.)
    ball_track_selected_only: bool = True
    ball_roi_max_per_frame: int = Field(2, ge=1, le=2)
    ball_roi_retry_hz: float = Field(5., gt=0, le=60.)
    ball_roi_imgsz: int = Field(640, ge=320, le=1280, multiple_of=32)
    ball_rim_roi_imgsz: int = Field(960, ge=320, le=1280, multiple_of=32)
    ball_roi_edge_guard: bool = False
    ball_roi_edge_margin_px: float = Field(2.,ge=0,le=16)
    scene_motion_guard: bool = True
    scene_motion_min_matches: int = Field(20, ge=8, le=300)
    scene_motion_min_ratio: float = Field(.45, gt=0, le=1.)
    scene_motion_min_grid_cells: int = Field(3, ge=3, le=6)
    scene_motion_min_points_per_cell: int = Field(3, ge=1, le=30)
    scene_motion_max_side: int = Field(640, ge=320, le=1280)
    ball_min_side_px: Optional[float] = Field(4., ge=2., le=32.)
    # Preserve the existing 57.6px ceiling at a >=960px source width. Expose it
    # for offline zoom/close-up comparisons, without changing shot rules.
    ball_max_reference_ratio: float = Field(.06, gt=0., le=.5)
    ball_filter_diagnostics: bool = False
    motion_ball_recovery: bool = True
    # Only refine coarse model 'hoop' regions; native rim/manual boxes remain intact.
    rim_refinement: bool = True
    rim_refinement_options: RimRefinementOptions = Field(default_factory=RimRefinementOptions)
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
    return dict(general=opt.general.model_dump(),
                imgsz=opt.imgsz if opt.imgsz is not None else (960 if night else 640),
                shot_evidence=opt.shot_evidence.model_dump(),
                rim_min_conf=opt.rim_min_conf if opt.rim_min_conf is not None else (.30 if night else .35),
                rim_low_conf_guard=True, hint_first_scene_only=True,
                ball_roi_recovery=opt.ball_roi_recovery, ball_rim_recovery=opt.ball_rim_recovery,
                ball_static_lock_s=opt.ball_static_lock_s,
                **{key:getattr(opt,key) for key in ('ball_conf','ball_candidate_conf',
                    'ball_low_conf_confirm','ball_low_conf_max_candidates','ball_low_conf_min_frames','ball_low_conf_window_s',
                    'ball_low_conf_min_motion_px','ball_low_conf_near_rim_widths','ball_candidate_nms_iou',
                    'ball_track_selected_only','ball_roi_max_per_frame','ball_roi_retry_hz','ball_roi_imgsz','ball_rim_roi_imgsz',
                    'ball_roi_edge_guard','ball_roi_edge_margin_px',
                    'scene_motion_guard','scene_motion_min_matches','scene_motion_min_ratio',
                    'scene_motion_min_grid_cells','scene_motion_min_points_per_cell','scene_motion_max_side')},
                ball_min_side_px=opt.ball_min_side_px,
                ball_max_reference_ratio=opt.ball_max_reference_ratio,
                ball_filter_diagnostics=opt.ball_filter_diagnostics,
                motion_ball_recovery=opt.motion_ball_recovery,
                rim_refinement=opt.rim_refinement,
                rim_refinement_options=opt.rim_refinement_options.model_dump())

def prediction_options(detect):
    # Candidate admission and final measured-ball confirmation are separate.
    # Lower floors do not bypass size, head, graphics or temporal checks.
    return dict(imgsz=detect['imgsz'], conf=min(detect.get('ball_candidate_conf',detect['ball_conf']), detect['ball_conf'], detect['rim_min_conf']), iou=.5)
