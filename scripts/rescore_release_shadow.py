"""Re-evaluate ONLY parallel candidates on fixed selected model observations.

No YOLO calls, no changed basketball/rim selection, no altered official events.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from collect_cv_baseline import sha256,write_json
from aihoop.legacy_shots.settings import resolve_detect
from aihoop.legacy_shots.stream import unpack
from aihoop.legacy_shots.release_candidates import ShotReleaseCandidateDetector,link_forward_evidence


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raws',nargs='+',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('Choose a new output directory')
    a.out.mkdir(parents=True);summary=[]
    for i,path in enumerate(a.raws):
        raw=json.loads(path.read_text());trace=raw['detections_meta']['legacy_shots']
        options=resolve_detect({'general':trace['config']['detect']['general']})['general']
        detector=ShotReleaseCandidateDetector(raw['fps'],options)
        for row in trace['frames']:
            if row.get('cut'):detector.reset()
            detector.update(row['frame'],row['t'],unpack(row.get('ball')),
                [unpack(p) for p in row['persons']],row.get('tracked_rim'))
        detector.finish()
        result={'input_raw':str(path),'input_raw_sha256':sha256(path),'video_sha256':sha256(raw['video_path']),
            'source_sha256':sha256(Path(__file__).resolve().parents[1]/'src/aihoop/legacy_shots/release_candidates.py'),
            'scope':'fixed observations, shadow scoring only; not full GPU ablation',
            'options':options,'candidates':detector.candidates,
            'forward_links':link_forward_evidence(detector.candidates,trace['events'],trace['frames']),
            'formal_events_untouched':trace['events'],'counts_for_statistics':False}
        target=a.out/f'{i:02d}_{path.parent.name}.json';write_json(target,result)
        summary.append({'raw':str(path),'output':str(target),'candidates':len(detector.candidates),
            'states':dict(Counter(c['candidate_state'] for c in detector.candidates)),
            'types':dict(Counter(c['shot_type'] for c in detector.candidates))})
    write_json(a.out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
