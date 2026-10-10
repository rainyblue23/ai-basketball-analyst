"""HoopAI 73792c6 CourtModel restored for the calibration UI.
Local ground coordinates are translated to aihoop full-court coordinates.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
@dataclass
class CourtModel:
    """球场几何模型 + 可用于标定的地面标志点表。"""

    name: str = "fiba"
    length_m: float = 28.0
    width_m: float = 15.0
    hoop_from_baseline_m: float = 1.575
    lane_w_m: float = 4.9
    lane_len_m: float = 5.8          # 底线到罚球线的距离
    ft_circle_r_m: float = 1.8
    three_r_m: float = 6.75
    three_corner_x_m: float = 6.60   # 底角三分线到中线的距离（= 半场宽 - 0.90m）
    restricted_r_m: float = 1.25

    # ---------------------------------------------------------------- 标志点
    @property
    def landmarks(self) -> dict[str, tuple[float, float]]:
        """可标定的地面点：名称 → 球场坐标(米)。都是地面上的点，便于在画面里点选。"""
        half_lane = self.lane_w_m / 2.0
        y_base = -self.hoop_from_baseline_m                 # 底线
        y_ft = self.lane_len_m - self.hoop_from_baseline_m  # 罚球线
        x3 = self.three_corner_x_m
        return {
            "lane_left_baseline": (-half_lane, y_base),
            "lane_right_baseline": (half_lane, y_base),
            "lane_left_ft": (-half_lane, y_ft),
            "lane_right_ft": (half_lane, y_ft),
            "three_left_corner": (-x3, y_base),
            "three_right_corner": (x3, y_base),
            "ft_circle_left": (-self.ft_circle_r_m, y_ft),
            "ft_circle_right": (self.ft_circle_r_m, y_ft),
            "hoop_ground": (0.0, 0.0),
        }

    @property
    def landmark_help(self) -> dict[str, str]:
        y_base = -self.hoop_from_baseline_m
        y_ft = self.lane_len_m - self.hoop_from_baseline_m
        return {
            "lane_left_baseline": f"限制区左角（边线与底线交点，地面），球场坐标({-self.lane_w_m/2:.2f},{y_base:.2f})",
            "lane_right_baseline": f"限制区右角（地面），({self.lane_w_m/2:.2f},{y_base:.2f})",
            "lane_left_ft": f"罚球线左端（与限制区左边线交点，地面），({-self.lane_w_m/2:.2f},{y_ft:.2f})",
            "lane_right_ft": f"罚球线右端（地面），({self.lane_w_m/2:.2f},{y_ft:.2f})",
            "three_left_corner": f"左侧底角三分线与底线交点（地面），({-self.three_corner_x_m:.2f},{y_base:.2f})",
            "three_right_corner": f"右侧底角三分线与底线交点（地面），({self.three_corner_x_m:.2f},{y_base:.2f})",
            "ft_circle_left": f"罚球圈左端点（地面），({-self.ft_circle_r_m:.2f},{y_ft:.2f})",
            "ft_circle_right": f"罚球圈右端点（地面），({self.ft_circle_r_m:.2f},{y_ft:.2f})",
            "hoop_ground": "篮筐正下方的地面点（⚠️ 不要点篮筐本身，篮筐在空中，点了会引入误差）",
        }

    @staticmethod
    def recommended_sets() -> dict[str, list[str]]:
        return {
            "key4": ["lane_left_baseline", "lane_right_baseline",
                     "lane_left_ft", "lane_right_ft"],
            "key6": ["lane_left_baseline", "lane_right_baseline",
                     "lane_left_ft", "lane_right_ft",
                     "three_left_corner", "three_right_corner"],
            "full": ["lane_left_baseline", "lane_right_baseline",
                     "lane_left_ft", "lane_right_ft",
                     "three_left_corner", "three_right_corner",
                     "ft_circle_left", "ft_circle_right"],
        }

    @staticmethod
    def set_descriptions() -> dict[str, str]:
        return {
            "key4": "限制区四个角点（最小可用，4 点）",
            "key6": "key4 + 两侧三分底角（推荐，6 点）",
            "full": "key6 + 罚球圈左右端点（8 点，最稳）",
        }

    # ------------------------------------------------------------ 绘图用折线
    def court_polylines(self) -> list[tuple[str, list[tuple[float, float]]]]:
        """返回球场线条（球场坐标），供俯视图绘制使用。"""
        yb = -self.hoop_from_baseline_m
        yft = self.lane_len_m - self.hoop_from_baseline_m
        half = self.lane_w_m / 2.0
        x3 = self.three_corner_x_m
        # 三分弧：从底角直线结束点开始的圆弧
        y_arc_start = math.sqrt(max(self.three_r_m ** 2 - x3 ** 2, 0.0))
        arc = []
        for i in range(61):
            y = y_arc_start + (yft + 3.0 - y_arc_start) * i / 60.0
            if y > self.three_r_m:
                break
            x = math.sqrt(max(self.three_r_m ** 2 - y ** 2, 0.0))
            arc.append((x, y))
        arc_up = [(x, y) for x, y in arc]
        arc_down = [(-x, y) for x, y in reversed(arc)]
        lines: list[tuple[str, list[tuple[float, float]]]] = [
            ("baseline", [(-self.width_m / 2, yb), (self.width_m / 2, yb)]),
            ("lane_left", [(-half, yb), (-half, yft)]),
            ("lane_right", [(half, yb), (half, yft)]),
            ("ft_line", [(-half, yft), (half, yft)]),
            ("three_left_corner", [(-x3, yb), (-x3, y_arc_start)]),
            ("three_right_corner", [(x3, yb), (x3, y_arc_start)]),
            ("three_arc", arc_up + arc_down),
        ]
        # 罚球圈（半圆 + 虚线段简化为整圆）
        circle = []
        for i in range(61):
            a = math.pi * i / 60.0
            circle.append((self.ft_circle_r_m * math.cos(a), yft + self.ft_circle_r_m * math.sin(a)))
        lines.append(("ft_circle", circle))
        restricted = []
        for i in range(61):
            a = math.pi * i / 60.0
            restricted.append((self.restricted_r_m * math.cos(a), self.restricted_r_m * math.sin(a)))
        lines.append(("restricted", restricted))
        return lines

    def in_paint(self, x: float, y: float) -> bool:
        yb = -self.hoop_from_baseline_m
        yft = self.lane_len_m - self.hoop_from_baseline_m
        return abs(x) <= self.lane_w_m / 2.0 and yb <= y <= yft

def full_landmarks():
    return {name: (x, y - 12.425) for name, (x,y) in CourtModel().landmarks.items()}

def preview_lines(cal, width, height):
    from .court import invert, apply_homography
    inv = invert(cal.H)
    if inv is None: return []
    lines=[]
    for _, line in CourtModel().court_polylines():
        points=[apply_homography(inv,x,y-12.425) for x,y in line]
        if all(math.isfinite(x) and math.isfinite(y) for x,y in points):
            lines.append([[x/width,y/height] for x,y in points])
    return lines
