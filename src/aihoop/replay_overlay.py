"""Read-only replay boxes from saved detector observations; never run inference."""
from math import isfinite
from statistics import median

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
    previous_people = {}
    camera_x = camera_y = 0.0
    for row in legacy.get('frames') or []:
        t = row.get('t')
        if not isinstance(t, (int, float)) or not isfinite(t):
            continue
        people = {}
        for person in row.get('persons') or []:
            pb = box(person.get('xyxy'))
            pid = str(person.get('track_id') or '')
            if pb and pid and not person.get('predicted'):
                people[pid] = ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2)
        shifts = [(point[0] - previous_people[pid][0],
                   point[1] - previous_people[pid][1])
                  for pid, point in people.items() if pid in previous_people]
        if len(shifts) >= 3:
            dx = float(median(value[0] for value in shifts))
            dy = float(median(value[1] for value in shifts))
            if abs(dx) <= .08 * max(float(width), 1) and abs(dy) <= .08 * max(float(height), 1):
                camera_x += dx
                camera_y += dy
        previous_people = people
        players = []
        for person in row.get('persons') or []:
            b = box(person.get('xyxy'))
            if b and not person.get('predicted') and person.get('on_court') is not False:
                pid=str(person.get('track_id') or ''); identity=identities.get(pid) or {}
                players.append({'box': b, 'id': pid, 'jersey':identity.get('jersey'),'name':identity.get('name')})
        ball = row.get('ball') or {}
        b = box(ball.get('xyxy')) if not ball.get('predicted') and ball.get('cls') != 'motion_ball' else None
        rejection = ''
        # The scorer used to check only width. Tall head/logo boxes therefore
        # survived as balls. Apply the corrected two-axis gate to old traces too.
        size_limit = .06 * min(max(float(width), 1), 960.)
        if b and (max(b[2]-b[0], b[3]-b[1]) > size_limit or
                  max(b[2]-b[0], b[3]-b[1]) > 2.4 * max(1., min(b[2]-b[0], b[3]-b[1]))):
            b = None
            rejection = 'size_or_shape'
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
                       'ball': b, 'ball_suspect':suspect, 'rim': rb,
                       '_camera': (camera_x, camera_y), '_ball_rejection': rejection})

    # Review a whole measured run before calling it a basketball. A background
    # spectator moves in screen pixels during a pan, but remains nearly fixed after
    # subtracting the median person-track translation. Suppress such runs and leave
    # short/unconfirmed observations explicitly marked as suspect.
    measured = [i for i, row in enumerate(frames) if row.get('ball')]
    runs = []
    current = []
    for index in measured:
        row = frames[index]
        if (current and (row['t'] - frames[current[-1]]['t'] > .28 or row.get('cut') or
                         row.get('segment') != frames[current[-1]].get('segment'))):
            runs.append(current); current = []
        current.append(index)
    if current:
        runs.append(current)
    static_span = .04 * min(max(float(width), 1), 960.)
    for run in runs:
        first, last = frames[run[0]], frames[run[-1]]
        residual = []
        for index in run:
            row = frames[index]; b = row['ball']; cam = row['_camera']
            residual.append(((b[0]+b[2])/2-cam[0], (b[1]+b[3])/2-cam[1]))
        span = max(max(x for x, _ in residual)-min(x for x, _ in residual),
                   max(y for _, y in residual)-min(y for _, y in residual))
        is_static = len(run) >= 3 and last['t']-first['t'] >= .4 and span <= static_span
        confirmed = len(run) >= 2 and span > .015 * min(max(float(width), 1), 960.)
        for index in run:
            if is_static:
                frames[index]['ball'] = None
                frames[index]['_ball_rejection'] = 'camera_static'
            elif not confirmed:
                frames[index]['ball_suspect'] = True
    for row in frames:
        row.pop('_camera', None)
        row.pop('_ball_rejection', None)
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
