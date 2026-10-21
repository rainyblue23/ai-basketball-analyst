"""Import the supplied text as a new, provenance-preserving annotation batch."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    source = ROOT / '三个视频出手记录.txt'
    batch = ROOT / 'eval/annotation_imports/three_bili_20261020'
    batch.mkdir(parents=True, exist_ok=True)
    confirmation_path = batch / 'human_confirmation.json'
    confirmation = json.loads(confirmation_path.read_text(encoding='utf-8')) if confirmation_path.exists() else {}
    values_confirmed = confirmation.get('table_values_human_verified') is True and confirmation.get('source_sha256') == digest(source)
    archived = batch / source.name
    if archived.exists() and digest(archived) != digest(source):
        raise SystemExit('Archived original differs; create a new batch instead of overwriting.')
    if not archived.exists():
        shutil.copy2(source, archived)
    frozen = ROOT / 'eval/ground_truth/shots_split2_20261011.json'
    frozen_before = digest(frozen)
    text = source.read_text(encoding='utf-8-sig')
    keys = [('杨瀚森', 'yang', 'BV1e8HS6HEv4'), ('利拉德', 'lillard', 'BV165YQ68E3C'), ('哈登', 'harden', 'BV1sHYN6uEGd')]
    samples, issues = [], []
    video_root = ROOT.parent / 'aihoop_assets/samples/bili'
    for title, key, bvid in keys:
        section = text.split('【' + title + '】', 1)[1].split('【', 1)[0]
        videos = list(video_root.glob('*' + bvid + '*.mp4'))
        if len(videos) != 1:
            raise SystemExit(f'{key}: expected exactly one video, got {len(videos)}')
        video = videos[0]
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'json', str(video)], text=True, encoding='utf-8'))
        duration = float(probe['format']['duration'])
        old_path = ROOT / f'eval/ground_truth/{key}_bili_timed.json'
        old_data = json.loads(old_path.read_text(encoding='utf-8'))
        old = {float(s['release_t']): s for s in old_data['shots']}
        shots = []
        section_start_line = text[:text.index('【' + title + '】')].count('\n') + 1
        for line_no, line in enumerate(section.splitlines(), section_start_line):
            m = re.match(r'^\s+(\d{2})\s+(\d+(?:\.\d+)?)\s+(命中|未中)\s+([123—])\s*(.*)$', line)
            if not m:
                continue
            ordinal, seconds, outcome, value, note = m.groups()
            t = float(seconds)
            prior = old.get(t)
            parsed_value = None if value == '—' else int(value)
            status = []
            if prior is None:
                status.append('no_prior_event_at_time')
            elif parsed_value != prior.get('value') and not values_confirmed:
                status.append('value_conflict_with_prior')
            if not 0 <= t < duration:
                status.append('time_out_of_bounds')
            row = dict(id=f'{key}_{ordinal}', event_type='shot', release_s=t,
                result='made' if outcome == '命中' else 'missed',
                supplied_value=parsed_value,
                value=parsed_value if not status else None,
                value_status='pending' if status else ('UNKNOWN' if parsed_value is None else 'confirmed'),
                value_confirmation='human_user_followup' if values_confirmed and parsed_value is not None else None,
                prior_value=(prior or {}).get('value'),
                is_free_throw='✓' in note, note=note.replace('✓', '').strip(),
                is_replay=True if '回放 [lillard_buzzer]' in note else (prior or {}).get('is_replay', False),
                play_id=(prior or {}).get('play_id', f'{key}_{ordinal}'),
                prior_annotation_id=(prior or {}).get('id'),
                duplicate_of_existing_annotation=prior is not None,
                source_line=line_no, source_text=line.strip(), pending_reasons=status,
                event_time_status='approximate', time_precision_s=1.0)
            if '需核对离手帧' in note:
                row['pending_reasons'].append('precise_release_pending')
            if status:
                issues.append(dict(id=row['id'], reasons=status))
            shots.append(row)
        if len(shots) != len(old):
            raise SystemExit(f'{key}: parsed {len(shots)} rows, expected {len(old)}; refusing partial import')
        if len({s['release_s'] for s in shots}) != len(shots):
            raise SystemExit(f'{key}: duplicate timestamps require review')
        samples.append(dict(id=key, video=str(video), source_sha256=digest(video), duration_s=duration,
            source_platform='bilibili', source_id=bvid,
            identity_status='filename_and_bvid_matched_external_origin_not_verified',
            time_basis='approximate_release_seconds_in_supplied_video',
            original_full_game_offset_s=None, clip_offset_status='UNKNOWN',
            reviewed_range_declared=[0, duration], scope='all_players_entire_video',
            shots_complete=True, completeness_basis='user_file_declares_entire_video_not_independently_verified',
            non_shot_events_complete=None, dataset_split='Development',
            split_reason='previously used for curated examples and iterative development',
            prior_annotation_sha256=digest(old_path), shots=shots))
    payload = dict(schema_version=1, original_file=str(source), archived_original=str(archived),
        original_sha256=digest(source), source_kind='derived_export_of_existing_annotations',
        frozen_baseline_sha256=frozen_before, samples=samples,
        human_confirmation=confirmation,
        policy='Do not append to old truth or tune algorithms; unknown metadata remains pending.')
    (batch / 'annotations.normalized.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    assert digest(frozen) == frozen_before
    report = ['# NEW ANNOTATION IMPORT REPORT', '', '导入日期：2026-10-20', '',
        '原始TXT已按字节归档；旧JSON、31条冻结真值与算法均未修改。', '',
        '这份TXT声明由已有三份JSON导出，因此是既有人工记录的再次提交，不是59条新增独立样本。', '',
        '|视频|解析条目|命中/未中（含回放）|回放|去回放后出手/命中|待确认条目|', '|---|---:|---|---:|---|---:|']
    for sample in samples:
        shots = sample['shots']; unique = [s for s in shots if not s['is_replay']]
        report.append(f"|{sample['id']}|{len(shots)}|{sum(s['result']=='made' for s in shots)}/{sum(s['result']=='missed' for s in shots)}|{len(shots)-len(unique)}|{len(unique)}/{sum(s['result']=='made' for s in unique)}|{sum(bool(s['pending_reasons']) for s in shots)}|")
    report += ['', '## 成功导入', '', '59条事件解析并另存；解析失败0条。三段视频均存在，SHA256与实际时长已记录在规范化JSON。',
        '视频内近似离手时间均在时长内，无同视频同时间的重复行。全部59条与已有JSON按时间对应，不追加计数。',
        '利拉德141/159/171秒共用play_id，159/171秒保留为回放，唯一事件计数排除它们。', '',
        '## 待确认', '',
        ('- 用户后续明确确认TXT表格分值由其人工核实：14条旧分值差异已解决，采纳表格值；旧值保留在prior_value。表中“—”的8条仍为UNKNOWN。' if values_confirmed else '- TXT的分值列与其汇总、旧JSON存在冲突。冲突值保存为supplied_value，正式value置null，禁止默选。'),
        '- 哈登116秒补扣离手时间仍是近似值，115秒未中与116秒补扣是两次不同出手，不因接近而合并。',
        '- 原片整场时间、剪辑起点/剪辑是否连续均未提供；不把偏移猜成0。当前时间仅定位所提供的视频。',
        '- 整段审核范围是文件声明，尚未独立核验完整性；未提供传球/运球逐条记录，不据此认定这些行为为0次。',
        '- 比赛身份按文件名与BV号对应，未联网或逐帧核验比赛来源。', '',
        '### 逐条待确认', '']
    report.extend(f"- {i['id']}：{', '.join(i['reasons'])}" for i in issues)
    report += ['', '## 可评估范围', '',
        '三段均归Development；Validation=0，Independent Test=0。不能作为新的独立测试或默认用于调参。',
        '可在当前视频时间轴做近似事件/命中结果评估（显式记录匹配容差），但尚未运行评测。',
        '分值已知的记录可评估1/2/3分分类；哈登8条分值仍未知，不做完整得分评估。无球框、无逐帧标注，不做检测mAP或帧级召回。' if values_confirmed else '分值冲突未解决前不得做完整得分/2或3分分类评估；无球框、无逐帧标注，不做检测mAP或帧级召回。',
        '回放检出评估可保留59次画面出现；统计真实唯一出手时应为57次，须明确口径。', '',
        '## 文件', '', f'- 原件SHA256：`{digest(source)}`',
        f'- 归档与规范化数据：`{batch}`', f'- 旧31条真值SHA256（前后相同）：`{frozen_before}`', '',
        '本轮未修改算法、阈值、样例统计或旧冻结基线。']
    (ROOT / 'NEW_ANNOTATION_IMPORT_REPORT.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    print(json.dumps(dict(imported=sum(len(s['shots']) for s in samples), pending=len(issues), failed=0, report=str(ROOT/'NEW_ANNOTATION_IMPORT_REPORT.md')), ensure_ascii=False))


if __name__ == '__main__':
    main()
