"""Curated local examples: immutable snapshots, never arbitrary job lookup."""
import json
from pathlib import Path
from fastapi import HTTPException

def entries(root):
    p = Path(root)/'data/example_gallery.json'
    if not p.exists(): return []
    return json.loads(p.read_text(encoding='utf-8')).get('examples', [])

def resolve(root, job_id):
    for item in entries(root):
        if job_id == 'example_' + item['id']:
            if not item.get('prepared_at'):
                raise HTTPException(409, '样例正在准备')
            directory = (Path(root)/'out/examples'/item['id']).resolve()
            if not directory.is_relative_to((Path(root)/'out/examples').resolve()):
                raise HTTPException(404, '样例不存在')
            if not (directory/'game.json').exists():
                raise HTTPException(409, '样例正在准备')
            return item, directory
    raise HTTPException(404, '样例不存在')

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
            review = (game.get('meta') or {}).get('sample_review')
            if review:
                row['sample_review'] = review
        except HTTPException:
            row['ready']=False
        result.append(row)
    return result
