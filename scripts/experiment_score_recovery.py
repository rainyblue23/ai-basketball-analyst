"""Offline EasyOCR + existing score-change logic + bounded visual reanalysis.

Output stays in a new experiment folder. Nothing is loaded by the API.
"""
import argparse
import json
import math
from pathlib import Path

import cv2

from collect_cv_baseline import freeze,write_json
from eval_ball_feedback import sha256
from read_marked_scoreboard import _easyocr_model_dir,_easyocr_reader
from aihoop.logo_scoreboard import scan
from aihoop.score_guided_recovery import RecoveryOptions,investigate_score_changes
from aihoop.frame_reader import FrameReader
from aihoop.legacy_shots.stream import LegacyShotStream,unpack
from aihoop.legacy_shots.settings import resolve_detect,prediction_options
from aihoop.ball_recovery import measured_detections,deduplicate_candidates,recover_region,recover_rim


def reanalyze(video, window, model, options, cached_frames=None, prediction_cache=None):
    cap=cv2.VideoCapture(str(video));fps=cap.get(5);width=int(cap.get(3));height=int(cap.get(4))
    reader=FrameReader(cap);detect=resolve_detect(options)
    stream=LegacyShotStream(fps,width,height=height,config={'detect':detect})
    predict=dict(prediction_options(detect),device=0,verbose=False)
    start=max(0,math.floor(window['start_s']*fps));stop=math.ceil(window['end_s']*fps)
    calls=0;last=None;cache_hits=0
    cache=prediction_cache if prediction_cache is not None else {}
    try:
        for index in range(start,stop+1):
            ok,image=reader.read(index)
            if not ok:break
            if cached_frames is None or index not in cached_frames:
                raise ValueError('Dense recovery requires same-video cached scene/person context')
            context=cached_frames[index];last=index
            # Cached person/cut evidence is reused only for the same video hash.
            persons=[unpack(p) for p in context.get('persons',[])]
            heads=[unpack(p) for p in context.get('head_context',[])]
            cut=bool(context.get('cut'))
            key=(str(Path(video).resolve()),id(model),index,tuple(sorted(predict.items())))
            if key not in cache:
                cache[key]=measured_detections(model.predict(image,**predict)[0]);calls+=1
            else:cache_hits+=1
            detections=list(cache[key])
            roi_audits={}
            if index%max(1,round(fps/detect['ball_roi_retry_hz']))==0 and not cut:
                if stream.preview_ball(index,detections,image,persons=heads)[0] is None:
                    for name,recover,enabled in (
                        ('ball_recovery',recover_region,detect['ball_roi_recovery']),
                        ('rim_recovery',recover_rim,detect['ball_rim_recovery'])):
                        if not enabled:continue
                        extra,audit=recover(model,image,predict,stream,index)
                        calls+=bool(audit['ran']);detections+=extra
                        roi_audits[name]=audit
            stream.update(index,index/fps,deduplicate_candidates(detections),persons,
                          cut=cut,image=image,head_context=heads)
            stream.frames[-1].update(roi_audits)
            # This pass does not redetect people. Keep their original role and
            # court flags in diagnostic output; pack/unpack drops extra fields.
            stream.frames[-1]['persons']=[dict(p) for p in context.get('persons',[])]
    finally:cap.release()
    if last is not None:stream.finish(last,last/fps)
    return dict(window=window,options=options,original_fps=fps,frames=stream.frames,
        events=stream.events,inference_calls=calls,full_frame_cache_hits=cache_hits,
        truth_status='pending_human_review',time_basis='original_decoded_index_over_nominal_fps')


def reanalyze_reverse(video, window, event, model, options, cached_frames, prediction_cache=None):
    """Reuse full-frame cache and ROI machinery in reverse from a measured rim ball.

    Internal synthetic step numbers exist only to reuse the bounded ball/ROI
    tracker. Returned frame numbers/times always refer to the original video.
    Reverse-time scorer events are discarded; they have no physical meaning.
    """
    cap=cv2.VideoCapture(str(video));fps=cap.get(5)
    width=int(cap.get(3));height=int(cap.get(4));reader=FrameReader(cap)
    detect=resolve_detect(options);stream=LegacyShotStream(fps,width,height=height,config={'detect':detect})
    predict=dict(prediction_options(detect),device=0,verbose=False)
    cache=prediction_cache if prediction_cache is not None else {}
    crossing=event.get('crossing_t');rows=[];calls=hits=0
    eligible=[r for r in cached_frames.values() if crossing is not None and
              0<=crossing-r['t']<=.25 and r.get('ball') and
              not r['ball'].get('predicted') and r['ball'].get('cls')=='basketball']
    if not eligible:
        cap.release()
        return dict(frames=[],reason='no_original_measured_crossing_anchor',inference_calls=0)
    anchor=max(eligible,key=lambda r:r['t']);first=max(0,math.floor(window['start_s']*fps))
    try:
        for step,index in enumerate(range(anchor['frame'],first-1,-1)):
            context=cached_frames.get(index)
            if context is None:
                break
            if step and (cached_frames[index+1].get('cut') or
                         context.get('evidence_segment')!=anchor.get('evidence_segment')):
                break
            ok,image=reader.read(index)
            if not ok:
                break
            key=(str(Path(video).resolve()),id(model),index,tuple(sorted(predict.items())))
            if key not in cache:
                cache[key]=measured_detections(model.predict(image,**predict)[0]);calls+=1
            else:hits+=1
            detections=list(cache[key])
            people=[unpack(p) for p in context.get('persons',[])]
            heads=[unpack(p) for p in context.get('head_context',[])]
            if step==0:
                # The original event supplies a measured anchor, not a fixed
                # video coordinate or a guessed new result.
                ball=unpack(anchor['ball'])
                detections=[d for d in detections if 'ball' not in d.cls_name.lower()]+[ball]
            roi={}
            if step%max(1,round(fps/detect['ball_roi_retry_hz']))==0 and step:
                if stream.preview_ball(step,detections,image,persons=heads)[0] is None:
                    for name,recover,enabled in [('ball_recovery',recover_region,detect['ball_roi_recovery']),
                                                ('rim_recovery',recover_rim,detect['ball_rim_recovery'])]:
                        if enabled:
                            extra,audit=recover(model,image,predict,stream,step)
                            calls+=bool(audit['ran']);detections+=extra;roi[name]=audit
            stream.update(step,step/fps,deduplicate_candidates(detections),people,
                          image=image,head_context=heads)
            row=stream.frames[-1]
            # Preserve the source context, including original on_court flags.
            result={k:row.get(k) for k in ('ball','ball_candidates','rim','rim_candidates')}
            result.update(frame=index,t=context['t'],persons=[dict(p) for p in context.get('persons',[])],
                          cut=context.get('cut'),evidence_segment=context.get('evidence_segment'),
                          analysis_direction='reverse',roi_audits=roi)
            for candidate in result.get('ball_candidates') or []:
                candidate.update(frame_id=index,timestamp=context['t'])
            rows.append(result)
    finally:cap.release()
    return dict(frames=sorted(rows,key=lambda r:r['frame']),inference_calls=calls,
                full_frame_cache_hits=hits,outcomes_discarded=True,
                time_basis='original_decoded_index_over_nominal_fps')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--enable',action='store_true');p.add_argument('--reference',type=Path)
    p.add_argument('--ocr-box',help='Known digit strip x,y,w,h in ORIGINAL pixels')
    p.add_argument('--ocr-end',type=float,default=0.)
    p.add_argument('--excluded-intervals',type=Path)
    p.add_argument('--team-map',type=Path,help='Approved same-video screen-side mapping JSON')
    p.add_argument('--forward-raw',type=Path);p.add_argument('--reanalyze',action='store_true')
    p.add_argument('--weights',type=Path,default=Path('models/BODD_yolov8n_0001.pt'))
    p.add_argument('--max-windows',type=int,default=6)
    p.add_argument('--visual-options',type=Path,help='Explicit validated detector options for isolated offline comparisons')
    p.add_argument('--confidence-floor',type=float,default=.9,
                   help='Offline OCR sensitivity comparison only; default .9')
    a=p.parse_args()
    if a.out.exists():p.error('Choose a new output directory')
    if a.enable and not (a.reference or a.ocr_box):p.error('Provide reference or explicit OCR ROI')
    if a.reanalyze and not a.forward_raw:p.error('Reanalysis requires a same-video forward trace')
    a.out.mkdir(parents=True);revision=freeze(a.out);digest=sha256(a.video)
    reference={};forward=[];cached={};cuts=[]
    if a.enable:
        if a.reference:
            reference=json.loads(a.reference.read_text())
            if reference.get('video_sha256')!=digest:raise ValueError('Reference video SHA mismatch')
        else:
            reader=_easyocr_reader(str(_easyocr_model_dir()))
            reference=scan(str(a.video),reader,[int(v) for v in a.ocr_box.split(',')],step=.5,max_seconds=a.ocr_end,diagnostic=True)
            reference['video_sha256']=digest
        write_json(a.out/'ocr_reference.json',reference)
    if a.forward_raw:
        raw=json.loads(a.forward_raw.read_text())
        if sha256(raw['video_path'])!=digest:raise ValueError('Forward trace video SHA mismatch')
        trace=raw['detections_meta']['legacy_shots'];forward=trace['events']
        cached={r['frame']:r for r in trace['frames']};cuts=[r['t'] for r in trace['frames'] if r.get('cut')]
    excluded=json.loads(a.excluded_intervals.read_text()) if a.excluded_intervals else []
    mapping=None
    if a.team_map:
        reviewed_map=json.loads(a.team_map.read_text())
        if reviewed_map.get('video_sha256')!=digest or reviewed_map.get('review_status')!='approved':
            raise ValueError('Team mapping must be reviewed and belong to this video')
        mapping=reviewed_map['mapping']
    report=investigate_score_changes(reference,forward,options=RecoveryOptions(enabled=a.enable,max_windows=a.max_windows,
                                     confidence_floor=a.confidence_floor),
                                     cuts=cuts,excluded_intervals=excluded,team_map=mapping)
    report.update(revision=revision,video=str(a.video),video_sha256=digest,
                  live_fusion_setting_untouched=True,human_truth_available=False)
    write_json(a.out/'recovery.json',report)
    if a.enable and a.reanalyze and report['windows']:
        from ultralytics import YOLO
        model=YOLO(str(a.weights));write_json(a.out/'model.json',{'path':str(a.weights),'sha256':sha256(a.weights)})
        opts={'imgsz':1280,'ball_candidate_conf':.15,'ball_low_conf_confirm':True,
              'ball_roi_recovery':True,'ball_rim_recovery':True,'ball_roi_retry_hz':15}
        if a.visual_options:opts=json.loads(a.visual_options.read_text())
        resolve_detect(opts)
        prediction_cache={}
        for i,w in enumerate(report['windows']):
            result=reanalyze(a.video,w,model,opts,cached,prediction_cache)
            write_json(a.out/f'window_{i:02d}.json',result)
            print(json.dumps({'window':i,'frames':len(result['frames']),'events':result['events']},ensure_ascii=False),flush=True)
    print(json.dumps({'facts':len(report['facts']),'windows':len(report['windows']),
                      'rejected':len(report['rejected']),'enabled':report['enabled']}),flush=True)


if __name__=='__main__':main()
