"""球场几何 + 单应矩阵标定。

这一层的作用：把「像素坐标」变成「分析用的球场坐标（米）」。
计分规则引擎要用 6.75m / 0.90m 这些真实尺度判 1/2/3 分，
热区图与**俯视战术图（套餐 B）**也都要把球员画在标准球场上，
所以标定的正确性是整条坐标链的地基。

--------------------------------------------------------------------------
分析坐标系（"折半坐标"）—— 全工程唯一口径
--------------------------------------------------------------------------
  x 横向 ±7.5（x=0 是球场中轴；|x| 越大越贴边线）
  y 纵向：**符号表示在哪半场，|y| 表示离那条底线的距离**
        y < 0 → 左半场（攻左篮筐），|y|=0 是左底线，|y|=14 是中圈
        y > 0 → 右半场（攻右篮筐），|y|=0 是右底线，|y|=14 是中圈
  篮筐 (0, ±1.575)：|1.575| 正好是 FIBA 的「篮筐圆心距底线」——
  只有把 |y| 定义成"离底线的距离"，这个常数才对得上。

半场标定的 4 个目标点（按点击顺序）：
    底线左 (-7.5, 0) → 底线右 (7.5, 0) → 中线右 (7.5, -14) → 中线左 (-7.5, -14)

--------------------------------------------------------------------------
为什么还需要"全场坐标"，以及它怎么变成分析坐标
--------------------------------------------------------------------------
相机拍得下整场时，单应矩阵的 4 组对应点必须用**未折半**的全场坐标
（两条底线在 y=∓14、中线在 y=0），否则同一条对应关系里没法同时表示两个底线。
这类标定记为 ``frame="full"``，它输出的坐标要先经过 :func:`fold_to_analysis`
折到分析坐标系再给下游用（:meth:`Calibration.to_court` 已经把这一步封装好）。

> 折半坐标是**有意的设计**，不是历史包袱：一场比赛里两队各攻一个篮筐，
> 把两个半场叠起来后，热区图 / 分区统计 / 俯视战术图都只需要画一套半场，
> 左右两侧的出手天然对齐。全场坐标只活在标定这一步，不进下游。

--------------------------------------------------------------------------
两种标定方式（按成本从低到高）
--------------------------------------------------------------------------
  1. manual    —— 人工点 4 个角点（最快，2 分钟，demo 完全够用）
  2. keypoints —— 用球场关键点检测模型自动出点，再算单应
两者都收敛到同一个 Homography，下游代码不用改。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence

from .model import COURT_LENGTH, COURT_WIDTH


# --------------------------------------------------------------------------
# 单位换算：把「半场长度坐标」换成「全场中心坐标」
# --------------------------------------------------------------------------
def half_to_full(x_half: float, y_half: float) -> tuple[float, float]:
    """把「半场自建坐标」换成分析坐标（折半坐标）。

    x_half ∈ [0, 15] 从左边线量起；y_half ∈ [0, 14] 从**被进攻的那条底线**量起。
    这里约定被进攻的是左半场，所以分析坐标为 (x_half - 7.5, -y_half)。

    > 历史坑：老版本的 y 方向是反的（把底线当成了 |y|=14）。修正之后
    > ``HALF_COURT_CORNERS``、:func:`fold_to_analysis`、前端 court.js 的
    > ``v=|y|``（v=0 是底线）三者口径才完全一致。
    """
    return x_half - COURT_WIDTH / 2, -y_half


def fold_to_analysis(x: float, y: float, mode: str = "full"
                     ) -> tuple[float, float]:
    """把「标定输出坐标」折到分析坐标（|y| = 离本方底线的距离）。

    单应矩阵的输出到底落在哪种坐标里，**取决于当初拿什么点做的标定**，
    一共四种情形（mode）：

      half   目标点本来就是折半分析坐标（底线 |y|=0、中线 |y|=14）→ 原样返回
      left   目标是「未折半的左半场」（底线 y=-14、中线 y=0）→ y_a = -(14 + y)
      right  目标是「未折半的右半场」（底线 y=+14、中线 y=0）→ y_a = 14 - y
      full   目标是真·全场（两条底线 y=±14、中线 y=0）→ 按点所在半场分别折

    为什么要分这么细：老版本的半场标定点（底线→-14、中线→0）与新版本的
    半场标定点（底线→0、中线→-14）**y 的取值集合完全相同**，只是哪个端点是
    底线反了过来。只按点判断会认错半场 —— 实测会得到「底线折到 0、中线折到
    +14」这种自相矛盾的结果，球员位置在战术图上会整体错到另一个半场。

    ``mode=full`` 时本函数自反，可以直接正反两用；其余模式请配合
    :func:`unfold_from_analysis` 用（见 Calibration.to_pixel）。
    """
    if mode in ("half", ""):
        return x, y
    if mode == "left":
        return x, -(COURT_LENGTH / 2 + y)
    if mode == "right":
        return x, COURT_LENGTH / 2 - y
    # full：按点落在哪个半场分别折
    if y >= 0:
        return x, COURT_LENGTH / 2 - y
    return x, -(COURT_LENGTH / 2 + y)


def unfold_from_analysis(x: float, y: float, mode: str = "full"
                         ) -> tuple[float, float]:
    """:func:`fold_to_analysis` 的逆运算（分析坐标 -> 标定输出坐标）。

    画图（把篮筐/网格叠回视频帧）时要走这条路，所以必须严格互逆。
    """
    if mode in ("half", ""):
        return x, y
    if mode == "left":
        return x, -COURT_LENGTH / 2 - y
    if mode == "right":
        return x, COURT_LENGTH / 2 - y
    if y >= 0:
        return x, COURT_LENGTH / 2 - y
    return x, -COURT_LENGTH / 2 - y


def is_valid_court_point(x: float, y: float, tol: float = 2.0) -> bool:
    """分析坐标是否落在球场附近（容忍标定误差）。

    用途：把明显离谱的投影点（标定错机位、球飞出画面）挡在统计之外，
    否则一个 y=40 的点会把俯视战术图整张图拉爆。
    """
    return (abs(x) <= COURT_WIDTH / 2 + tol
            and -COURT_LENGTH / 2 - tol <= y <= COURT_LENGTH / 2 + tol)


# --------------------------------------------------------------------------
# 单应矩阵（3x3，无 numpy 依赖实现，方便在无第三方库时也能跑）
# --------------------------------------------------------------------------
Matrix3 = list[list[float]]


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float]:
    """高斯消元解 n 元线性方程组（带部分主元）。纯 python，无 numpy。"""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("单应矩阵求解失败：点共线或退化，请重新选点")
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for r in range(col + 1, n):
            f = M[r][col] / pv
            if f:
                for c in range(col, n + 1):
                    M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / M[r][r]
    return x


def find_homography(src: Sequence[Sequence[float]],
                    dst: Sequence[Sequence[float]]) -> Matrix3:
    """求 H 使得 dst ~ H @ src。至少需要 4 组点。"""
    if len(src) < 4 or len(dst) != len(src):
        raise ValueError("至少需要 4 组对应点")
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    h = _solve_linear(A, b)
    return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]


def apply_homography(H: Matrix3, x: float, y: float) -> tuple[float, float]:
    d = H[2][0] * x + H[2][1] * y + H[2][2]
    if abs(d) < 1e-12:
        return 0.0, 0.0
    return ((H[0][0] * x + H[0][1] * y + H[0][2]) / d,
            (H[1][0] * x + H[1][1] * y + H[1][2]) / d)


@dataclass
class Calibration:
    """一次标定结果。可序列化成 calibration.json 存盘/复用。"""
    name: str = "default"
    method: str = "manual"                 # manual | keypoints
    src_px: list[list[float]] = field(default_factory=list)   # 像素点
    dst_m: list[list[float]] = field(default_factory=list)    # 球场米
    H: Optional[Matrix3] = None
    reproj_error_m: float = 0.0
    note: str = ""
    # 目标坐标是「折半坐标」(half) 还是「全场坐标」(full)。
    # keypoints 自动标定可能用全场关键点，所以这个字段显式存下来，
    # 不能靠猜 —— 老文件（没有这个字段）由 _infer_frame 兜底。
    frame: str = "half"
    # 这份标定是**给哪个视频/哪个机位**的。
    # 存在的意义：标定是按机位来的，不是按分辨率来的。以前只比对分辨率，
    # 结果拿公园球场的标定去算 NBA 转播（同样 1280×720）也能通过，
    # 出手点被算到三分线外十几米 —— 看起来像真的，其实全是垃圾。
    # 现在明确绑定视频文件名，对不上就拒绝自动使用。
    for_video: str = ""
    frame_size: list = field(default_factory=list)   # [宽, 高]

    def fit(self) -> "Calibration":
        self.H = find_homography(self.src_px, self.dst_m)
        self.reproj_error_m = self.rmse()
        return self

    def rmse(self) -> float:
        if not self.H:
            return 0.0
        errs = []
        for (x, y), (u, v) in zip(self.src_px, self.dst_m):
            px, py = apply_homography(self.H, x, y)
            errs.append(math.hypot(px - u, py - v))
        return round(sum(errs) / len(errs), 4) if errs else 0.0

    def to_court(self, px: float, py: float) -> tuple[float, float]:
        """像素 -> **分析坐标**（米）。这是下游唯一该用的入口。

        ``frame == "full"`` 的标定会先经过 fold_to_analysis 折半；
        半场标定（``frame == "half"``）的目标点本来就是折半坐标，直接返回。
        """
        if not self.H:
            return 0.0, 0.0
        x, y = apply_homography(self.H, px, py)
        return fold_to_analysis(x, y, self.frame or "half")

    def to_pixel(self, x_m: float, y_m: float) -> tuple[float, float]:
        """**分析坐标** -> 像素（画热区叠加、校验标定用）。

        与 to_court 严格互逆：full 标定会先把折半坐标 unfold 回全场坐标
        （fold_to_analysis 自反，所以直接复用同一个函数）。
        """
        inv = invert(self.H) if self.H else None
        if not inv:
            return 0.0, 0.0
        x_m, y_m = unfold_from_analysis(x_m, y_m, self.frame or "half")
        return apply_homography(inv, x_m, y_m)

    @staticmethod
    def _infer_frame(dst_m: list) -> str:
        """老标定文件（没有 frame 字段）的兜底判定：返回 half/left/right/full。

        判据（按可靠性排序）：
          1. y 跨度 >= 27.5m            -> full（真·全场，两条底线在 ±14）
          2. 前两个点的 y >= +13.9      -> right（未折半的右半场，底线在 +14）
          3. 前两个点的 y <= -13.9      -> left （未折半的左半场，底线在 -14）
          4. 其余                        -> half（本来就是折半分析坐标）

        为什么看"前两个点"：四角点的点选顺序固定是
        「底线左 → 底线右 → 中线右 → 中线左」，所以前两个点一定是底线。
        老版本半场标定（底线 -14 / 中线 0）与新版本（底线 0 / 中线 -14）
        y 取值集合一样，只有顺序能区分，这是唯一可靠的信号。
        """
        ys = [p[1] for p in (dst_m or []) if len(p) >= 2]
        if not ys:
            return "half"
        if max(ys) - min(ys) >= 27.5:
            return "full"
        first = ys[:2]
        if first and min(first) >= 13.9:
            return "right"
        if first and max(first) <= -13.9:
            return "left"
        return "half"

    def analysis_bounds(self, tol: float = 0.15
                        ) -> tuple[float, float, float, float]:
        """这份标定在**分析坐标**里覆盖的球场范围 (xmin, xmax, ymin, ymax)。

        为什么要它：半场标定只覆盖半个球场 —— 左半场是 y ∈ [-14,0]，
        右半场是 y ∈ [0,14]。如果下游拿"|y| <= 14"这种对称范围去过滤，
        就会把**远底线后方**（观众/替补席）的点当成场内点收进来
        （实测出现过 y=+7.4 的"球员"停在底线后面）。
        这里直接从标定点反推覆盖范围，什么半场都不会认错。
        """
        if not self.dst_m:
            return (-COURT_WIDTH / 2 - tol, COURT_WIDTH / 2 + tol,
                    -COURT_LENGTH / 2 - tol, COURT_LENGTH / 2 + tol)
        pts = [fold_to_analysis(px, py, self.frame or "half")
               for px, py in self.dst_m]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs) - tol, max(xs) + tol, min(ys) - tol, max(ys) + tol)

    def in_court(self, x: float, y: float, tol: float = 0.15) -> bool:
        """分析坐标是否落在这份标定覆盖的球场内。"""
        x0, x1, y0, y1 = self.analysis_bounds(tol)
        return x0 <= x <= x1 and y0 <= y <= y1

    def save(self, path: str) -> None:
        d = asdict(self)
        d["H"] = self.H
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load(path: str) -> "Calibration":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return Calibration(name=d.get("name", "default"),
                           method=d.get("method", "manual"),
                           src_px=d.get("src_px", []), dst_m=d.get("dst_m", []),
                           H=d.get("H"),
                           reproj_error_m=d.get("reproj_error_m", 0.0),
                           note=d.get("note", ""),
                           for_video=d.get("for_video", ""),
                           frame_size=d.get("frame_size", []),
                           frame=d.get("frame") or
                           Calibration._infer_frame(d.get("dst_m", [])))

    def matches_video(self, video_path: str, width: int = 0,
                      height: int = 0) -> bool:
        """这份标定是不是给这个视频的。

        判据：`for_video` 记了视频文件名就必须对上；没记（老文件）则退回
        分辨率比对，并且**只在标定点确实落在画面内时**才算通过。
        """
        import os
        base = os.path.basename(str(video_path or ""))
        if self.for_video:
            return bool(base) and self.for_video == base
        src = self.src_px or []
        if not src or not width or not height:
            return False
        return (max(p[0] for p in src) <= width * 1.05
                and max(p[1] for p in src) <= height * 1.05)


def invert(H: Matrix3) -> Optional[Matrix3]:
    """3x3 求逆（伴随矩阵法）。"""
    a, b, c = H[0]
    d, e, f = H[1]
    g, h, i = H[2]
    A = e * i - f * h
    B = -(d * i - f * g)
    C = d * h - e * g
    det = a * A + b * B + c * C
    if abs(det) < 1e-12:
        return None
    return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
            [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
            [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]]


# --------------------------------------------------------------------------
# 预置标定点：让用户点 4 个角点即可
# --------------------------------------------------------------------------
# 全场 4 个角点（**未折半**的全场坐标，米）：两条底线在 y=∓14、中线在 y=0。
# 用这套点算出来的标定 frame="full"，下游必须先 fold_to_analysis() 折半。
FULL_COURT_CORNERS = [
    (-COURT_WIDTH / 2, -COURT_LENGTH / 2),   # 左下
    (COURT_WIDTH / 2, -COURT_LENGTH / 2),    # 右下
    (COURT_WIDTH / 2, COURT_LENGTH / 2),     # 右上
    (-COURT_WIDTH / 2, COURT_LENGTH / 2),    # 左上
]

# 半场 4 个角点（只拍到半场时的推荐配置），**直接用折半坐标**：
#   底线在 |y|=0、中线在 |y|=14，篮筐 (0,±1.575) 正好距底线 1.575m。
# 约定这支摄像机拍的是左半场（y<0），任务列表里 home_hoop 默认也是 left。
#
# ⚠️ 这里曾经是一个**真实的 bug**：老版本把底线映射到 y=-14、中线映射到 y=0，
#    于是篮下上篮被算成离篮筐 12.4m，规则引擎判成三分；俯视战术图也会整体
#    偏移 14m。现在 HALF_COURT_CORNERS / fold_to_analysis / 前端 court.js
#    的 v=|y|（v=0 是底线）三者严格一致，并由
#    tests/test_plan_b.py::test_calibration_layup_is_two_points 守住。
HALF_COURT_CORNERS = [
    (-COURT_WIDTH / 2, 0.0),                   # 底线左
    (COURT_WIDTH / 2, 0.0),                    # 底线右
    (COURT_WIDTH / 2, -COURT_LENGTH / 2),      # 中线右
    (-COURT_WIDTH / 2, -COURT_LENGTH / 2),     # 中线左
]


def calibrate_from_corners(pixel_corners: Sequence[Sequence[float]],
                           half_court: bool = False,
                           name: str = "court",
                           video_path: str = "",
                           frame_size: Optional[Sequence[int]] = None
                           ) -> Calibration:
    """最简单可靠的标定：用户按顺序点 4 个角点。

    顺序：底线左 -> 底线右 -> 中线右 -> 中线左（或全场四角逆/顺时针）。
    """
    import os
    dst = HALF_COURT_CORNERS if half_court else FULL_COURT_CORNERS
    c = Calibration(name=name, method="manual",
                    src_px=[list(p) for p in pixel_corners],
                    dst_m=[list(p) for p in dst],
                    frame="half" if half_court else "full",
                    note="四角点手动画定" + ("（半场）" if half_court else "（全场）"),
                    for_video=os.path.basename(str(video_path)) if video_path else "",
                    frame_size=[int(v) for v in (frame_size or [])])
    return c.fit()


def calibrate_from_keypoints(kp_px: dict[str, Sequence[float]],
                             model_dst: Optional[dict[str, Sequence[float]]] = None
                             ) -> Calibration:
    """用球场关键点检测模型的输出标定（B 套餐的升级路径）。

    kp_px: {"left_baseline_corner_top": (x,y), ...} 至少 4 个，
           名称需与 model_dst 的键一致。
    默认提供一套常见关键点的球场真实坐标（半场进攻右侧篮筐）。
    """
    default_dst = {
        "baseline_left":  (-COURT_WIDTH / 2, -COURT_LENGTH / 2),
        "baseline_right": (COURT_WIDTH / 2, -COURT_LENGTH / 2),
        "half_left":      (-COURT_WIDTH / 2, 0.0),
        "half_right":     (COURT_WIDTH / 2, 0.0),
        "hoop":           (1.575, -COURT_LENGTH / 2 + 1.575),
        "center":         (0.0, 0.0),
    }
    model_dst = model_dst or default_dst
    src, dst = [], []
    for k, px in kp_px.items():
        if k in model_dst:
            src.append(list(px))
            dst.append(list(model_dst[k]))
    if len(src) < 4:
        raise ValueError(f"可用关键点不足 4 个（当前 {len(src)}）")
    c = Calibration(name="keypoints", method="keypoints",
                    src_px=src, dst_m=dst, note="关键点模型自动标定",
                    frame=Calibration._infer_frame(dst))
    return c.fit()
