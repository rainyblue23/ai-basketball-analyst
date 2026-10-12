"""Curated local examples and portable published snapshots."""
import json
from pathlib import Path
from fastapi import HTTPException


def entries(root):
    root=Path(root)
    shipped=root/'examples/catalog.json'
    rows=json.loads(shipped.read_text(encoding='utf-8')).get('examples',[]) if shipped.exists() else []
    merged={r['id']:dict(r) for r in rows}
    local=root/'data/example_gallery.json'
    if local.exists():
        for r in json.loads(local.read_text(encoding='utf-8')).get('examples',[]):
            video=Path(r.get('video_path') or '')
            if not video.is_absolute():video=root/video
            if r['id'] not in merged or video.is_file():merged[r['id']]=dict(r)
    for r in merged.values():
        p=Path(r.get('video_path') or '')
        if not p.is_absolute():r['video_path']=str(root/p)
    return list(merged.values())


def resolve(root, job_id):
    for item in entries(root):
        if job_id != 'example_'+item['id']:continue
        if not item.get('prepared_at'):raise HTTPException(409,'样例正在准备')
        base=Path(root)/('examples' if item.get('bundled') else 'out/examples')
        directory=(base/item['id']).resolve()
        if not directory.is_relative_to(base.resolve()):raise HTTPException(404,'样例不存在')
        if not (directory/'game.json').exists():raise HTTPException(409,'样例正在准备')
        return item,directory
    raise HTTPException(404,'样例不存在')


def catalog(root):
    result=[]
    for item in entries(root):
        row={k:item[k] for k in ('id','title','description','duration','source_url') if k in item}
        row['job_id']='example_'+item['id']
        try:
            _,directory=resolve(root,row['job_id'])
            game=json.loads((directory/'game.json').read_text(encoding='utf-8'))
            shots=[x for x in game.get('timeline',[]) if x.get('type','shot')=='shot']
            row.update(ready=True,shots=len(shots),made=sum(x.get('result')=='made' for x in shots),unknown=sum(x.get('result')=='unknown' for x in shots))
            review=(game.get('meta') or {}).get('sample_review')
            if review:row['sample_review']=review
        except HTTPException:row['ready']=False
        result.append(row)
    return result
