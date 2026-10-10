"""Read-only replay boxes from saved detector observations; never run inference."""
from math import isfinite

def detection_overlay(raw):
    width, height = raw.get('width', 0), raw.get('height', 0)
    meta = raw.get('detections_meta') or {}
    legacy = meta.get('legacy_shots') or {}
    frames = []
    identities=raw.get("players") or {}
    if isinstance(identities,list):identities={p["player_id"]:p for p in identities}
    def box(value):
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            v = [float(x) for x in value]
        except (TypeError, ValueError):
            return None
        if not all(isfinite(x) for x in v) or v[2] <= v[0] or v[3] <= v[1]:
            return None
        return [round(x, 2) for x in v]
    for row in legacy.get('frames') or []:
        t = row.get('t')
        if not isinstance(t, (int, float)) or not isfinite(t):
            continue
        players = []
        for person in row.get('persons') or []:
            b = box(person.get('xyxy'))
            if b and not person.get('predicted') and person.get('on_court') is not False:
                pid=str(person.get('track_id') or ''); identity=identities.get(pid) or {}
                players.append({'box': b, 'id': pid, 'jersey':identity.get('jersey'),'name':identity.get('name')})
        ball = row.get('ball') or {}
        b = box(ball.get('xyxy')) if not ball.get('predicted') else None
        # A ball centered inside a person's head area can also be the head.
        # Describe ambiguity only: real release frames can share this geometry.
        suspect=False
        if b:
            cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
            suspect=any(p['box'][0]<=cx<=p['box'][2] and p['box'][1]<=cy<=p['box'][1]+.23*(p['box'][3]-p['box'][1]) for p in players)
        # Only show the selected observation, never stale tracked coordinates.
        rim = row.get('rim') or {}
        rb = box(rim.get('xyxy')) if not rim.get('predicted') else None
        frames.append({'t': t, 'frame': row.get('frame'), 'cut': bool(row.get('cut')),
                       'segment': row.get('evidence_segment'), 'players': players,
                       'ball': b, 'ball_suspect':suspect, 'rim': rb})
    if not frames:
        grouped = {}
        for obs in raw.get('player_obs') or []:
            t = obs.get('t'); b = box(obs.get('box'))
            if isinstance(t, (int, float)) and isfinite(t) and b:
                row = grouped.setdefault(t, {'t': t, 'players': [], 'ball': None, 'rim': None, 'cut': False})
                pid=str(obs.get('player_id') or '');identity=identities.get(pid) or {}
                row['players'].append({'box': b, 'id':pid,'jersey':identity.get('jersey'),'name':identity.get('name')})
        frames = list(grouped.values())
    frames.sort(key=lambda x: x['t'])
    return {'available': bool(frames and width and height), 'width': width, 'height': height,
            'fps': raw.get('fps') or 30, 'frames': frames, 'identities':identities,
            'reason': '' if frames else '这份任务没有保存检测框，请重新分析。'}
