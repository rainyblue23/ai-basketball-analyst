"""Human ball corrections are separate from automatic results and test truth."""
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path


def validate_feedback(body):
    if not isinstance(body, dict):
        raise ValueError('纠正格式不正确')
    t = body.get('t')
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
        raise ValueError('回看时间无效')
    boxes = body.get('boxes')
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= 20:
        raise ValueError('请框出篮球或误检物体')
    clean = []
    for box in boxes:
        if not isinstance(box, dict) or box.get('kind') not in ('ball', 'decoy'):
            raise ValueError('框类型无效')
        xy = box.get('xyxy')
        if not isinstance(xy, list) or len(xy) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in xy):
            raise ValueError('框坐标无效')
        if xy[2] <= xy[0] or xy[3] <= xy[1]:
            raise ValueError('框选范围无效')
        clean.append({'kind': box['kind'], 'xyxy': xy})
    return {'t': float(t), 'boxes': clean}


def read_frame(video, t):
    import cv2
    cap = cv2.VideoCapture(str(video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0 or count <= 0:
            raise ValueError('无法读取视频帧信息')
        index = int(t * fps + 1e-6)
        if index >= count:
            raise ValueError('时间超出视频范围')
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            raise ValueError('无法读取当前帧')
        ok, encoded = cv2.imencode('.png', frame)
        if not ok:
            raise ValueError('无法保存画面')
        return encoded.tobytes(), {'frame_index': index, 'frame_t': index / fps, 'fps': fps, 'width': frame.shape[1], 'height': frame.shape[0]}
    finally:
        cap.release()


def save_feedback(directory, video, body, job_id):
    clean = validate_feedback(body)
    image, meta = read_frame(video, clean['t'])
    folder = Path(directory) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    record = {**clean, **meta, 'job_id': job_id, 'video_path': str(video), 'source': 'human_correction', 'purpose': 'training_review', 'training_approved': False, 'created_at': datetime.now(timezone.utc).isoformat(), 'image': 'frame.png'}
    try:
        (folder / 'frame.png').write_bytes(image)
        # JSON is the commit marker; incomplete image-only folders aren't records.
        temp = folder / 'record.tmp'
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(folder / 'record.json')
    except Exception:
        for p in folder.iterdir():
            p.unlink()
        folder.rmdir()
        raise
    return {'saved': True, 'id': folder.name, **meta}
