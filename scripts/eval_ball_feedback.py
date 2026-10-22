"""Diagnose one detector on reviewed ball-correction frames; never trains it."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def iou(left, right):
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = ((left[2] - left[0]) * (left[3] - left[1])
             + (right[2] - right[0]) * (right[3] - right[1]) - intersection)
    return intersection / union if union > 0 else 0.0


def matched_count(truth, predicted, threshold):
    candidates = sorted(
        ((iou(gt, pred), gi, pi) for gi, gt in enumerate(truth)
         for pi, pred in enumerate(predicted)), reverse=True)
    used_truth, used_pred = set(), set()
    for overlap, gi, pi in candidates:
        if overlap < threshold:
            break
        if gi not in used_truth and pi not in used_pred:
            used_truth.add(gi)
            used_pred.add(pi)
    return len(used_truth), len(used_pred)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--feedback-dir', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--conf', type=float, default=.25)
    parser.add_argument('--device', default='0')
    args = parser.parse_args()

    rows = []
    for record_path in sorted(args.feedback_dir.glob('*/record.json')):
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if not (record.get('training_approved') and record.get('frame_complete')
                and record.get('review_status') == 'approved'):
            continue
        image = record_path.parent / record['image']
        if not image.is_file():
            raise ValueError(f'审核记录缺少画面: {record_path.parent.name}')
        expected = record.get('frame_sha256')
        actual = sha256(image)
        if expected and expected != actual:
            raise ValueError(f'审核画面哈希不一致: {record_path.parent.name}')
        rows.append((record_path.parent.name, record, image))
    if not rows:
        raise ValueError('没有审核通过且确认整帧完整的纠错记录')

    from ultralytics import YOLO
    model = YOLO(str(args.weights))
    ball_classes = [key for key, value in model.names.items()
                    if 'ball' in str(value).lower()]
    if len(ball_classes) != 1:
        raise ValueError('模型必须有且只有一个篮球类别')
    results = model.predict([str(row[2]) for row in rows], imgsz=args.imgsz,
                            conf=args.conf, device=args.device, verbose=False)

    totals = Counter()
    details = []
    condition_counts = Counter()
    sources = set()
    for (feedback_id, record, image), result in zip(rows, results):
        width, height = record['width'], record['height']
        truth = [[value * (width if index % 2 == 0 else height)
                  for index, value in enumerate(box['xyxy'])]
                 for box in record['boxes'] if box['kind'] == 'ball']
        predicted = [box.xyxy[0].tolist() for box in result.boxes
                     if int(box.cls[0]) == ball_classes[0]]
        matched_50, used_pred_50 = matched_count(truth, predicted, .5)
        matched_30, _ = matched_count(truth, predicted, .3)
        totals['frames'] += 1
        totals['positive_frames'] += bool(truth)
        totals['negative_frames'] += not truth
        totals['ground_truth_boxes'] += len(truth)
        totals['predictions'] += len(predicted)
        totals['matched_iou_50'] += matched_50
        totals['matched_iou_30'] += matched_30
        totals['unmatched_predictions_iou_50'] += len(predicted) - used_pred_50
        totals['negative_frames_with_predictions'] += bool(predicted) and not truth
        condition_counts.update(record.get('conditions', []))
        source_match_id = record.get('source_match_id')
        if not source_match_id:
            raise ValueError(f'审核记录缺少比赛来源编号: {feedback_id}')
        sources.add(source_match_id)
        details.append({
            'feedback_id': feedback_id,
            'image': str(image),
            'source_match_id': source_match_id,
            'source_video_sha256': record.get('source_video_sha256'),
            'conditions': record.get('conditions', []),
            'ground_truth_boxes': len(truth),
            'predictions': len(predicted),
            'matched_iou_50': matched_50,
            'matched_iou_30': matched_30,
        })
    report = {
        'scope': 'Reviewed local correction subset diagnostics; not overall accuracy.',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'weights': str(args.weights),
        'weights_sha256': sha256(args.weights),
        'settings': {'imgsz': args.imgsz, 'conf': args.conf,
                     'device': args.device, 'iou_thresholds': [.5, .3]},
        'source_count': len(sources),
        'totals': dict(totals),
        'conditions': dict(sorted(condition_counts.items())),
        'details': details,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
