"""Human ball corrections are separate from automatic results and test truth."""
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

CONDITIONS = {
    'far_small', 'motion_blur', 'occluded', 'held_ball',
    'logo_decoy', 'scoreboard_decoy', 'head_decoy', 'other',
}


def file_sha256(path, chunk_size=1024 * 1024):
    """Hash a source without loading a match video into memory."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b''):
            digest.update(chunk)
    return digest.hexdigest()


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
    conditions = body.get('conditions', [])
    if not isinstance(conditions, list) or len(conditions) > len(CONDITIONS):
        raise ValueError('场景标签格式无效')
    conditions = list(dict.fromkeys(conditions))
    if any(not isinstance(v, str) or v not in CONDITIONS for v in conditions):
        raise ValueError('包含未知场景标签')
    return {'t': float(t), 'boxes': clean, 'conditions': conditions}


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
    video_path = Path(video)
    folder = Path(directory) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    record = {
        **clean, **meta, 'job_id': job_id, 'video_path': str(video),
        'frame_sha256': hashlib.sha256(image).hexdigest(),
        # This catches duplicate files and integrity drift. The reviewer later
        # assigns source_match_id because clips/re-encodes can share a match.
        'source_video_sha256': file_sha256(video_path) if video_path.is_file() else None,
        'source': 'human_correction', 'purpose': 'training_review',
        # 网页只要求用户修正局部框，不能据此假设画面其它位置已经完整检查。
        'annotation_scope': 'partial_correction', 'frame_complete': False,
        'review_status': 'pending', 'training_approved': False,
        'created_at': datetime.now(timezone.utc).isoformat(), 'image': 'frame.png',
    }
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


def list_feedback(directory):
    """Return committed correction records; image-only partial writes are ignored."""
    rows = []
    for path in sorted(Path(directory).glob('*/record.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(record, dict):
                continue
            record = {'id': path.parent.name, **record}
            record.setdefault('annotation_scope', 'partial_correction')
            record.setdefault('frame_complete', False)
            record.setdefault('review_status', 'pending')
            record.setdefault('training_approved', False)
            rows.append(record)
        except (OSError, ValueError, TypeError):
            continue
    return rows


def review_feedback(directory, feedback_id, *, decision, reviewer,
                    frame_complete=False, note='', conditions=None,
                    source_match_id=''):
    """Approve only after a reviewer confirms the entire frame was checked."""
    if not isinstance(feedback_id, str) or len(feedback_id) != 32 or any(
            c not in '0123456789abcdef' for c in feedback_id):
        raise ValueError('纠错记录编号无效')
    if decision not in ('approved', 'rejected'):
        raise ValueError('审核结论无效')
    reviewer = str(reviewer or '').strip()
    if not reviewer or len(reviewer) > 80:
        raise ValueError('请填写审核人')
    if decision == 'approved' and not frame_complete:
        raise ValueError('局部纠错不能直接用于训练；请先确认整帧标注完整')
    source_match_id = str(source_match_id or '').strip()
    if (decision == 'approved'
            and (not source_match_id or len(source_match_id) > 120
                 or any(ord(char) < 32 for char in source_match_id))):
        raise ValueError('审核通过前必须填写稳定的比赛来源编号')
    path = Path(directory) / feedback_id / 'record.json'
    if not path.is_file():
        raise ValueError('纠错记录不存在')
    record = json.loads(path.read_text(encoding='utf-8'))
    if conditions is not None:
        checked = validate_feedback({
            't': record.get('t'), 'boxes': record.get('boxes'),
            'conditions': conditions,
        })
        record['conditions'] = checked['conditions']
    record.update({
        'frame_complete': bool(frame_complete),
        'review_status': decision,
        'training_approved': decision == 'approved' and bool(frame_complete),
        'reviewed_by': reviewer,
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'review_note': str(note or '')[:500],
        # Clips, re-encodes and extracted highlights from one match must share
        # this ID. A byte hash alone cannot prevent source leakage.
        'source_match_id': source_match_id or record.get('source_match_id'),
    })
    record.setdefault('annotation_scope', 'partial_correction')
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    return {'id': feedback_id, **record}
