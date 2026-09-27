"""FastAPI 服务 —— 套餐 A 的后端。

设计取舍（答辩会被问，先说清楚）：
  * **不用 Celery**：套餐 A 是「上传 -> 离线分析 -> 出报告」的场景，并发量小、
    单机演示为主。用「线程池 + 任务表」就够，少一个 Redis 依赖，
  Docker Compose 也少一个容器。等真有并发需求（套餐 C 的实时大屏）再上 Celery。
  * **进度用 WebSocket 推**：分析长任务必须有进度反馈，否则 demo 时体验很差。
  * **产物全部落盘 + SQLite 只存索引**：JSON/CSV/MP4 落盘方便直接检查，
    数据库只存任务状态与输出目录，避免大字段进库。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, \
    WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .model import Shot, write_jsonl
from .pipeline import PipelineConfig, run_pipeline
from .report import build_report_json, build_report_md, build_report_llm
from .rules import RulesConfig, compute_player_stats, compute_team_stats, \
    quarter_scores, score_progression, shot_chart

ROOT = Path(__file__).resolve().parents[2]     # aihoopanalyst/
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "jobs.sqlite"
OUT_ROOT = ROOT / "out"
OUT_ROOT.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI 篮球分析软件 · API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

POOL = ThreadPoolExecutor(max_workers=2)
LOCK = threading.Lock()


# --------------------------------------------------------------------------
# 任务存储
# --------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT, progress REAL, message TEXT, error TEXT,
            out_dir TEXT, summary TEXT, source TEXT, video_path TEXT,
            created REAL, updated REAL, payload TEXT
        )""")


init_db()


@dataclass
class JobState:
    job_id: str
    status: str = "queued"
    progress: float = 0.0
    message: str = "排队中"
    error: Optional[str] = None
    out_dir: str = ""
    summary: str = ""
    source: str = "synthetic"
    video_path: Optional[str] = None
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message,
                "error": self.error, "out_dir": self.out_dir,
                "summary": self.summary, "source": self.source,
                "video_path": self.video_path}


_mem: dict[str, JobState] = {}
_subscribers: dict[str, list[asyncio.Queue]] = {}
_loop: Optional[asyncio.AbstractEventLoop] = None


def _persist(st: JobState) -> None:
    with _conn() as c:
        c.execute("""INSERT INTO jobs (job_id,status,progress,message,error,out_dir,
                     summary,source,video_path,created,updated,payload)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(job_id) DO UPDATE SET
                     status=excluded.status, progress=excluded.progress,
                     message=excluded.message, error=excluded.error,
                     out_dir=excluded.out_dir, summary=excluded.summary,
                     updated=excluded.updated, payload=excluded.payload""",
                  (st.job_id, st.status, st.progress, st.message, st.error,
                   st.out_dir, st.summary, st.source, st.video_path,
                   time.time(), time.time(),
                   json.dumps(st.payload, ensure_ascii=False)))


def _broadcast(st: JobState) -> None:
    """把进度推给所有 WebSocket 订阅者（从工作线程安全地调度到事件循环）。"""
    if _loop is None:
        return
    for q in list(_subscribers.get(st.job_id, [])):
        try:
            _loop.call_soon_threadsafe(q.put_nowait, st.to_dict())
        except Exception:
            pass


def _update(st: JobState, **kw) -> None:
    for k, v in kw.items():
        setattr(st, k, v)
    _persist(st)
    _broadcast(st)


# --------------------------------------------------------------------------
# 请求/响应模型
# --------------------------------------------------------------------------
class JobCreate(BaseModel):
    source: str = "synthetic"          # synthetic | video | jsonl
    video_path: Optional[str] = None
    raw_path: Optional[str] = None
    seed: int = 7
    duration: float = 720.0
    # 人工标点（在画面上标篮筐）与人工标注（哪些是真进球）的文件路径。
    # 界面上「在画面上标篮筐」保存后会带上来；给了就优先用，不再靠自动检测。
    marks: Optional[str] = None
    basket_labels: Optional[str] = None
    # 外部记分牌事件（「手动框选 + OCR」的产出，见 /api/scoreboard/ocr）。
    # 给非标准台标用：自动定位/模板都读不出来时，靠它走比分牌路径。
    scoreboard_events: Optional[str] = None
    make_highlights: bool = True
    highlight_limit: int = 15
    review_threshold: float = 0.6
    # 真视频推理：CPU 上逐帧 YOLO 是唯一瓶颈。球追踪必须逐帧（球在空中只有
    # 1 秒左右，抽帧会漏掉整条投篮弧线），所以抽帧只作用在球员检测上。
    stride: int = 1
    player_stride: int = 2
    # False = 跳过逐帧 YOLO。比分牌识别不需要 YOLO，
    # 只要「比分 + 每次得分事件」时把它关掉，3 分钟视频从几十分钟降到一两分钟。
    detect_players: bool = True
    # auto（默认）：比分牌**真读出来了**就用比分牌口径（带入分 + 得分事件），
    # 否则按场上进球计分。为什么设成默认：转播素材上"画面写着 27:35、
    # 报告却写 0:0"是用户最不能接受的错法（实测踩到）。
    # court/visual：一律按场上检测到的进球计分（比分牌只作参考）；
    # scoreboard：强制用比分牌带入分 + 事件。
    score_policy: str = "auto"
    # 没有球场标定时，视觉命中默认按几分计（2 或 3）
    visual_shot_value: int = 2
    # 显式声明"不要球场坐标"：允许在没有标定的情况下跑完整视觉路径，
    # 只验证投篮判定（球+筐），位置类结论一律关闭。见 _run_job 里那道门。
    allow_no_calibration: bool = False
    # 手动篮筐提示 [cx, cy, r]（移动机位/复杂场景下用它锁定篮筐）
    hoop_hint: Optional[list] = None
    # 没有可用球场标定时，**自动启用逐帧滑动标定**（套餐 B 真视频兜底路径）。
    # 关掉就只有「静态标定」一条路，上传的视频大概率出不了战术图。
    auto_sliding: bool = True
    sliding_stride: int = 5
    # 只对前 N 秒做滑动标定（0 = 整段）。这一段之外用最后一个锚点，会偏。
    sliding_max_seconds: float = 0.0
    half_court: bool = True
    # 球检测权重。留空 = 自动挑选（优先重训模型，其次 ShotTracker）。
    # 为什么必须在 API 里暴露：没有它，网页上传的视频只能走"橙色色块"那条
    # 线索（每帧 70 个噪声候选），传球网络必然是空的 —— 而这条路只有在
    # 专用球检测器下才可能出东西。
    ball_weights: str = ""
    # 推理设备："0" = 第一块 GPU，"cpu" = CPU。
    # ⚠️ 之前这里没有这个字段，所有视频任务都默认跑在 CPU 上 ——
    # 球检测/篮筐检测逐帧推理，CPU 上慢十几倍。
    device: str = "0"
    # 跟踪器：botsort.yaml 比 bytetrack 抗遮挡
    tracker: str = "botsort.yaml"


class ShotCorrection(BaseModel):
    made: Optional[bool] = None
    value: Optional[int] = None


class ManualShot(BaseModel):
    """人工补录一次进球（自动检测漏掉时使用）。"""
    t: float
    team: str = "home"
    player_id: str = "MANUAL"
    value: int = 2          # 1=罚球 2=两分 3=三分
    x: float = 0.0
    y: float = 0.0
    period: int = 1


def _pick_hoop_weights(explicit: str = "") -> str:
    """挑一个可用的**篮筐**检测权重（自己标注+训练的优先）。"""
    if explicit and Path(explicit).exists():
        return explicit
    cand = ROOT / "runs/detect/rim/weights/best.pt"
    return str(cand) if cand.exists() else ""


def _pick_ball_weights(explicit: str = "") -> str:
    """挑一个可用的球检测权重。

    优先级：调用方显式指定 > 重训的模型 > ShotTracker 现成的。
    两个都没有就返回空串 —— 那意味着退化成"橙色色块"线索（广播素材上基本没用），
    但至少不会崩。
    """
    if explicit and Path(explicit).exists():
        return explicit
    for cand in ("runs/detect/ball/weights/best.pt",   # 用自己的数据重训的
                 "data/shot_tracker_best.pt"):          # ShotTracker 现成权重
        if (ROOT / cand).exists():
            return str(ROOT / cand)
    return ""


# --------------------------------------------------------------------------
# 分析任务
# --------------------------------------------------------------------------
def _run_job(job_id: str, req: JobCreate) -> None:
    st = _mem[job_id]
    try:
        _update(st, status="running", message="准备数据源", progress=0.02)
        out_dir = OUT_ROOT / job_id

        if req.source == "synthetic":
            from .sources import synthetic_game
            rt = synthetic_game(seed=req.seed, duration=req.duration)
            (out_dir).mkdir(parents=True, exist_ok=True)
            rt.save(str(out_dir / "raw_track.json"))
        elif req.source == "jsonl":
            if not req.raw_path or not Path(req.raw_path).exists():
                raise RuntimeError(f"raw_track.json 不存在：{req.raw_path}")
            from .sources import jsonl_source
            rt = jsonl_source(req.raw_path)
        elif req.source == "video":
            if not req.video_path or not Path(req.video_path).exists():
                raise RuntimeError(f"视频不存在：{req.video_path}")
            # 优先用**这段视频自己的**标定（界面上点几个场地特征点生成的那种），
            # 再退回老的全局 data/calibration.json。
            # 为什么：标定是按机位/视频来的，拿别的视频的标定硬套，
            # 球场坐标会整片错位（实测把球员投到球场外 8 米）。
            cal_path = _find_calibration_for(req.video_path)
            if cal_path is None:
                cal_path = DATA / "calibration.json"
            from .court import Calibration
            from .sources import VideoSource
            if cal_path.exists():
                cal = Calibration.load(str(cal_path))
            elif (not req.detect_players and req.score_policy == "scoreboard") \
                    or getattr(req, "allow_no_calibration", False):
                # 没有标定也允许跑：管线本来就支持（位置类结论会被自动关掉，
                # 分值退回 visual_shot_value）。两种情形：
                #   ① 只读比分（关球员 + 比分牌口径）—— 作者原有豁免
                #   ② 调用方**显式**声明"不要球场坐标"（allow_no_calibration）
                #      —— 用来单独验证"投篮判定"本身：球+筐路径不依赖单应矩阵，
                #      实测需求就是"跑一段素材看投篮判得准不准"，不该被标定卡住。
                cal = Calibration(name="unavailable", method="unavailable")
            else:
                raise RuntimeError(
                    "尚未标定球场。请先标球场；只读比分可关闭球员检测并选 scoreboard 口径，"
                    "只想验证投篮判定（不要球场坐标）可传 allow_no_calibration=true。")
            _update(st, message=f"球场标定：{cal.name}")

            # ---- 人工标点 / 人工标注（界面上传过来的路径）----
            # marks：在画面上标过篮筐 → 直接用用户的坐标，跳过篮筐检测器
            manual_hoop = None
            marks_p = getattr(req, "marks", None)
            if not marks_p:
                # 前端没带（常见：本次会话没打开过标注弹窗）——服务端自己找。
                # 标过一次就该一直生效，不能依赖"用户这次点没点过那个按钮"。
                auto = _find_marks_for(req.video_path)
                if auto:
                    marks_p = str(auto)
                    _update(st, message=f"自动使用已保存的篮筐标点：{auto.name}")
            if marks_p and Path(marks_p).exists():
                try:
                    md = json.loads(Path(marks_p).read_text(encoding="utf-8"))
                    hp = md.get("hoop")
                    if hp:
                        from .hoop import Hoop
                        manual_hoop = Hoop(cx=float(hp[0]), cy=float(hp[1]),
                                           rx=float(hp[2]), ry=float(hp[3]),
                                           votes=1, confidence=1.0,
                                           method="manual",
                                           t=float(md.get("at") or 0.0))
                        _update(st, message=f"使用人工标点篮筐 "
                                            f"({manual_hoop.cx:.0f},{manual_hoop.cy:.0f})")
                except Exception as e:  # noqa: BLE001
                    _update(st, message=f"标点文件读不了，忽略：{e}")
            # basket_labels：人工标注了「哪些是真进球」→ 只报告标注为进球的时刻
            basket_labels = None
            labels_p = getattr(req, "basket_labels", None)
            if labels_p and Path(labels_p).exists():
                try:
                    rows = [json.loads(x) for x in
                            Path(labels_p).read_text(encoding="utf-8").splitlines()
                            if x.strip()]
                    basket_labels = {"path": str(labels_p), "rows": rows}
                    n_made = sum(1 for r in rows if r.get("label") == "made")
                    _update(st, message=f"人工标注：{len(rows)} 个候选，"
                                        f"{n_made} 个标为进球")
                except Exception as e:  # noqa: BLE001
                    _update(st, message=f"标注文件读不了，忽略：{e}")

            # 界面上的「逐球确认」反馈（/api/feedback）**自动生效**：
            # 用户否掉过的误报，不需要再填任何路径也不会再出现。
            # 只在用户没显式给标注文件时用它 —— 显式文件优先。
            if basket_labels is None:
                fb = load_feedback(req.video_path)
                if fb:
                    rows = [{"t0": float(x["t"]) - 1.0, "t1": float(x["t"]) + 1.0,
                             "label": x["label"]} for x in fb]
                    # 有反馈就启用白名单：只保留你判过「进了」的那些
                    basket_labels = {"path": str(_feedback_path()), "rows": rows}
                    n_made = sum(1 for r in rows if r["label"] == "made")
                    _update(st, message=f"用界面反馈过滤：{len(rows)} 条判断，"
                                        f"{n_made} 个标为进球")

            src = VideoSource(req.video_path, cal, stride=max(1, req.stride),
                              player_stride=max(1, req.player_stride),
                              detect_players=req.detect_players,
                              score_policy=getattr(req, "score_policy", "auto"),
                              visual_shot_value=getattr(req, "visual_shot_value", 2),
                              hoop_hint=(tuple(req.hoop_hint)
                                         if getattr(req, "hoop_hint", None) else None),
                              auto_sliding=getattr(req, "auto_sliding", True),
                              sliding_stride=getattr(req, "sliding_stride", 5),
                              sliding_max_seconds=getattr(
                                  req, "sliding_max_seconds", 0.0),
                              half_court=getattr(req, "half_court", True),
                              tracker=getattr(req, "tracker", "botsort.yaml"),
                              ball_weights=_pick_ball_weights(
                                  getattr(req, "ball_weights", "")),
                              hoop_weights=_pick_hoop_weights(""),
                              device=getattr(req, "device", "0"),
                              manual_hoop=manual_hoop,
                              scoreboard_events=getattr(req, "scoreboard_events",
                                                        None),
                              basket_labels=basket_labels)
            rt = src.run(progress=lambda p, m="视频推理中": _update(
                st, progress=0.05 + p * 0.55, message=m))
            out_dir.mkdir(parents=True, exist_ok=True)
            rt.save(str(out_dir / "raw_track.json"))
        else:
            raise RuntimeError(f"未知数据源：{req.source}")

        cfg = PipelineConfig(
            out_dir=str(out_dir),
            rules=RulesConfig(review_threshold=req.review_threshold),
            make_highlights=req.make_highlights,
            highlight_limit=req.highlight_limit,
            video_path=req.video_path,
        )
        res = run_pipeline(
            rt, cfg,
            progress=lambda p, m: _update(st, progress=0.6 + p * 0.38, message=m))

        _update(st, status="done", progress=1.0, message="分析完成",
                out_dir=str(out_dir), summary=res.summary())
    except Exception as e:  # noqa: BLE001
        _update(st, status="error", message="分析失败",
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


@app.on_event("startup")
async def _startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    from .job_recovery import recover_jobs
    recover_jobs(DB_PATH)


@app.post("/api/jobs")
async def create_job(req: JobCreate) -> dict:
    if req.source == "jsonl" and (req.scoreboard_events or req.score_policy != "auto"):
        raise HTTPException(400, "jsonl 不支持覆盖 scoreboard_events / score_policy；请使用 video 比分任务。")
    job_id = uuid.uuid4().hex[:12]
    st = JobState(job_id=job_id, source=req.source, video_path=req.video_path,
                  payload=req.model_dump())
    from .job_recovery import process_identity
    st.payload["_worker_owner"] = process_identity()
    _mem[job_id] = st
    _persist(st)
    POOL.submit(_run_job, job_id, req)
    return {"job_id": job_id}


@app.get("/api/jobs")
async def list_jobs(include_synthetic: bool = False) -> list[dict]:
    """最近 20 条任务。

    默认**不返回合成（synthetic）任务** —— 那是 `demo` 数据源跑出来的模拟比赛
    （比分、出手、回合全是生成的），把它们混在历史里会让人以为系统分析过这些
    比赛。需要时用 `?include_synthetic=true` 取回。

    额外带一个 ``has_tactics``：产物目录里有没有 tactics.json。
    前端据此把"能看战术分析的任务"标出来 —— 实机上最常见的困惑就是
    "为什么战术页什么都没有"：因为当前选中的是**真视频任务**，
    而真视频要同时有球场标定 + 球员检测才可能产出球员轨迹。
    """
    where = "" if include_synthetic else "WHERE IFNULL(source,'') <> 'synthetic' "
    with _conn() as c:
        rows = c.execute("SELECT job_id,status,progress,message,out_dir,summary,"
                         "source,created FROM jobs " + where +
                         "ORDER BY created DESC LIMIT 20").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        od = d.get("out_dir") or ""
        # 注意：不能只看"文件在不在" —— 没有球员轨迹的任务也会写一份
        # tactics.json（里面是 {"available": false, "reason": ...}），
        # 只看存在性会把这类任务也标成"有战术数据"，用户点进去还是空的。
        d["has_tactics"] = False
        if od:
            fp = Path(od) / "tactics.json"
            try:
                if fp.exists():
                    d["has_tactics"] = bool(
                        json.loads(fp.read_text(encoding="utf-8")).get("available"))
            except Exception:  # noqa: BLE001
                d["has_tactics"] = False
        out.append(d)
    return out


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    st = _mem.get(job_id)
    if st:
        return st.to_dict()
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "job not found")
    r = dict(row)
    r["payload"] = json.loads(r.get("payload") or "{}")
    return r


@app.websocket("/api/jobs/{job_id}/ws")
async def job_ws(ws: WebSocket, job_id: str) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(job_id, []).append(q)
    try:
        st = _mem.get(job_id)
        if st:
            await ws.send_json(st.to_dict())
        while True:
            item = await q.get()
            await ws.send_json(item)
            if item.get("status") in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            _subscribers.get(job_id, []).remove(q)
        except ValueError:
            pass
        try:
            await ws.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 结果读取
# --------------------------------------------------------------------------
def _out_dir(job_id: str) -> Path:
    st = _mem.get(job_id)
    if st and st.out_dir:
        return Path(st.out_dir)
    with _conn() as c:
        row = c.execute("SELECT out_dir,status FROM jobs WHERE job_id=?",
                        (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "job not found")
    if row["status"] != "done" or not row["out_dir"]:
        raise HTTPException(409, "任务尚未完成")
    return Path(row["out_dir"])


def _load_json(job_id: str, name: str) -> Any:
    p = _out_dir(job_id) / name
    if not p.exists():
        raise HTTPException(404, f"{name} 不存在")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/games/{job_id}")
async def get_game(job_id: str) -> Any:
    return _load_json(job_id, "game.json")


@app.get("/api/games/{job_id}/players")
async def get_players(job_id: str) -> Any:
    return _load_json(job_id, "players.json")


@app.get("/api/games/{job_id}/shotchart")
async def get_shotchart(job_id: str) -> Any:
    return _load_json(job_id, "shotchart.json")


@app.get("/api/games/{job_id}/tactics")
async def get_tactics(job_id: str, v: str = "") -> Any:
    """套餐 B：战术层结论（控球 / 传球网络 / 阵型 / 空间指标）。

    没有球员轨迹时会返回 200 + {"available": false, "reason": "..."} —— 
    **不要**返回 404：前端据此显示"本场没有球员轨迹"这种可读提示，
    比一个干巴巴的 404 有用得多。
    """
    d = _out_dir(job_id)
    p = d / "tactics.json"
    # no-store：战术数据会被"重算战术层"原地覆盖（比如修完 bug 用已存的
    # raw_track.json 重算），URL 不变的话浏览器会一直用旧响应 ——
    # 表现就是"后端明明有了、页面上还是空的"。
    if not p.exists():
        return JSONResponse({"available": False,
                             "reason": "本场没有战术产物。"},
                            headers={"Cache-Control": "no-store"})
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")),
                        headers={"Cache-Control": "no-store"})


@app.get("/api/games/{job_id}/tactics/frames")
async def get_tactics_frames(job_id: str) -> Any:
    """俯视战术图的逐帧数据（JSONL -> JSON 数组）。

    单独一个接口是有意的：它比 tactics.json 还大（每帧 10 名球员 + 球），
    只在用户真的打开"战术分析"页时才拉，不拖慢总览/统计页。
    """
    d = _out_dir(job_id)
    p = d / "tactics_frames.jsonl"
    if not p.exists():
        return JSONResponse({"available": False, "frames": [],
                             "reason": "没有逐帧战术数据"},
                            headers={"Cache-Control": "no-store"})
    frames = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return JSONResponse({"available": True, "count": len(frames),
                         "frames": frames},
                        headers={"Cache-Control": "no-store"})


@app.get("/api/games/{job_id}/highlights")
async def get_highlights(job_id: str) -> Any:
    """高光片段清单。

    这里会**核对文件是否真的在磁盘上**，并把 `available` 改成真实值 ——
    以前直接照抄分析时写的 clips.json，文件被删掉（或被清理脚本误删）后
    接口仍然报 available=true，前端于是拿一个 404 地址去播，用户只看到
    「文件缺失或编码不支持」，查不出原因。现在缺文件就直接标出来，
    并告诉调用方可以调 /export/highlights 重新切。
    """
    game = _load_json(job_id, "game.json")
    clips = game.get("highlights", []) or []
    hl_dir = _out_dir(job_id) / "highlights"
    missing = 0
    fixed = []
    for c in clips:
        c = dict(c)
        name = c.get("path")
        # clips.json 里存的是文件名；旧产物里可能是绝对路径 —— 都归一成文件名
        if name:
            name = Path(str(name)).name
        exists = bool(name) and (hl_dir / name).exists()
        if c.get("available") and not exists:
            missing += 1
        c["available"] = exists
        # path 必须带 `highlights/` 前缀 —— 前端把它交给 API.mediaUrl(jobId, path)
        # 拼成 /api/media/{job}/{path}；只给裸文件名会拼成 /api/media/{job}/clip_xx.mp4
        # → 404 → 页面列了片段但**点了没反应**（实测踩到：14 个片段全在磁盘上、
        # 单独 GET 也是 200 video/mp4，就是页面播不了）。
        c["path"] = f"highlights/{name}" if exists else None
        c["url"] = (f"/api/media/{job_id}/highlights/{name}" if exists else None)
        c["file"] = name if exists else None
        fixed.append(c)
    # 合成好的整段高光（如果切过）——之前根本没返回，前端"播放合成视频"永远是空的
    reel = hl_dir / "highlights_reel.mp4"
    reel_url = (f"/api/media/{job_id}/highlights/highlights_reel.mp4"
                if reel.exists() else None)
    return {"clips": fixed,
            "count": len(fixed),
            "available": sum(1 for c in fixed if c["available"]),
            "missing": missing,
            "reel_url": reel_url,
            "reel_available": bool(reel_url),
            "can_regenerate": bool(missing),
            "regenerate_url": f"/api/games/{job_id}/export/highlights",
            "index_url": f"/api/media/{job_id}/highlights/index.json"}


@app.post("/api/games/{job_id}/export/highlights")
async def regenerate_highlights(job_id: str) -> Any:
    """**重切高光片段**（用已保存的时间码 + 源视频，不重新推理）。

    为什么需要它：`out/<job>/highlights/` 是产物目录，很容易被清理脚本、
    手动 rm、或换机器时丢掉。以前丢了就只能重跑整条推理管线；其实出手明细和
    源视频路径都还在，`make_highlights()` 重跑一次就恢复 —— 这个接口就是那条路。
    """
    from .highlight import make_highlights
    from .rules import build_shots

    d = _out_dir(job_id)
    raw_p = d / "raw_track.json"
    if not raw_p.exists():
        raise HTTPException(404, "raw_track.json 不存在，无法重建（需要重跑分析）")
    raw = json.loads(raw_p.read_text(encoding="utf-8"))
    with _conn() as c:
        row = c.execute("SELECT payload FROM jobs WHERE job_id=?",
                        (job_id,)).fetchone()
    payload = json.loads(row["payload"]) if row else {}
    video = payload.get("video_path") or raw.get("video_path")
    if not video or not Path(video).exists():
        raise HTTPException(
            400, "源视频不在本机（合成数据没有视频源），只能导出时间码")
    shots = build_shots(raw.get("attempts") or [], ball_track=[],
                        scoreboard_events=[])
    clips = make_highlights(shots, video, str(d / "highlights"),
                            duration=raw.get("duration"))
    ok = sum(1 for x in clips if x.get("available"))
    # 顺手把 game.json 里的 highlights 也刷新，免得接口再读到旧清单
    gp = d / "game.json"
    if gp.exists():
        try:
            g = json.loads(gp.read_text(encoding="utf-8"))
            g["highlights"] = clips
            gp.write_text(json.dumps(g, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        except Exception:
            pass
    return {"ok": True, "clips": clips, "count": len(clips), "available": ok,
            "note": f"已按时间码重切 {ok}/{len(clips)} 个片段"}


@app.get("/api/games/{job_id}/report")
async def get_report(job_id: str) -> Any:
    d = _out_dir(job_id)
    md = (d / "report.md").read_text(encoding="utf-8") \
        if (d / "report.md").exists() else ""
    js = json.loads((d / "report.json").read_text(encoding="utf-8")) \
        if (d / "report.json").exists() else {}
    return {"markdown": md, "json": js}


@app.post("/api/games/{job_id}/report/llm")
async def gen_report_llm(job_id: str) -> Any:
    """可选：用 LLM 润色战报（套餐 C 能力，A 里作为加分项）。"""
    js = _load_json(job_id, "report.json")
    try:
        text = build_report_llm(js)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    ( _out_dir(job_id) / "report_llm.md").write_text(text, encoding="utf-8")
    return {"markdown": text}


# --------------------------------------------------------------------------
# 人工复核：改判并写回统计口径
# --------------------------------------------------------------------------
@app.get("/api/games/{job_id}/review")
async def list_review(job_id: str) -> Any:
    game = _load_json(job_id, "game.json")
    return {"needs_review": game.get("needs_review", []),
            "total": len(game.get("timeline", [])),
            "threshold": _review_threshold(job_id),
            "corrections": _corrections(job_id)}


def _review_threshold(job_id: str) -> float:
    st = _mem.get(job_id)
    if st:
        return float(st.payload.get("review_threshold", 0.6))
    with _conn() as c:
        row = c.execute("SELECT payload FROM jobs WHERE job_id=?",
                        (job_id,)).fetchone()
    if not row:
        return 0.6
    return float(json.loads(row["payload"] or "{}").get("review_threshold", 0.6))


def _corrections_path(job_id: str) -> Path:
    return _out_dir(job_id) / "corrections.json"


def _manual_attempts_path(job_id: str) -> Path:
    return _out_dir(job_id) / "manual_attempts.json"


def _manual_attempts(job_id: str) -> list:
    p = _manual_attempts_path(job_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _corrections(job_id: str) -> dict:
    p = _corrections_path(job_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.post("/api/games/{job_id}/shots/{index}/correct")
async def correct_shot(job_id: str, index: int, body: ShotCorrection) -> Any:
    """修正一次出手判定，然后**重算全部统计与热区并覆盖产物**。

    这就是「可解释、可干预」的产品化体现：模型的低置信度判断不是终点，
    人工一键修正后所有派生数据（比分/球员统计/热区/战报）立即一致更新。

    index 是 game["timeline"] 里的下标（按时间排序后的出手序号）。
    """
    if body.value is not None and body.value not in (1, 2, 3):
        raise HTTPException(400, "分值只能为 1、2 或 3")
    game = _load_json(job_id, "game.json")
    timeline = game.get("timeline", [])
    if not (0 <= index < len(timeline)):
        raise HTTPException(400, f"index 越界：{index}，当前共 {len(timeline)} 次出手")

    d = _out_dir(job_id)
    if not (d / "raw_track.json").exists():
        raise HTTPException(409, "缺少 raw_track.json，无法重算")

    # 累积改判记录，然后整条管线重算 —— 保证统计口径始终一致
    fixes = _corrections(job_id)
    cur = fixes.get(str(index), {})
    if body.made is not None:
        cur["made"] = body.made
    if body.value in (1, 2, 3):
        cur["value"] = body.value
    fixes[str(index)] = cur
    _corrections_path(job_id).write_text(
        json.dumps(fixes, ensure_ascii=False, indent=2), encoding="utf-8")

    from .sources import RawTrack
    rt = RawTrack.load(str(d / "raw_track.json"))
    st = _mem.get(job_id)
    payload = st.payload if st else {}
    cfg = PipelineConfig(
        out_dir=str(d),
        rules=RulesConfig(review_threshold=payload.get("review_threshold", 0.6)),
        make_highlights=False,
        video_path=payload.get("video_path"),
    )
    cfg.overrides = {int(k): v for k, v in fixes.items()}
    cfg.extra_attempts = _manual_attempts(job_id)
    res = run_pipeline(rt, cfg)
    if st:
        _update(st, summary=res.summary())
    return {"ok": True, "summary": res.summary(), "score": res.game["score"],
            "corrections": fixes,
            "needs_review_left": len(res.game.get("needs_review", []))}


@app.post("/api/games/{job_id}/shots/add")
async def add_manual_shot(job_id: str, body: ManualShot) -> Any:
    """人工补录一次进球，然后重算全部统计与战报。

    自动检测漏掉时，用户在复核页/接口里填「时间、球队、几分」，
    系统把它当成一次 100% 置信度的人工出手，走同一套规则引擎。
    """
    d = _out_dir(job_id)
    rt_path = d / "raw_track.json"
    if not rt_path.exists():
        raise HTTPException(404, "该任务没有 raw_track.json")
    value = int(body.value)
    if value not in (1, 2, 3):
        raise HTTPException(400, "value 必须是 1、2 或 3")
    if body.t < 0:
        raise HTTPException(400, "t 不能为负")
    from .sources import RawTrack
    rt = RawTrack.load(str(rt_path))
    fps = rt.fps or 30.0
    manual = _manual_attempts(job_id)
    manual.append({
        "t": float(body.t),
        "team": body.team or "home",
        "player_id": body.player_id or "MANUAL",
        "x": float(body.x or 0.0),
        "y": float(body.y or 0.0),
        "period": int(body.period or 1),
        "clock": 0.0,
        "is_free_throw": value == 1,
        "release_frame": int(float(body.t) * fps),
        "made": True,
        "conf": 1.0,
        "forced_value": value,
        "source": "manual",
        "location_source": "manual",
        "location_estimated": False,
        "counts_for_score": True,
        "value_source": "manual",
        "manual": True,
    })
    _manual_attempts_path(job_id).write_text(
        json.dumps(manual, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = PipelineConfig(
        out_dir=str(d),
        rules=RulesConfig(review_threshold=_review_threshold(job_id)),
        make_highlights=False,
    )
    cfg.extra_attempts = manual
    res = run_pipeline(rt, cfg)
    st = _mem.get(job_id)
    if st:
        _update(st, summary=res.summary())
    return {"ok": True, "summary": res.summary(), "score": res.game["score"],
            "manual_attempts": len(manual),
            "timeline": res.game.get("timeline", [])}


# --------------------------------------------------------------------------
# 导出下载
# --------------------------------------------------------------------------
@app.get("/api/games/{job_id}/export")
async def export(job_id: str, fmt: str = "json") -> Any:
    d = _out_dir(job_id)
    table = {
        "json": ("game.json", "application/json", "game.json"),
        "csv_stats": ("stats.csv", "text/csv", "球员统计.csv"),
        "csv_shots": ("shots.csv", "text/csv", "出手明细.csv"),
        "report_md": ("report.md", "text/markdown", "战报.md"),
        "events": ("events.jsonl", "application/x-ndjson", "events.jsonl"),
        # 套餐 B：战术层导出
        "csv_passes": ("passes.csv", "text/csv", "传球网络.csv"),
        "csv_spacing": ("spacing.csv", "text/csv", "球队空间指标.csv"),
        "tactics": ("tactics.json", "application/json", "战术分析.json"),
    }
    if fmt not in table:
        raise HTTPException(400, f"fmt 只能是 {list(table)}")
    name, mime, dl = table[fmt]
    p = d / name
    if not p.exists():
        raise HTTPException(404, f"{name} 不存在")
    return FileResponse(str(p), media_type=mime, filename=dl)


@app.get("/api/frame")
async def get_frame(video_path: str, at: float = 1.0) -> Any:
    """取视频某一秒的一帧（JPEG），给「在画面上标点」用。

    为什么做进接口：标点必须在**用户看着画面**的环境里做。命令行脚本
    （scripts/mark_landmarks.py）能用，但用户全程在界面里操作，不该被要求去敲命令。
    """
    import base64
    import cv2
    p = Path(video_path)
    if not p.exists():
        cand = UPLOAD_DIR / p.name
        if cand.exists():
            p = cand
        else:
            raise HTTPException(404, f"视频不存在：{video_path}")
    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        raise HTTPException(400, "打不开视频")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(float(at) * fps)))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(400, f"取不到第 {at}s 的帧")
    h, w = frame.shape[:2]
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise HTTPException(500, "帧编码失败")
    return {"video": str(p), "at": float(at), "w": w, "h": h,
            "fps": round(float(fps), 3), "frames": total,
            "image": "data:image/jpeg;base64," +
                     base64.b64encode(buf.tobytes()).decode("ascii")}



def _video_identity(video: str) -> str:
    """上传视频的"身份"：去掉 `_a129ae7e6e` 这类上传后缀后的原始哈希。

    界面上传会把文件复制成 `<hash>_<8~10位>.mp4`，同一个视频每次上传后缀都不同。
    我们要认的是同一个视频，所以把后缀剥掉。
    """
    import re as _re
    stem = Path(video).stem
    return _re.sub(r"_[0-9a-f]{8,12}$", "", stem)


def _newest_matching(pattern: str) -> Optional[Path]:
    try:
        cands = [q for q in DATA.glob(pattern) if q.is_file()]
    except Exception:
        return None
    if not cands:
        return None
    cands.sort(key=lambda q: q.stat().st_mtime, reverse=True)
    return cands[0]


def _find_marks_for(video: str) -> Optional[Path]:
    """按视频身份找人工标点文件（精确 → 同一视频的其他上传副本）。"""
    exact = _marks_path_for(video)
    if exact.exists():
        return exact
    ident = _video_identity(video)
    if ident and ident != Path(video).stem:
        hit = _newest_matching(f"marks_{ident[:40]}*.json")
        if hit:
            return hit
    return None


def _find_calibration_for(video: str) -> Optional[Path]:
    """按视频身份找这段视频自己的标定文件。"""
    exact = _calibration_path_for(video)
    if exact.exists():
        return exact
    ident = _video_identity(video)
    if ident and ident != Path(video).stem:
        hit = _newest_matching(f"calibration_{ident[:40]}*.json")
        if hit:
            return hit
    return None


class MarkRequest(BaseModel):
    """画面标点：坐标用**归一化值**（0~1）传，避免前后端分辨率不一致。"""
    video_path: str
    at: float = 1.0
    landmarks: dict = {}          # {name: [x, y]}，归一化
    hoop: Optional[list] = None   # [cx, cy, rx, ry]，归一化（可选，服务端也会算）
    attack_dir: Optional[str] = None    # left | right | unknown


def _marks_path_for(video: str) -> Path:
    """标点文件按视频名存，避免不同视频互相覆盖。"""
    import re
    stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", Path(video).stem)[:40]
    return DATA / f"marks_{stem}.json"


# --------------------------------------------------------------------------
# 进球反馈：把「这一下到底进没进」的人工判断攒成训练/评估数据
# --------------------------------------------------------------------------
# 为什么要有它：自动判据在有些机位上 precision = 0%（实测 nybo_3min 三次全错）。
# 光说"不准"没有意义，得有地方让用户逐球确认，并把确认结果留下来：
#   1. 立刻用于过滤 —— 用户在界面上把误报一键否掉，重跑就对了；
#   2. 累积成带标签样本，供训练一个真正学出来的判据
#      （scripts/export_basket_patches.py 导出切片 → 训练脚本）。
# 反馈按「视频 + 时刻」存，同一段视频重复分析时**自动生效**，不用再填路径。
FEEDBACK_FILE = DATA / "basket_feedback.jsonl"


def _feedback_path() -> Path:
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    return FEEDBACK_FILE


def load_feedback(video: Optional[str] = None) -> list:
    p = _feedback_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if video is None or Path(str(d.get("video", ""))).name == Path(video).name:
            out.append(d)
    return out


def append_feedback(rows: list) -> int:
    """追加反馈；同一「视频+时刻」覆盖旧的，避免重复累积。"""
    p = _feedback_path()

    def key(d):
        return (Path(str(d.get("video", ""))).name,
                round(float(d.get("t", 0.0)), 1))

    merged = {key(d): d for d in load_feedback()}
    for d in rows:
        d = dict(d)
        d["recorded_at"] = time.time()
        merged[key(d)] = d
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for d in merged.values():
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    tmp.replace(p)
    return len(rows)


class FeedbackRequest(BaseModel):
    video_path: str
    items: list = []          # [{"t": 59.94, "label": "made|miss", "note": ""}]


@app.post("/api/feedback")
async def post_feedback(req: FeedbackRequest) -> Any:
    """记录「这一球进没进」的人工判断（界面上把误报一键否掉）。"""
    items = []
    for it in (req.items or []):
        lab = str(it.get("label", "")).strip()
        if lab not in ("made", "miss"):
            continue
        items.append({"video": str(req.video_path),
                      "t": float(it.get("t", 0.0)),
                      "label": lab, "note": str(it.get("note", ""))})
    n = append_feedback(items)
    rows = load_feedback(req.video_path)
    return {"ok": True, "saved": n, "total_for_video": len(rows),
            "made": sum(1 for d in rows if d.get("label") == "made"),
            "file": str(_feedback_path())}


@app.get("/api/feedback")
async def get_feedback(video_path: Optional[str] = None) -> Any:
    """读回反馈（界面用来显示「这一球你已经判过」）。"""
    rows = load_feedback(video_path)
    return {"video": video_path, "count": len(rows),
            "made": sum(1 for d in rows if d.get("label") == "made"),
            "items": rows, "file": str(_feedback_path())}


@app.get("/api/games/{job_id}/candidate_sheet")
async def candidate_sheet(job_id: str, t: float, span: float = 1.6):
    """某个时刻的候选证据图（篮筐放大 + 逐帧，红圈=篮圈，黄圈=球块）。

    逐球标注必须"看得见画面"才能判 —— 只有数字的表格用户没法判断。
    """
    import sys as _sys
    from fastapi.responses import Response
    d = _out_dir(job_id)
    raw = d / "raw_track.json"
    if not raw.exists():
        raise HTTPException(404, "raw_track.json 不存在")
    meta = (json.loads(raw.read_text(encoding="utf-8")).get("detections_meta")
            or {})
    hs = meta.get("hoopsight") or {}
    video = hs.get("video_path") or meta.get("video_path")
    if not video or not Path(video).exists():
        raise HTTPException(400, "找不到源视频，无法出图")
    hoop = None
    for src in (hs.get("auto_shots") or []), (hs.get("shots") or []):
        for s_ in src:
            if abs(float(s_.get("t", -99)) - float(t)) < 0.5:
                hoop = s_.get("hoop_px") or None
                break
        if hoop:
            break
    if not hoop:
        h0 = (hs.get("hoops") or [{}])[0]
        hoop = [h0.get("cx"), h0.get("cy"), h0.get("rx", 40.0),
                h0.get("ry", 17.0)]
    if hoop[0] is None:
        raise HTTPException(400, "这次任务没有篮筐信息（缺标点或检测失败）")

    # 用同一套渲染（scripts/basket_label_lib.py）
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts) not in _sys.path:
        _sys.path.insert(0, str(scripts))
    try:
        from basket_label_lib import make_sheet, require_cv
        cv2, _np = require_cv()
        cand = {"t0": float(t) - 0.2, "t1": float(t) + 0.6,
                "hoop": [float(hoop[0]), float(hoop[1]),
                         float(hoop[2]) if len(hoop) > 2 else 40.0,
                         float(hoop[3]) if len(hoop) > 3 else 17.0],
                "rel_x_at_rim": 0.0, "drop_px": 0.0,
                "chain": []}
        if len(hoop) >= 4:
            cand["win"] = [max(0, int(hoop[0] - 3 * hoop[2])),
                           max(0, int(hoop[1] - 2 * hoop[3])),
                           int(hoop[0] + 3 * hoop[2]),
                           int(hoop[1] + 6 * hoop[3])]
        else:
            cand["win"] = [max(0, int(hoop[0] - 120)),
                           max(0, int(hoop[1] - 60)),
                           int(hoop[0] + 120), int(hoop[1] + 200)]
        out_png = d / f"_sheet_{int(float(t) * 100)}.jpg"
        ok = make_sheet(str(video), cand, out_png)
        if not ok or not out_png.exists():
            raise HTTPException(500, "出图失败")
        data = out_png.read_bytes()
        try:
            out_png.unlink()
        except OSError:
            pass
        return Response(content=data, media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"出图失败：{type(e).__name__}: {e}")


# --------------------------------------------------------------------------
# 训练标注：逐球判「进没进」（不要先跑完整分析）
# --------------------------------------------------------------------------
LABEL_SHEET_DIR = DATA / "_label_sheets"


def _load_candidates_file(path: str) -> dict:
    fp = Path(path)
    if not fp.is_absolute():
        fp = DATA.parent / fp
    if not fp.exists():
        raise HTTPException(404, f"候选文件不存在：{path}")
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"候选文件解析失败：{e}")


@app.get("/api/label/candidates")
async def label_candidates(path: str) -> Any:
    """候选列表（给训练标注页用）。path 指向 candidates.json。"""
    d = _load_candidates_file(path)
    cands = d.get("candidates") or []
    meta = d.get("meta") or {}
    video = meta.get("video") or d.get("video") or ""
    fb = {}
    for row in load_feedback(video or None):
        fb[round(float(row.get("t", 0)), 1)] = row.get("label")
    out = []
    for i, c in enumerate(cands):
        t = float(c.get("t0", 0.0))
        out.append({
            "idx": i, "t0": t, "t1": float(c.get("t1", t)),
            "n": c.get("n"), "drop_px": c.get("drop_px"),
            "rel_x_at_rim": c.get("rel_x_at_rim"),
            "likely": c.get("likely", False),
            "feedback": fb.get(round(t, 1)),
        })
    return {"path": str(path), "video": video, "count": len(out),
            "likely": sum(1 for c in out if c["likely"]),
            "labeled": sum(1 for c in out if c["feedback"]),
            "make": sum(1 for c in out if c["feedback"] == "made"),
            "candidates": out, "meta": meta}


@app.get("/api/label/clip")
async def label_clip(path: str, idx: int, zoom: float = 4.0, slow: int = 3,
                     pad_before: float = 1.6, pad_after: float = 1.0):
    """第 idx 个候选的**放大慢放短视频**（人工判进球用）。

    比逐帧拼图直观得多：球有没有从圈里落下去，看视频是一眼的事。
    结果缓存在 data/_label_clips/，同一个候选第二次请求直接返回。
    """
    import sys as _sys
    from fastapi.responses import FileResponse
    d = _load_candidates_file(path)
    cands = d.get("candidates") or []
    if not (0 <= idx < len(cands)):
        raise HTTPException(404, f"候选序号越界：{idx}")
    meta = d.get("meta") or {}
    video = meta.get("video") or d.get("video")
    if not video or not Path(video).exists():
        raise HTTPException(400, "候选文件里没有可用的视频路径")
    c = cands[idx]
    out_dir = DATA / "_label_clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{abs(hash(path)) % 100000}_{idx}_{zoom:g}_{slow}_{pad_before:g}"
    out_mp4 = out_dir / f"c_{tag}.mp4"
    if not out_mp4.exists():
        scripts = Path(__file__).resolve().parents[2] / "scripts"
        if str(scripts) not in _sys.path:
            _sys.path.insert(0, str(scripts))
        try:
            from make_basket_clip import make_clip
            win = c.get("win")
            if not win:
                h = c.get("hoop") or [0, 0, 40, 17]
                win = [max(0, int(h[0] - 3 * h[2])), max(0, int(h[1] - 2 * h[3])),
                       int(h[0] + 3 * h[2]), int(h[1] + 6 * h[3])]
            ok = make_clip(str(video), float(c["t0"]), float(c["t1"]), win,
                           float(zoom), int(slow), out_mp4,
                           hoop_px=c.get("hoop"), chain=c.get("chain"),
                           pad_before=float(pad_before),
                           pad_after=float(pad_after))
            if not ok:
                raise HTTPException(500, "切片失败（缺 ffmpeg？）")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"切片失败：{type(e).__name__}: {e}")
    return FileResponse(str(out_mp4), media_type="video/mp4")


@app.get("/api/label/sheet")
async def label_sheet(path: str, idx: int):
    """第 idx 个候选的证据图（篮筐放大 + 逐帧 + 球块圆圈）。"""
    import sys as _sys
    from fastapi.responses import Response
    d = _load_candidates_file(path)
    cands = d.get("candidates") or []
    if not (0 <= idx < len(cands)):
        raise HTTPException(404, f"候选序号越界：{idx}")
    meta = d.get("meta") or {}
    video = meta.get("video") or d.get("video")
    if not video or not Path(video).exists():
        raise HTTPException(400, "候选文件里没有可用的视频路径")
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts) not in _sys.path:
        _sys.path.insert(0, str(scripts))
    try:
        from basket_label_lib import make_sheet
        LABEL_SHEET_DIR.mkdir(parents=True, exist_ok=True)
        out_png = LABEL_SHEET_DIR / f"s_{abs(hash(path)) % 100000}_{idx}.jpg"
        if not out_png.exists():
            ok = make_sheet(str(video), cands[idx], out_png)
            if not ok:
                raise HTTPException(500, "出图失败")
        return Response(content=out_png.read_bytes(), media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"出图失败：{type(e).__name__}: {e}")


class LabelOne(BaseModel):
    path: str
    idx: int
    t: float
    label: str
    video: Optional[str] = None
    note: str = ""


@app.post("/api/label/labeled")
async def label_one(req: LabelOne) -> Any:
    """记下一条标注（同时用于过滤误报与训练）。"""
    if req.label not in ("made", "miss"):
        raise HTTPException(400, "label 只能是 made / miss")
    video = req.video
    if not video:
        d = _load_candidates_file(req.path)
        video = (d.get("meta") or {}).get("video") or d.get("video") or ""
    n = append_feedback([{"video": video, "t": float(req.t),
                          "label": req.label, "note": req.note}])
    rows = load_feedback(video or None)
    return {"ok": True, "saved": n, "video": video,
            "make": sum(1 for r in rows if r.get("label") == "made"),
            "count": len(rows), "file": str(_feedback_path())}


@app.get("/api/games/{job_id}/candidates")
async def get_candidates(job_id: str) -> Any:
    """某次分析里「被判成进球」的时刻 + 低于门槛被拒的候选。

    给界面用：让用户逐球确认「进没进」，把误报一键否掉（写进 /api/feedback）。
    这些确认过的样本同时也是训练数据（带人工标签的切片）。
    """
    d = _out_dir(job_id)
    raw = d / "raw_track.json"
    if not raw.exists():
        raise HTTPException(404, "raw_track.json 不存在")
    meta = (json.loads(raw.read_text(encoding="utf-8"))
            .get("detections_meta") or {})
    hs = meta.get("hoopsight") or {}
    fb = {round(float(x["t"]), 1): x.get("label")
          for x in load_feedback(hs.get("video_path") or "")}

    def _with_fb(lst):
        out = []
        for s in (lst or []):
            s = dict(s)
            s["feedback"] = fb.get(round(float(s["t"]), 1))
            out.append(s)
        return out

    # shots = 过滤后真正计入的；auto_shots = 自动判定的原始结果（给用户逐条判）
    shots = _with_fb(hs.get("shots"))
    auto = _with_fb(hs.get("auto_shots"))
    rejected = _with_fb(hs.get("rejected") or hs.get("auto_rejected"))
    return {"job_id": job_id, "shots": shots, "auto_shots": auto,
            "rejected": rejected,
            "auto_dropped": (hs.get("label_whitelist") or {}).get("auto_dropped") or [],
            "label_whitelist": hs.get("label_whitelist"),
            "note": hs.get("note", ""),
            "verify_sheet": hs.get("verify_sheet")}


@app.post("/api/marks")
async def save_marks_api(req: MarkRequest) -> Any:
    """保存画面标点（归一化坐标 → 像素），返回落盘路径。

    产出格式与 `scripts/mark_landmarks.py` 完全一致，所以
    `aihoop.cli video --marks <file>` 能直接吃。
    """
    import cv2
    p = Path(req.video_path)
    if not p.exists():
        cand = UPLOAD_DIR / p.name
        if cand.exists():
            p = cand
        else:
            raise HTTPException(404, f"视频不存在：{req.video_path}")
    cap = cv2.VideoCapture(str(p))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    def to_px(v):
        return [round(float(v[0]) * W, 1), round(float(v[1]) * H, 1)]

    pts = {k: to_px(v) for k, v in (req.landmarks or {}).items() if v}
    hoop = None
    if req.hoop and len(req.hoop) >= 3:
        hoop = [round(float(req.hoop[0]) * W, 1),
                round(float(req.hoop[1]) * H, 1),
                round(float(req.hoop[2]) * W, 1),
                round(float(req.hoop[3]) * H, 1)]
    out = {"video": str(p), "at": float(req.at),
           "landmarks": pts, "hoop": hoop,
           "attack_dir": req.attack_dir,
           "frame_size": [W, H], "mode": "web-ui"}
    mp = _marks_path_for(str(p))
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(mp), "marks": out}


# --------------------------------------------------------------------------
# 球场标点（点几个场地特征点 → 解出这段视频的标定）
# --------------------------------------------------------------------------
# 场地真实坐标（FIBA 28x15 米，原点在中圈中心）。
# x: 球场宽度方向 ±7.5；y: 长度方向 ±14。
COURT_LANDMARKS = {
    "corner_near_left":  (-7.5, -14.0),
    "corner_near_right": (7.5, -14.0),
    "corner_far_left":   (-7.5, 14.0),
    "corner_far_right":  (7.5, 14.0),
    "half_left":         (-7.5, 0.0),
    "half_right":        (7.5, 0.0),
    "center":            (0.0, 0.0),
    "ft_near":           (0.0, -5.8),
    "ft_far":            (0.0, 5.8),
    "hoop_near":         (0.0, -12.425),
    "hoop_far":          (0.0, 12.425),
    # ↓ 这几项**必须**和 COURT_LABELS 一一对应。
    # 实测踩到大坑：先把新点位加进了界面清单却没加进这张表 →
    # 用户标了「罚球区左角」「三分弧顶」，后端查不到坐标就**静默丢弃**，
    # 7 个点只剩 4 个，界面还显示"误差 0.0m 偏大"，用户完全无从判断。
    # 罚球区（FIBA）：宽 4.9m、从底线起 5.8m 到罚球线
    "lane_far_left":     (-2.45, 8.2),
    "lane_far_right":    (2.45, 8.2),
    "lane_near_left":    (-2.45, -8.2),
    "lane_near_right":   (2.45, -8.2),
    # 三分线弧顶：半径 6.75m，正对篮筐
    "arc_far":           (0.0, 14.0 - 6.75),
    "arc_near":          (0.0, -14.0 + 6.75),
}


def _calibration_path_for(video: str) -> Path:
    import re
    stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", Path(video).stem)[:40]
    return DATA / f"calibration_{stem}.json"


def _sb_events_path_for(video: str) -> Path:
    """「手动框选 + OCR」读出的得分事件按视频存盘。"""
    import re
    stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", Path(video).stem)[:40]
    return DATA / f"sb_events_{stem}.json"


class ScoreboardOcrRequest(BaseModel):
    """框选比分牌 → OCR 读得分事件。

    ``box`` 是**归一化**坐标 [x0, y0, x1, y1]；不传就自动定位
    （候选叠加区域经过多帧 OCR 比分语义验证后才使用）。
    ``start`` 是起始比分（视频从半场中间开始录时用它当基线）。
    """
    video_path: str
    team_names: Optional[dict] = None
    box: Optional[list] = None
    start: Optional[dict] = None
    step: float = 0.5
    zoom: float = 4.0
    max_seconds: float = 0.0


@app.post("/api/scoreboard/ocr")
async def post_scoreboard_ocr(req: ScoreboardOcrRequest) -> Any:
    """读比分牌（自动定位或手动框选）→ 存成得分事件文件，供分析任务使用。

    为什么要有这个接口：`scoreboard.py` 的模板匹配只认它标过的样式，
    非标准台标（校园/村 BA 转播的横条）读不出来；而"框出比分区域 + 放大 OCR"
    实测能稳定读出（这段素材：27:33 → 27:35 → 27:37 → 29:38，与画面逐帧一致）。
    """
    import cv2

    vp = Path(req.video_path)
    if not vp.exists():
        cand = UPLOAD_DIR / vp.name
        if cand.exists():
            vp = cand
        else:
            raise HTTPException(404, f"视频不存在：{req.video_path}")
    cap = cv2.VideoCapture(str(vp))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if W <= 0 or H <= 0:
        raise HTTPException(400, "读不出视频尺寸")

    box = None
    method = ""
    if req.box and len(req.box) == 4:
        x0, y0, x1, y1 = (float(v) for v in req.box)
        # 归一化坐标 → 像素（前端画框用的是 0~1）
        if max(abs(x0), abs(x1), abs(y0), abs(y1)) <= 1.5:
            x0, x1 = x0 * W, x1 * W
            y0, y1 = y0 * H, y1 * H
        box = (int(min(x0, x1)), int(min(y0, y1)),
               int(abs(x1 - x0)), int(abs(y1 - y0)))
        method = "manual_box"
    import importlib.util
    script = ROOT / "scripts" / "read_marked_scoreboard.py"
    spec = importlib.util.spec_from_file_location("read_marked_sb", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        res = mod.read_scoreboard(str(vp), box=box, start=req.start,
                                  step=req.step, zoom=req.zoom,
                                  max_seconds=req.max_seconds, team_names=req.team_names)
        box, method = res["box"], res["method"]
    except (Exception, SystemExit) as e:
        raise HTTPException(422, f"比分牌读取失败：{e}")
    outp = _sb_events_path_for(str(vp))
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"ok": True, "path": str(outp), "box": list(box), "method": method,
            "n_crops": res["n_crops"], "ocr_hit": res["ocr_hit"],
            "final": res["final"], "n_events": len(res["events"]),
            "start": res["start"], "baseline_from": res["baseline_from"],
            "warnings": res["warnings"],
            "events": res["events"], "rejected": len(res.get("rejected") or []),
            "note": ("读到 %d/%d 张，得分事件 %d 条，最终比分 %s:%s —— "
                     "分析时会自动使用（也可在任务里带 scoreboard_events）"
                     % (res["ocr_hit"], res["n_crops"], len(res["events"]),
                        res["final"].get("home"), res["final"].get("away")))}


@app.get("/api/scoreboard/events")
async def get_scoreboard_events(video_path: str) -> Any:
    """这段视频是否已经有「框选 + OCR」读出的得分事件（前端显示状态用）。"""
    vp = Path(video_path)
    if not vp.exists():
        cand = UPLOAD_DIR / vp.name
        if cand.exists():
            vp = cand
    p = _sb_events_path_for(str(vp))
    if not p.exists():
        return {"exists": False, "path": str(p)}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"exists": True, "path": str(p), "error": "文件解析失败"}
    return {"exists": True, "path": str(p), "box": d.get("box"),
            "method": d.get("method"), "final": d.get("final"),
            "n_events": len(d.get("events") or []),
            "start": d.get("start")}


def _calibration_quality(vp: Path, cal) -> dict:
    """标定的两项客观体检（保存前 + 分析时都用同一套判据）。

    1. **退化检测**：点几乎共线 / 有重合点。这时重投影误差必然是 0.00m 左右，
       所以"误差很小"完全不能证明标定可用 —— 实测一份 4 点标定误差 1.45m、
       界面显示"可用"，而画面里的篮筐被投到 **33.4m** 外，热区/战术图整片错位。
    2. **独立校验**：这份标定解不解释得了画面里那个真篮筐（只在这段视频
       已经标过篮筐时才有真值）。这是与特征点无关的证据 ——
       只看重投影误差永远发现不了"整份标定位错"。

    返回 ``{"degenerate": bool, "reason": str, "hoop_check": {...}, "metrics": {...}}``。
    """
    from .court import calibration_degeneracy
    deg = calibration_degeneracy(cal)
    hoop = {"checked": False, "ok": None, "reason": "这段视频还没有篮筐标点"}
    try:
        marks_p = _find_marks_for(str(vp))
        if marks_p and Path(marks_p).exists():
            md = json.loads(Path(marks_p).read_text(encoding="utf-8"))
            hp = md.get("hoop")
            if hp:
                from .baskets import calibration_sane_for_scoring
                ok_h, why_h = calibration_sane_for_scoring(
                    cal, (float(hp[0]), float(hp[1]), float(hp[2])))
                hoop = {"checked": True, "ok": bool(ok_h), "reason": why_h,
                        "hoop_px": [float(hp[0]), float(hp[1])],
                        "marks": str(marks_p)}
    except Exception as e:  # noqa: BLE001  体检失败不该让标定存不下去
        hoop = {"checked": False, "ok": None,
                "reason": f"校验失败：{type(e).__name__}: {e}"}
    reason = deg.get("reason", "") if deg.get("degenerate") else ""
    if not reason and hoop.get("checked") and hoop.get("ok") is False:
        reason = ("这份标定解释不了画面里的真篮筐 —— %s。两种可能："
                  "① 特征点的**名称与实际位置对不上**（最常见：把罚球区角"
                  "当成底线角、把这一头的点标到那一头）；② 篮筐标点标错了。"
                  "请先核对画面里那个篮筐，再重新标特征点：同一帧里点 6 个以上、"
                  "不要都在同一条线上。" % hoop.get("reason", ""))
    return {"degenerate": bool(deg.get("degenerate")), "reason": reason,
            "hoop_check": hoop, "metrics": deg}


class CourtMarkRequest(BaseModel):
    """球场标点：landmarks 是 {点名义名: [x,y]}，坐标为**归一化**值。

    `confirm=False`（默认）= **只预览**：算出来、把每个点的像素误差与球场合不合规
    都返回给界面，但**不落盘** —— 用户可以先看点得对不对再决定保存。
    这一点是从旧版移植过来的：老版本点完 4 个点直接存，出了问题时用户既不知道
    错在哪、也不知道能不能重来，只能反复试。
    `revision` = 乐观锁：与已存标定的 revision 不一致就 409，避免两个页面互相覆盖。
    """
    video_path: str
    at: float = 1.0
    landmarks: dict = {}
    confirm: bool = False
    revision: Optional[int] = None


def _reproj_px(cal, used: list) -> dict:
    """每个点的**像素**残差：把球场坐标投回画面，与用户点的位置比。

    为什么按像素报：用户点的是像素，"这个点差了 32 像素"他立刻知道该重点哪个；
    米制误差（0.4m）他没概念。旧版标定页就是这么反馈的，用户能自己定位到错的那个点。

    注意坐标系：`cal.dst_m[i]` 与用户点 `cal.src_px[i]` 一一对应，所以直接对
    `dst_m` 用 H 的逆矩阵即可，**不需要**再做 fold/unfold（那是 to_court 那条路的约定）。
    """
    out: dict = {}
    try:
        import math
        from .court import apply_homography, invert
        inv = invert(cal.H)
        if not inv:
            return out
        for i, name in enumerate(used):
            try:
                cx, cy = cal.dst_m[i]
                px, py = cal.src_px[i]
                gx, gy = apply_homography(inv, float(cx), float(cy))
                out[name] = round(math.hypot(gx - float(px), gy - float(py)), 1)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return out
    return out


@app.post("/api/calibrate")
async def post_calibrate(req: CourtMarkRequest) -> Any:
    """用球场特征点解出这段视频的标定（≥4 个点，越多越准）。

    两段式：`confirm=False` 先预览（不落盘），`confirm=True` 才保存。
    保存时的宽容度（移植自旧版）：
      * **点位退化**（近共线/重合）→ 仍然拒绝：这时单应在数学上没有意义
        （重投影误差必然≈0，却把坐标投到几十米外），存下来只会害人；
      * **篮筐独立校验**：投偏 ≤3m 视为合格；3~6m 允许保存但记
        `position_unverified=True` 并提示（可以让人去修，分析时位置结论照样会被关掉）；
        >6m 直接拒绝（那是彻底错的标定，没必要存）。
      这样"宽容地存、严格地用"：保存不卡人，而分析端（sources.py 的
      `calibration_valid` / hoop_check / court_fit）继续一票否决。
    """
    import cv2  # noqa: F401  (court 内部用到)
    import math
    from .court import calibrate_from_keypoints

    vp = Path(req.video_path)
    if not vp.exists():
        cand = UPLOAD_DIR / vp.name
        if cand.exists():
            vp = cand
        else:
            raise HTTPException(404, f"视频不存在：{req.video_path}")
    cap = __import__("cv2").VideoCapture(str(vp))
    W = int(cap.get(__import__("cv2").CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(__import__("cv2").CAP_PROP_FRAME_HEIGHT))
    cap.release()

    kp_px, used = {}, []
    for name, xy in (req.landmarks or {}).items():
        if name not in COURT_LANDMARKS or not xy:
            continue
        kp_px[name] = (float(xy[0]) * W, float(xy[1]) * H)
        used.append(name)
    if len(kp_px) < 4:
        raise HTTPException(
            400, f"至少要点 4 个场地特征点（现在 {len(kp_px)} 个）—— "
                 "四角、中线两端、中圈、罚球线、篮筐里挑看得清的")
    try:
        cal = calibrate_from_keypoints(kp_px, COURT_LANDMARKS)
    except Exception as e:  # noqa: BLE001
        # 预览模式下**不要抛 400**：用户还没保存，界面需要的是"为什么点不成"，
        # 而不是一个错误弹窗（旧版标定页就是先给原因、让人能就地改点）。
        msg = (f"这些点解不出标定：{type(e).__name__}: {e}。"
               "最常见原因是点位几乎在一条线上（比如只点了底线上的几个点），"
               "请换几个**不在同一条线**上的场地特征点。")
        if not req.confirm:
            return {"ok": False, "saved": False, "path": None, "points": used,
                    "n_points": len(kp_px), "rmse_m": None, "reproj_err_px": None,
                    "per_point_px": {}, "usable": False,
                    "position_unverified": False, "hoop_error_m": None,
                    "degeneracy": {}, "hoop_check": {}, "note": msg}
        raise HTTPException(400, msg)
    cal.name = Path(vp).stem
    cal.method = "web-keypoints"
    cal.for_video = str(vp)
    cal.frame_size = [W, H]
    cal.note = f"界面标点：{len(kp_px)} 个场地特征点"
    rmse = float(getattr(cal, "reproj_error_m", 0.0) or 0.0)
    # 保存前的客观体检：退化点位 + 独立校验（画面里的真篮筐）。
    # 不合格就**不写盘**并说明原因 —— 老版本无条件写盘、只看 rmse<1.0，
    # 于是退化标定（误差必然≈0）能一路存下来，分析时坐标整片错位还不报错。
    qual = _calibration_quality(vp, cal)
    hoop = qual["hoop_check"] or {}
    # 篮筐投偏多少米？分三级：≤3 合格 / 3~6 存但标未校验 / >6 拒绝
    hoop_err = None
    if hoop.get("checked"):
        try:
            from .baskets import calibration_hoop_error_m
            hoop_err = calibration_hoop_error_m(cal, hoop.get("hoop_px"))
        except Exception:  # noqa: BLE001
            hoop_err = None
    HOOP_UNVERIFIED_M = 6.0
    blocked = ""
    if qual["degenerate"]:
        blocked = qual["reason"] or "点位退化"
    elif hoop_err is not None and hoop_err > HOOP_UNVERIFIED_M:
        blocked = (f"这份标定把画面里的真篮筐投偏了 {hoop_err:.1f}m（>"
                   f"{HOOP_UNVERIFIED_M:.0f}m）—— 基本可以确定特征点与名称对不上，"
                   "请核对后重新点选")
    tolerate = (not blocked) and hoop_err is not None and hoop_err > 3.0
    notes = []
    if hoop_err is not None:
        notes.append(f"篮筐投影误差 {hoop_err:.2f}m")
    if tolerate:
        notes.append("已允许保存，但**位置结论会被判为未校验**"
                     "（分析端仍会用它自己的校验决定要不要出热区/战术图）")
    # 每点像素误差：用户点的是像素，按像素报他才好判断重点哪个（移植自旧版）
    per_point_px = _reproj_px(cal, used)
    tol_px = max(8.0, 0.02 * math.hypot(W, H))

    result = {"ok": not blocked, "saved": False, "path": None, "points": used,
              "n_points": len(kp_px), "rmse_m": round(rmse, 3),
              "reproj_err_px": (round(max(per_point_px.values()), 1)
                                if per_point_px else None),
              "tol_px": round(tol_px, 1), "per_point_px": per_point_px,
              "usable": (not blocked), "position_unverified": bool(tolerate),
              "hoop_error_m": (round(hoop_err, 2) if hoop_err is not None else None),
              "degeneracy": qual["metrics"], "hoop_check": hoop,
              "revision": req.revision,
              "note": ("；".join(notes) if notes else "")}
    if blocked:
        result["note"] = blocked + "（提示：重投影误差小不等于标定对 —— "
        result["note"] += "4~6 个点几乎共线时误差必然≈0，但坐标会整片错位。）"
        if req.confirm:
            raise HTTPException(400, result["note"])
        return result                      # 预览：把"为什么不能存"如实返回给界面

    out = _calibration_path_for(str(vp))
    if req.confirm:
        old = {}
        if out.exists():
            try:
                old = json.loads(out.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                old = {}
        cur_rev = int(old.get("revision") or 0)
        if req.revision is not None and int(req.revision) != cur_rev:
            raise HTTPException(
                409, f"标定已被其它页面修改（当前 revision={cur_rev}），请刷新后重试")
        result["revision"] = cur_rev + 1
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            from dataclasses import asdict
            data = asdict(cal)
            data.update({
                "revision": cur_rev + 1,
                "capture_time_s": float(req.at) if req.at is not None else None,
                "point_names": used,
                "normalized_points": [[float(v) for v in (req.landmarks or {})[n]]
                                      for n in used
                                      if (req.landmarks or {}).get(n)],
                "reproj_err_px": result["reproj_err_px"],
                "per_point_px": per_point_px,
                "hoop_error_m": result["hoop_error_m"],
                "hoop_check": hoop,
                "position_unverified": bool(tolerate),
            })
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"标定写盘失败：{e}")
        result["saved"] = True
        result["path"] = str(out)
        if not result["note"]:
            result["note"] = ("标定已保存（重投影误差 %.2f m），分析这段视频时会自动使用"
                              % rmse)
        return result
    # 预览模式（confirm=False）：算好了、把误差与合规性都返回，但不落盘
    return result


@app.get("/api/samples")
async def list_samples(limit: int = 24) -> Any:
    """列出机器上现成的视频（示例素材 + 已上传），供引导里"一键用一段视频"。

    为什么需要：新用户上手第一件事是"选一段视频"，而路径要自己找、自己敲（或者
    自己先上传）—— 这正是"刚拿到手一头雾水"的第一个卡点。这里把能直接用的素材
    列出来，前端一个下拉就能选。
    素材来源：环境变量 `AIHOOP_SAMPLES` 指到的目录（示例）与 `data/uploads`（已上传）。
    """
    import os
    exts = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
    roots: list[tuple[str, Path]] = []
    env_dir = os.environ.get("AIHOOP_SAMPLES")
    if env_dir:
        roots.append(("示例", Path(env_dir)))
    if ROOT / "samples" != Path(env_dir or ""):
        roots.append(("示例", ROOT / "samples"))
    roots.append(("已上传", UPLOAD_DIR))
    rows: list[dict] = []
    seen: set = set()
    for group, root in roots:
        if not root.is_dir():
            continue
        # 只扫两层：示例目录往往按场景分子目录，再深就会把大目录扫成十几秒
        for pat in ("*", "*/*"):
            for p in sorted(root.glob(pat)):
                try:
                    if not p.is_file() or p.suffix.lower() not in exts:
                        continue
                    rp = str(p.resolve())
                    if rp in seen:
                        continue
                    seen.add(rp)
                    rows.append({"name": p.name, "path": rp, "group": group,
                                 "size_mb": round(p.stat().st_size / 1048576, 1)})
                except OSError:
                    continue
    rows.sort(key=lambda r: (r["group"] != "示例", r["size_mb"]))
    return {"samples": rows[:max(1, int(limit))], "total": len(rows),
            "sample_dir": env_dir or "",
            "hint": ("示例素材在 " + (env_dir or "samples/") +
                     "；上传的视频在 data/uploads。都没有就先在上传页选一个本地文件。")}


@app.api_route("/api/video", methods=["GET", "HEAD"])
async def get_video_by_path(video_path: str) -> Any:
    """把**原片**流给浏览器，供标定页拖动定位（支持 Range，`<video>` 靠它 seek）。

    为什么必须新增这个接口：原来只有两类能拿到画面 —— `/api/frame`（一张 JPEG）
    和 `/api/games/{job}/video`（按任务 id）。于是标定时**只能手输秒数**去碰那一帧，
    用户实测反馈："只调时间秒数不好整，对于用户来说一点也不方便"。
    旧版（HoopAI）标定页是内嵌播放器 + 拖到任意时刻现场截帧，这里把那条路补回来。

    安全：只接受视频扩展名；路径按"原路径 → data/uploads 下的同名文件"解析，
    和其余接口同一套规则（本工具设计为本地/内网使用，公网部署要额外加鉴权）。
    """
    p = Path(video_path)
    if not p.exists():
        cand = UPLOAD_DIR / p.name
        if cand.exists():
            p = cand
        else:
            raise HTTPException(404, f"视频不存在：{video_path}")
    if not p.is_file():
        raise HTTPException(400, "不是文件")
    ext = p.suffix.lower()
    mime = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
            ".mov": "video/quicktime", ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo"}.get(ext)
    if mime is None:
        raise HTTPException(400, f"不支持的文件类型：{ext}（只允许视频）")
    # FileResponse 自带 Range 支持（前端拖动进度条/seek 都靠它）
    return FileResponse(p, media_type=mime)


@app.get("/api/frames")
async def get_frames(video_path: str, n: int = 6, center: float = -1.0,
                     span: float = 3.0) -> Any:
    """随机抽 N 个画面（给多画面标定用）。

    抽帧原则：在整个视频里均匀撒点再随机抖动，避开开头结尾（常有黑帧/片头），
    并跳过几乎全黑或几乎全白的帧。返回每帧的时刻 + JPEG(base64) + 尺寸。
    """
    import base64
    import random
    import cv2
    p_ = Path(video_path)
    if not p_.exists():
        cand = UPLOAD_DIR / p_.name
        if cand.exists():
            p_ = cand
        else:
            raise HTTPException(404, f"视频不存在：{video_path}")
    cap = cv2.VideoCapture(str(p_))
    if not cap.isOpened():
        raise HTTPException(400, "打不开视频")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total / fps if fps else 0.0
    n = max(1, min(20, int(n)))
    rng = random.Random(20240919)
    picks = []
    if center is not None and float(center) >= 0:
        # 在指定时刻附近抽帧 —— 这样几帧**属于同一段镜头**，
        # 标点才能叠加到同一坐标系（跨镜头一份单应矩阵拟合不了，实测过）。
        c = max(0.0, min(dur - 0.05, float(center)))
        sp = max(0.4, float(span))
        for i in range(n):
            t = c + (i - (n - 1) / 2.0) * (sp / max(1, n - 1))
            picks.append(max(0.0, min(dur - 0.05, t)))
    else:
        lo, hi = dur * 0.05, dur * 0.95
        if hi <= lo:
            picks = [dur / 2]
        else:
            step = (hi - lo) / n
            for i in range(n):
                t = lo + step * (i + 0.5) + rng.uniform(-step * 0.35,
                                                        step * 0.35)
                picks.append(max(0.0, min(dur - 0.05, t)))
    out = []
    W = H = 0
    for t in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(t * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        mean = float(g.mean())
        if mean < 12 or mean > 245:
            continue                      # 黑帧/白帧，跳过
        H, W = fr.shape[:2]
        ok2, buf = cv2.imencode(".jpg", fr,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 86])
        if not ok2:
            continue
        out.append({"t": round(t, 2), "w": W, "h": H,
                    "image": "data:image/jpeg;base64," +
                             base64.b64encode(buf.tobytes()).decode("ascii")})
    cap.release()
    return {"video": str(p_), "count": len(out), "frames": out}


class MultiCalibRequest(BaseModel):
    video_path: str
    # True = 先做镜头位移补偿（只合并同一镜头内的点）再解标定。
    # 移动镜头/剪接素材必须开：实测跨镜头硬合并的平均误差 61 m。
    compensate: bool = True
    # 每帧一组点：[{t: 12.3, landmarks: {名字: [x,y]}}]，x/y 是**该帧的归一化坐标**
    frames: list = []
    # confirm=False（默认）= **只预览**：解出来、把逐点误差与合规性返回，但不落盘。
    # revision = 乐观锁：与已存标定的 revision 不一致就 409。
    confirm: bool = False
    revision: Optional[int] = None


class AutoCalibRequest(BaseModel):
    """自动识别标定：只给点位置，不用给点名。"""
    video_path: str
    points: list = []                     # [[x, y], ...] 归一化
    half: str = "far"                     # far / near / full
    t: float = 0.0


@app.post("/api/calibrate_auto")
async def post_calibrate_auto(req: AutoCalibRequest) -> Any:
    """不用给特征点命名：程序自己认出每个点对应场地哪里，再解标定。

    为什么需要：端线机位一个画面只能看到 5~6 个场地特征点，而「近端/远端」
    的命名在**单张画面上无法分辨**（镜像解与真解几何等价、都误差 0）——
    实测用户按名字标多次都失败，不是操作问题。
    现在改成：只点位置 + 选一个"看到哪部分场地"，其余交给几何约束
    （第 5 个点投票）。
    """
    from .auto_identify_calib import COURT_PTS, identify
    vp = Path(req.video_path)
    if not vp.exists():
        raise HTTPException(400, f"视频不存在：{req.video_path}")
    import cv2  # 其余端点都是局部导入，这里保持一致（模块级没有 cv2）
    cap = cv2.VideoCapture(str(vp))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if W <= 0 or H <= 0:
        raise HTTPException(400, "读不出视频分辨率")
    if len(req.points) < 5:
        raise HTTPException(400, "至少要点 5 个点 —— 4 个点时任何配对都能精确拟合，"
                                 "分不出对错；第 5 个点才能投票。")
    px = [(float(p[0]) * W, float(p[1]) * H) for p in req.points]
    if req.half == "far":
        court = {k: v for k, v in COURT_PTS.items() if v[1] >= -0.1}
    elif req.half == "near":
        court = {k: v for k, v in COURT_PTS.items() if v[1] <= 0.1}
    else:
        court = dict(COURT_PTS)
    r = identify(px, court=court)
    if not r.get("ok"):
        return {"ok": False, "note": r.get("note"), "hits": r.get("hits"),
                "rmse_m": r.get("rmse_m")}
    from .court import Calibration
    from dataclasses import asdict
    mapping = r["mapping"]
    idxs = sorted(mapping)
    src = [list(px[i]) for i in idxs]
    dst = [list(court[mapping[i]]) for i in idxs]
    lab_of = {}
    for c in COURT_LABELS:
        if isinstance(c, dict) and c.get("name"):
            lab_of[c["name"]] = c.get("label", c["name"])
    named = "、".join(lab_of.get(mapping[i], mapping[i]) for i in idxs)
    cal = Calibration(name=vp.stem[:40], method="auto-identify",
                      src_px=src, dst_m=dst, H=r["H"],
                      reproj_error_m=float(r["rmse_m"]), frame="full",
                      for_video=str(vp.resolve()), frame_size=[W, H],
                      note=f"自动识别出 {len(src)} 个关键点：{named}")
    out = DATA / f"calibration_{vp.stem[:40]}.json"
    out.write_text(json.dumps(asdict(cal), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return {"ok": True, "rmse_m": r["rmse_m"], "hits": r["hits"],
            "named": named, "count": len(src),
            "note": r["note"] + f"；已保存 {out.name}（分析时会自动使用）",
            "mapping": {str(k): v for k, v in mapping.items()},
            "calibration": out.name}


@app.post("/api/calibrate_multi")
async def post_calibrate_multi(req: MultiCalibRequest) -> Any:
    """用**多个画面**上点的场地特征点解一份标定，并逐点报误差。"""
    import cv2
    from .court import find_homography, apply_homography, Calibration

    vp = Path(req.video_path)
    if not vp.exists():
        cand = UPLOAD_DIR / vp.name
        if cand.exists():
            vp = cand
        else:
            raise HTTPException(404, f"视频不存在：{req.video_path}")
    cap = cv2.VideoCapture(str(vp))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    label_of = {d["name"]: d["label"] for d in COURT_LABELS}
    src, dst, tags = [], [], []
    for fr in (req.frames or []):
        t = float(fr.get("t", 0.0))
        for name, xy in (fr.get("landmarks") or {}).items():
            if name not in COURT_LANDMARKS or not xy:
                continue
            src.append([float(xy[0]) * W, float(xy[1]) * H])
            dst.append(list(COURT_LANDMARKS[name]))
            tags.append({"name": name, "label": label_of.get(name, name),
                         "t": round(t, 2)})
    seg_info: list = []
    dropped: list = []
    comp_note = ""
    if getattr(req, "compensate", True) and len({t["t"] for t in tags}) > 1:
        # ---- 镜头位移补偿：只合并同一镜头内的点 ----
        try:
            import numpy as _np
            from .frame_motion import build_segments, warp_point
            times = sorted({t["t"] for t in tags})
            seg = build_segments(str(vp), times)
            # 每个片段里有多少个点
            best = None
            for gi, g in enumerate(seg["segments"]):
                sel_idx = [i for i, t_ in enumerate(tags) if t_["t"] in g["times"]]
                info = {"idx": gi, "ref_t": g["ref_t"],
                        "times": [round(x, 2) for x in g["times"]],
                        "n": len(sel_idx)}
                seg_info.append(info)
                if len(sel_idx) >= 4 and (best is None or
                                          len(sel_idx) > best[1]):
                    best = (gi, len(sel_idx), g, sel_idx)
            if best is not None:
                gi, _n, g, sel_idx = best
                src2, dst2, tags2 = [], [], []
                for i in sel_idx:
                    Hmap = _np.array(g["to_ref"][float(tags[i]["t"])],
                                     dtype=_np.float64)
                    wx, wy = warp_point(Hmap, src[i][0], src[i][1])
                    src2.append([wx, wy])
                    dst2.append(dst[i])
                    tags2.append({**tags[i], "warped_to": g["ref_t"]})
                # 其余片段的点只能丢 —— 不同镜头没有统一坐标系
                kept_t = {tags[i]["t"] for i in sel_idx}
                dropped = sorted({t["t"] for t in tags if t["t"] not in kept_t})
                src, dst, tags = src2, dst2, tags2
                for info in seg_info:
                    info["used"] = (info["idx"] == gi)
                comp_note = ("已按镜头位移补偿：用第 %d 段（参考帧 t=%.2fs，%d 个点）"
                             % (gi, g["ref_t"], len(src)))
                if dropped:
                    comp_note += ("；其余画面（t=%s）与它不在同一镜头，未参与解算"
                                  % "、".join("%.1f" % x for x in dropped))
            else:
                comp_note = "各画面都没有凑够 4 个点，无法做镜头位移补偿"
        except Exception as e:  # noqa: BLE001
            comp_note = f"镜头位移补偿失败（{type(e).__name__}: {e}），按原样解算"

    if len(src) < 4:
        raise HTTPException(
            400, f"至少要点 4 个场地特征点（现在 {len(src)} 个）—— "
                 "几个画面上的点会累加在一起算。"
                 + (comp_note and ("当前：" + comp_note) or ""))
    via = "dlt"
    try:
        Hm = find_homography(src, dst)
    except Exception as e:  # noqa: BLE001
        # 兜底：DLT 是纯最小二乘，点共线/重合就无解。改用 RANSAC 找一致子集 ——
        # 能救回"大部分点对、个别点标错"的情况。
        import numpy as _np
        try:
            Hr, mask = cv2.findHomography(
                _np.array(src, dtype=_np.float64),
                _np.array(dst, dtype=_np.float64), cv2.RANSAC, 5.0)
            if Hr is None:
                raise ValueError("RANSAC 也没找到一致的子集")
            Hm = Hr.tolist()
            via = "ransac"
        except Exception as e2:  # noqa: BLE001
            pts = "、".join(
                "%s(t=%ss)→(%.0f,%.0f)" % (t["name"], t["t"], p_[0], p_[1])
                for t, p_ in zip(tags, src))
            raise HTTPException(
                400,
                "解算不出标定（%s）。收到的点：%s —— "
                "如果这些点挤在同一个位置，说明点击没落到你按的地方（坐标 bug）；"
                "如果它们排在一条线上，请换几个不在同一条线的特征点。"
                % (str(e2), pts))

    # ---- RANSAC 内点分析：离群点 = 与其余点矛盾的那几个 ----
    # 为什么单独做：只点 4 个点时，一个点错了也能"解出"H（RANSAC 剔掉它、
    # 用剩下 3 点拟合，3 点必然完美拟合），于是误差看起来是 3 个 0.00 + 1 个大值。
    # 这个特征必须翻译成人话："你那个点与其余点矛盾，重点它"。
    outliers, n_inliers, inlier_mask = [], len(src), None
    try:
        import numpy as _np2
        _Hr, _mask = cv2.findHomography(
            _np2.array(src, dtype=_np2.float64),
            _np2.array(dst, dtype=_np2.float64), cv2.RANSAC, 5.0)
        if _mask is not None:
            inlier_mask = [bool(v) for v in _mask.ravel()]
            n_inliers = sum(1 for v in inlier_mask if v)
            for i, ok_i in enumerate(inlier_mask):
                if not ok_i:
                    outliers.append({"label": tags[i].get("label", tags[i]["name"]),
                                     "t": tags[i]["t"]})
    except Exception:  # noqa: BLE001
        pass

    # 逐点误差 —— 哪个点离群一眼看到
    per_point = []
    errs = []
    for (x, y), (u, v), tag in zip(src, dst, tags):
        px, py = apply_homography(Hm, x, y)
        e = float(((px - u) ** 2 + (py - v) ** 2) ** 0.5)
        errs.append(e)
        per_point.append({**tag, "err_m": round(e, 2),
                          "px": [round(x, 1), round(y, 1)]})
    rmse = float(sum(errs) / len(errs)) if errs else 0.0
    worst = sorted(per_point, key=lambda d: -d["err_m"])[:5]

    # ---- 按画面分组，各自拟合 ----
    # 不同镜头 = 不同单应矩阵，混在一起必然误差巨大（实测 61 m）。
    # 这里逐帧拟合，报出"哪一帧自己就能标定"—— 那才是能用的标定。
    by_t = {}
    for p_, d_ in zip(per_point, dst):
        by_t.setdefault(p_["t"], []).append((p_, d_))
    per_frame_fit = []
    for tt in sorted(by_t):
        items = by_t[tt]
        if len(items) < 4:
            per_frame_fit.append({"t": tt, "n": len(items), "ok": False,
                                  "rmse_m": None,
                                  "note": "点不够 4 个，无法单独拟合"})
            continue
        s_f = [list(i[0]["px"]) for i in items]
        d_f = [list(i[1]) for i in items]
        try:
            Hf = find_homography(s_f, d_f)
            e_f = []
            for (x, y), (u, v) in zip(s_f, d_f):
                px, py = apply_homography(Hf, x, y)
                e_f.append(((px - u) ** 2 + (py - v) ** 2) ** 0.5)
            r_f = float(sum(e_f) / len(e_f))
            per_frame_fit.append({"t": tt, "n": len(items),
                                  "ok": r_f < 1.5, "rmse_m": round(r_f, 3),
                                  "H": Hf if r_f < 1.5 else None,
                                  "note": ("这一帧自己就能标定（误差 %.2f m）"
                                           % r_f) if r_f < 1.5 else
                                          ("这一帧的点也不自洽（误差 %.2f m）"
                                           % r_f)})
        except Exception as e:  # noqa: BLE001
            per_frame_fit.append({"t": tt, "n": len(items), "ok": False,
                                  "rmse_m": None,
                                  "note": f"这一帧解不出：{e}"})
    best_frame = None
    for f_ in per_frame_fit:
        if f_.get("ok") and f_.get("H") is not None:
            best_frame = f_
            break

    # 场景数（不同画面时刻的数量）—— 用来判断"是否跨镜头"
    n_frames = len({f.get("t") for f in (req.frames or [])})
    # **单画面点数不足**是最常见的失败原因（实测用户把 6 个点标在 3 个画面上：
    # t=48.5s 三个、t=49.7s 一个、t=51.5s 两个 → 没有任何一帧凑够 4 个 →
    # 跨帧只能靠位移补偿去拼，误差 4.589m）。这种情况必须直接点名，否则用户
    # 只会看到"误差偏大"，不知道该把点标在同一帧里。
    _best_n = max([f.get("n", 0) for f in per_frame_fit] or [0])
    if _best_n < 4 and len(src) >= 4:
        detail = "、".join(f"t={f['t']}s 有 {f['n']} 个点" for f in per_frame_fit)
        note = ("**没有任何一个画面凑够 4 个点**（%s）。单应矩阵要求同一帧里至少 4 个点"
                "（跨帧的点只有在相机完全不动时才能拼）。请回到场地看得最全的那一帧，"
                "**在同一帧里一次点够 5~6 个点**，再切到下一帧。" % detail)
        ok = False
        if comp_note:
            note += "；" + comp_note
        return {"ok": ok, "rmse_m": round(rmse, 3), "note": note,
                "per_point": sorted(per_point, key=lambda d: -d["err_m"])[:5],
                "worst": sorted(per_point, key=lambda d: -d["err_m"])[:5],
                "n_points": len(src), "n_frames": n_frames,
                "per_frame_fit": per_frame_fit, "H": None,
                "compensate_note": comp_note, "segments": seg_info,
                "outliers": outliers, "n_inliers": n_inliers}
    ok = rmse < 1.5 and n_inliers >= 4

    # ---- 保存前的客观体检：退化（近共线/重合）+ 独立校验（画面里的真篮筐）----
    # 这两项是**必须**的：点几乎共线时 H 在这些点上是精确解（误差 0.00m），
    # 离开这条线就飞掉；而"整份标定位错"只有拿真值点（篮筐）才看得出来。
    cand = Calibration(name=vp.stem, method="web-keypoints-multi", src_px=src,
                       dst_m=dst, H=Hm, reproj_error_m=round(rmse, 3),
                       frame="full", for_video=str(vp), frame_size=[W, H])
    qual = _calibration_quality(vp, cand)
    deg, hoop_check = qual["metrics"], qual["hoop_check"]
    hoop_err2 = None
    if hoop_check.get("checked"):
        try:
            from .baskets import calibration_hoop_error_m
            hoop_err2 = calibration_hoop_error_m(cand, hoop_check.get("hoop_px"))
        except Exception:  # noqa: BLE001
            hoop_err2 = None
    HOOP_HARD_M = 6.0
    # 宽容度分级（移植自旧版标定页的"先让人标完、再告诉他哪里不行"）：
    #   * 退化点位 → 仍然拒绝（单应矩阵在数学上无意义）
    #   * 篮筐投偏 >6m → 仍然拒绝（基本可以断定名称与位置对不上）
    #   * 篮筐投偏 3~6m / 只有 4 个点（无冗余，误差恒为 0）/ 有点互相矛盾
    #     → **允许保存**，但一律标 position_unverified=True，位置类结论由分析端关掉
    #   * 没有任何一帧凑够 4 个点 → 仍然拒绝（这是点法问题，不是宽容度问题）
    blocked = ""
    tolerant = False
    if qual["degenerate"]:
        blocked = ("标定点位**退化**（几乎在一条线上 / 有重合点），这份标定不能用："
                   + qual["reason"]
                   + "（重投影误差小是假象：退化时它必然是 0.00m 左右）")
    elif hoop_err2 is not None and hoop_err2 > HOOP_HARD_M:
        blocked = (f"这份标定把画面里的真篮筐投偏了 {hoop_err2:.1f}m（>"
                   f"{HOOP_HARD_M:.0f}m）—— 基本可以确定特征点与名称对不上，"
                   "请核对画面里的篮筐后重新点选")
    elif len(src) <= 4:
        ok = False
        tolerant = True
        note = ("只点了 %d 个点：4 个点时单应矩阵是精确解，重投影误差必然 "
                "0.00m，**这个数字不能作为质量依据**。已按宽容规则保存，"
                "但位置类结论（热区/战术图）会被判为**未校验**；"
                "想拿到可用的位置结论，请补到 6 个点（多点几个才有冗余去发现错的那个）。"
                % len(src))
    elif outliers and n_inliers >= 4:
        ok = False
        tolerant = True
        note = ("有 %d 个点与其余点**互相矛盾**：%s —— 已用其余 %d 个一致的点"
                "（RANSAC 内点）解算并保存，但位置结论会被判为**未校验**；"
                "想让它变成可信标定，请重点这几个点。"
                % (len(outliers),
                   "、".join("%s(t=%ss)" % (d["label"], d["t"]) for d in outliers),
                   n_inliers))
    elif outliers and n_inliers < 4:
        ok = False
        note = ("排除掉 %d 个矛盾的点后只剩 %d 个点，**解不出标定**"
                "（单应矩阵至少要 3 个不共线的对应，且实际用 4 个以上才稳）。"
                "请重点这几个：%s；再补 1~2 个别的特征点。"
                % (len(outliers), n_inliers,
                   "、".join(d["label"] for d in outliers)))
    elif hoop_err2 is not None and hoop_err2 > 3.0:
        # 3~6m：能存，但位置结论不可信 —— 让用户自己决定要不要重标
        tolerant = True
        note = (f"标定已保存，但独立校验显示篮筐投偏 {hoop_err2:.1f}m —— "
                "位置类结论会被判为**未校验**（计分不受影响）。"
                "想用位置结论，请核对特征点名称与实际位置后重标一次。")
    elif ok:
        note = (("标定可用（%d 个点，来自 %d 个画面；平均重投影误差 %.2f m）"
             % (len(src), n_frames, rmse))
            + (("；" + comp_note) if comp_note else ""))
    elif best_frame is not None:
        ok = True      # 整体拟合不了，但**某一帧自己就能标定** → 用它
        Hm = best_frame["H"]
        rmse = float(best_frame["rmse_m"])
        note = ("整体拟合不了（跨画面平均误差偏大，说明这些画面不是同一镜头），"
                "但 t=%.2fs 这一帧自己就能标定（%d 个点，误差 %.2f m）—— "
                "已用这一帧的标定。" % (best_frame["t"], best_frame["n"], rmse))
    else:
        note = ("平均重投影误差 %.2f m 偏大，且没有任何一帧自己够 4 个点。"
                "说明这些画面**不在同一镜头**（镜头平移/切换），"
                "一份标定拟合不了。请用「取帧时刻 + 在这附近抽帧」，"
                "在**同一段镜头内**的几秒里抽帧，再把 4 个以上点标在那几帧上。"
                % rmse)

    if blocked:
        if comp_note:
            blocked += "；" + comp_note
        if getattr(req, "confirm", False):
            raise HTTPException(400, blocked)
        return {"ok": False, "saved": False, "path": None, "rmse_m": round(rmse, 3),
                "via": via, "note": blocked, "per_point": per_point, "worst": worst,
                "n_points": len(src), "n_frames": n_frames,
                "degeneracy": deg, "hoop_check": hoop_check,
                "hoop_error_m": (round(hoop_err2, 2) if hoop_err2 is not None else None),
                "position_unverified": False,
                "per_frame_fit": [{k: v for k, v in f_.items() if k != "H"}
                                  for f_ in per_frame_fit]}

    cal = Calibration(name=vp.stem, method="web-keypoints-multi",
                      src_px=src, dst_m=dst, H=Hm,
                      reproj_error_m=round(rmse, 3), frame="full",
                      for_video=str(vp), frame_size=[W, H],
                      note=note)
    saved = bool(ok or tolerant)
    want_save = bool(getattr(req, "confirm", False)) and saved
    rev_out = None
    out_p = _calibration_path_for(str(vp))
    if want_save:
        old_rev = 0
        if out_p.exists():
            try:
                old_rev = int((json.loads(out_p.read_text(encoding="utf-8"))
                               or {}).get("revision") or 0)
            except Exception:  # noqa: BLE001
                old_rev = 0
        req_rev = getattr(req, "revision", None)
        if req_rev is not None and int(req_rev) != old_rev:
            raise HTTPException(
                409, f"标定已被其它页面修改（当前 revision={old_rev}），请刷新后重试")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        try:
            from dataclasses import asdict
            data = asdict(cal)
            data.update({
                "revision": old_rev + 1,
                "point_names": [t["name"] for t in tags],
                "reproj_err_px": max((p.get("err_px") or 0) for p in per_point) if per_point else None,
                "hoop_error_m": (round(hoop_err2, 2) if hoop_err2 is not None else None),
                "hoop_check": hoop_check,
                "position_unverified": bool(tolerant),
                "outliers": outliers,
            })
            out_p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"标定写盘失败：{e}")
        rev_out = old_rev + 1
    return {"ok": bool(ok or tolerant), "rmse_m": round(rmse, 3), "via": via,
            "per_frame_fit": [{k: v for k, v in f_.items() if k != "H"}
                              for f_ in per_frame_fit],
            "compensate_note": comp_note, "segments": seg_info,
            "outliers": outliers, "n_inliers": n_inliers,
            "dropped_frames": dropped,
            # 质量诊断：退化读数 + 独立校验（真篮筐）结论。
            # 前端据此显示"为什么不能用"，而不是只红一个"标定失败"。
            "degeneracy": deg, "hoop_check": hoop_check,
            "hoop_error_m": (round(hoop_err2, 2) if hoop_err2 is not None else None),
            "position_unverified": bool(tolerant),
            "n_points": len(src),
            "n_frames": n_frames, "per_point": per_point, "worst": worst,
            "saved": want_save, "revision": rev_out,
            "path": str(out_p) if want_save else None,
            "note": note}


COURT_LABELS = [
    # 命名原则：**用画面里能一眼看到的东西来描述**，不用"近端/远端"。
    # 实测教训：端线机位下用户根本判断不了"近端/远端"，而且球场关于中线对称，
    # 单张画面里镜像解与真解几何等价（误差都是 0.457m）→ 按近/远命名必然失败。
    # 改成"篮筐侧 / 中圈侧"后，用户只需看"这个点在篮筐那一头还是中圈那一头"。
    {"name": "hoop_far", "label": "篮筐中心（画面里那个篮筐）",
     "hint": "篮圈的正中心（不是篮板、不是支架）"},
    {"name": "corner_far_left", "label": "底线左角（篮筐后面那条线）",
     "hint": "篮筐所在的那条底线，与左边线的交点"},
    {"name": "corner_far_right", "label": "底线右角（篮筐后面那条线）",
     "hint": "篮筐所在的那条底线，与右边线的交点"},
    {"name": "lane_far_left", "label": "罚球区左角（篮筐那一头）",
     "hint": "篮筐下面那个梯形/矩形的两个外侧角之一（靠左那个）"},
    {"name": "lane_far_right", "label": "罚球区右角（篮筐那一头）",
     "hint": "篮筐下面那个梯形的另一个外侧角（靠右那个）"},
    {"name": "ft_far", "label": "罚球线中点（篮筐那一头）",
     "hint": "篮筐那侧罚球线的正中间（罚球时站的那条线）"},
    {"name": "arc_far", "label": "三分弧顶（篮筐那一头）",
     "hint": "篮筐那侧三分线圆弧的最高点（正对篮筐）"},
    {"name": "center", "label": "中圈中心",
     "hint": "画面中间那个大圆（通常有队徽）的圆心"},
    {"name": "half_left", "label": "中线·左边线交点",
     "hint": "把球场分成两半的那条中线，与左边线的交点"},
    {"name": "half_right", "label": "中线·右边线交点",
     "hint": "中线与右边线的交点"},
    {"name": "lane_near_left", "label": "罚球区左角（中圈那一头）",
     "hint": "中圈那一侧的罚球区外侧角（靠左）"},
    {"name": "lane_near_right", "label": "罚球区右角（中圈那一头）",
     "hint": "中圈那一侧的罚球区外侧角（靠右）"},
    {"name": "ft_near", "label": "罚球线中点（中圈那一头）",
     "hint": "中圈那侧罚球线的正中间"},
    {"name": "corner_near_left", "label": "底线左角（中圈那一头）",
     "hint": "中圈那一侧的底线，与左边线的交点（多半在画面外）"},
    {"name": "corner_near_right", "label": "底线右角（中圈那一头）",
     "hint": "中圈那一侧的底线，与右边线的交点（多半在画面外）"},
    {"name": "hoop_near", "label": "另一端的篮筐中心",
     "hint": "画面里看不到的那个篮筐（若只有一个篮筐可见就别选它）"},
    {"name": "arc_near", "label": "三分弧顶（中圈那一头）",
     "hint": "中圈那侧三分弧的最高点"},
]


@app.get("/api/court_landmarks")
async def court_landmarks() -> Any:
    """可选的点位清单（前端据此显示提示与进度）。"""
    return {"landmarks": COURT_LABELS, "min_points": 4,
            "court": {"length_m": 28.0, "width_m": 15.0}}


@app.get("/api/court_landmarks_legacy")
async def _court_landmarks_legacy() -> Any:
    return {"landmarks": [
        {"name": "corner_near_left", "label": "近端底线左角",
         "hint": "画面下方那条底线，与左边线的交点"},
        {"name": "corner_near_right", "label": "近端底线右角",
         "hint": "画面下方那条底线，与右边线的交点"},
        {"name": "corner_far_left", "label": "远端底线左角",
         "hint": "画面上方那条底线，与左边线的交点"},
        {"name": "corner_far_right", "label": "远端底线右角",
         "hint": "画面上方那条底线，与右边线的交点"},
        {"name": "half_left", "label": "中线左端",
         "hint": "中线与左边线的交点"},
        {"name": "half_right", "label": "中线右端",
         "hint": "中线与右边线的交点"},
        {"name": "center", "label": "中圈中心",
         "hint": "中圈圆心"},
        {"name": "ft_near", "label": "近端罚球线中点",
         "hint": "靠近画面那侧的罚球线正中"},
        {"name": "ft_far", "label": "远端罚球线中点",
         "hint": "远处那侧的罚球线正中"},
        {"name": "hoop_near", "label": "近端篮筐中心",
         "hint": "靠近画面那个篮筐的篮圈正中心"},
        {"name": "hoop_far", "label": "远端篮筐中心",
         "hint": "远处那个篮筐的篮圈正中心"},
    ], "min_points": 4,
        "court": {"length_m": 28.0, "width_m": 15.0}}

@app.get("/api/calibrate")
async def get_calibration(video_path: str) -> Any:
    """这段视频是否已经有标定（前端用来显示状态）。"""
    vp = Path(video_path)
    if not vp.exists():
        cand = UPLOAD_DIR / vp.name
        if cand.exists():
            vp = cand
    cp = _calibration_path_for(str(vp))
    if not cp.exists():
        # 老路径：data/calibration.json 也可能就是这段视频的
        return {"exists": False, "path": str(cp), "revision": 0}
    try:
        d = json.loads(cp.read_text(encoding="utf-8"))
    except Exception:
        return {"exists": True, "path": str(cp), "error": "标定文件解析失败",
                "revision": 0}
    # revision 要回给前端：保存时带回去做乐观锁（避免两个页面互相覆盖，移植自旧版）；
    # hoop_error / position_unverified 也回：界面要能一眼看出"这份标定没通过独立校验"。
    return {"exists": True, "path": str(cp),
            "for_video": d.get("for_video", ""),
            "reproj_error_m": d.get("reproj_error_m"),
            "reproj_err_px": d.get("reproj_err_px"),
            "method": d.get("method"),
            "point_names": d.get("point_names") or [],
            "capture_time_s": d.get("capture_time_s"),
            "hoop_error_m": d.get("hoop_error_m"),
            "hoop_check": d.get("hoop_check"),
            "position_unverified": bool(d.get("position_unverified")),
            "revision": int(d.get("revision") or 0)}


@app.delete("/api/calibrate")
async def delete_calibration(video_path: str, revision: int = -1) -> Any:
    """撤销这份标定（用户标错了得能重来，而不是只能覆盖或忍着）。

    带 revision 做乐观锁：与当前不一致就 409，避免把别人刚标好的东西删掉。
    撤销后重新分析该视频时，热区/战术图会回到"没有标定"的状态（位置结论关闭）。
    """
    vp = Path(video_path)
    if not vp.exists():
        cand = UPLOAD_DIR / vp.name
        if cand.exists():
            vp = cand
    cp = _calibration_path_for(str(vp))
    if not cp.exists():
        return {"ok": True, "removed": False, "note": "本来就没有标定"}
    cur = 0
    try:
        cur = int((json.loads(cp.read_text(encoding="utf-8")) or {}).get("revision") or 0)
    except Exception:  # noqa: BLE001
        cur = 0
    if revision >= 0 and int(revision) != cur:
        raise HTTPException(409, f"标定已被修改（当前 revision={cur}），请刷新后重试")
    try:
        cp.unlink()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"删除标定失败：{e}")
    return {"ok": True, "removed": True, "path": str(cp)}


@app.get("/api/marks")
async def get_marks_api(video_path: str) -> Any:
    """读回某视频已保存的标点（没有就返回 exists=false）。"""
    p = Path(video_path)
    if not p.exists():
        cand = UPLOAD_DIR / p.name
        if cand.exists():
            p = cand
    mp = _marks_path_for(str(p))
    if not mp.exists():
        return {"exists": False, "path": str(mp)}
    return {"exists": True, "path": str(mp),
            "marks": json.loads(mp.read_text(encoding="utf-8"))}


@app.get("/api/games/{job_id}/video")
async def get_video(job_id: str) -> Any:
    with _conn() as c:
        row = c.execute("SELECT payload FROM jobs WHERE job_id=?",
                        (job_id,)).fetchone()
    payload = json.loads(row["payload"]) if row else {}
    vp = payload.get("video_path")
    if not vp or not Path(vp).exists():
        raise HTTPException(404, "该任务没有关联视频")
    return FileResponse(vp, media_type="video/mp4")


@app.post("/api/upload")
async def upload(request: Request) -> Any:
    """把上传的视频保存到 data/uploads 下。

    直接用 `request.stream()` 写盘，不依赖 `python-multipart`，也不把整个
    文件读进内存。文件名带随机后缀，避免覆盖已有文件或撞上正在被分析、
    被 Windows 锁定的文件。
    """
    import os
    import traceback

    raw_name = request.headers.get("x-filename") or f"upload_{int(time.time())}.mp4"
    safe = "".join(ch for ch in raw_name if ch.isalnum() or ch in "._-") or "video.mp4"
    stem, ext = os.path.splitext(safe)
    stem = (stem[:60] or "video")
    if not ext or len(ext) > 8:
        ext = ".mp4"
    dst = UPLOAD_DIR / f"{stem}_{uuid.uuid4().hex[:10]}{ext}"

    clen = request.headers.get("content-length", "?")
    origin = request.headers.get("origin", "-")
    print(f"[upload] start name={raw_name!r} content-length={clen} "
          f"origin={origin}", flush=True)

    total = 0
    try:
        with open(dst, "wb") as f:
            async for chunk in request.stream():
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
    except Exception as e:
        print(f"[upload] failed while reading body: {type(e).__name__}: {e}",
              flush=True)
        traceback.print_exc()
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        # 客户端断开时可能已经无法回响应，这里尽量给出明确错误。
        raise HTTPException(500, f"写入上传文件失败：{type(e).__name__}: {e}")

    try:
        from .highlight import probe_info
        info = probe_info(str(dst))
    except Exception:
        info = {}
    print(f"[upload] saved {dst} bytes={total}", flush=True)
    return {"path": str(dst), "bytes": total, "info": info}


@app.get("/api/media/{job_id}/{path:path}")
async def media(job_id: str, path: str) -> Any:
    """托管任务产物目录下的文件（高光片段、缩略图等）。"""
    base = _out_dir(job_id).resolve()
    target = (base / path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(403, "越权路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(target))


@app.get("/api/health")
async def health() -> dict:
    from .highlight import ffmpeg_path
    try:
        import ultralytics  # noqa
        yolo = True
    except Exception:
        yolo = False
    try:
        import cv2  # noqa
        cv = True
    except Exception:
        cv = False
    rev = _code_rev()
    stale = rev["newest"] > _LOADED_AT + 1.0
    return {"ok": True, "ffmpeg": bool(ffmpeg_path()),
            "ultralytics": yolo, "opencv": cv,
            "jobs": len(_mem),
            # 「服务进程比代码旧」是踩过的坑：改完源码忘了重启 uvicorn，
            # 新任务还在跑内存里的旧模块，表现是「改了跟没改一样」，
            # 而且没有任何报错，非常难查。所以在 /api/health 里把它暴露出来。
            "code_rev": rev["text"],
            "code_loaded_at": _fmt(_LOADED_AT),
            "stale": stale,
            "has_ball_rim_path": _has_ball_rim_path()}


_LOADED_AT = time.time()


def _code_rev() -> dict:
    """源码最后修改时间 —— 和进程启动时间一比就知道服务是不是旧代码。"""
    root = Path(__file__).resolve().parent
    newest = 0.0
    for p in root.glob("*.py"):
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return {"newest": newest, "text": _fmt(newest)}


def _fmt(ts: float) -> str:
    import datetime
    if not ts:
        return "unknown"
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S")


def _has_ball_rim_path() -> bool:
    """**当前进程里**的 VideoSource 有没有「球+篮筐」这条路。

    注意不能用 importlib.util.find_spec —— 那是去文件系统找，旧进程也能找到，
    就测不出「进程里是旧模块」。必须直接问已经载入的类有没有这个方法。
    """
    from . import sources
    return hasattr(sources.VideoSource, "_visual_attempts")


@app.get("/", response_class=PlainTextResponse)
async def index() -> str:
    return ("AI 篮球分析软件 API 已启动。\n"
            "接口文档：/docs\n"
            "前端：用浏览器打开 web/index.html\n"
            "健康检查：/api/health\n")
