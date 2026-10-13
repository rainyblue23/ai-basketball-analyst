"""Court markings in the shared 28 x 15 diagram coordinate system.

NBA floor coordinates are scaled along each axis into this shared system so
that A/B calibrations, existing shot grids, and player coordinates agree.
The projected markings must undergo the same scaling as the landmarks.
"""
def geometry(standard="fiba"):
    if standard == "nba":
        sx, sy = 15 / 15.24, 28 / 28.6512
        return dict(standard="nba", lane_half=2.4384*sx, ft=5.7912*sy,
                    hoop=1.6002*sy, arc_x=7.239*sx, arc_y=7.239*sy,
                    corner_x=6.7056*sx, circle_x=1.8288*sx,
                    circle_y=1.8288*sy)
    return dict(standard="fiba", lane_half=2.45, ft=5.8, hoop=1.575,
                arc_x=6.75, arc_y=6.75, corner_x=6.6,
                circle_x=1.8, circle_y=1.8)


def infer_standard(dst):
    # Coordinates from our NBA landmark table carry its geometry even when an
    # older caller constructs Calibration without copying the profile field.
    g = geometry("nba")
    candidates = (14-g["ft"], 14-g["hoop"]-g["arc_y"])
    if any(abs(abs(float(p[1]))-v) < 1e-5 for p in dst or [] for v in candidates):
        return "nba"
    return "fiba"


def landmark_table(base, standard="fiba"):
    out = dict(base)
    g = geometry(standard)
    for end, sign in (("far",1), ("near",-1)):
        for side, x in (("left",-g["lane_half"]),("right",g["lane_half"])):
            out[f"lane_{end}_{side}"] = (x,sign*(14-g["ft"]))
            out[f"paint_base_{end}_{side}"] = (x,sign*14)
        out[f"ft_{end}"] = (0,sign*(14-g["ft"]))
        out[f"arc_{end}"] = (0,sign*(14-g["hoop"]-g["arc_y"]))
        out[f"hoop_{end}"] = (0,sign*(14-g["hoop"]))
    return out
