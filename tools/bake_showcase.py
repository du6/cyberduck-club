#!/usr/bin/env python3
"""bake_showcase.py — build the daily champions showcase for cyberduck.club.

Walks the PUBLIC ladder API and writes website/data/showcase.json:

    board  ->  top robot per weight class
           ->  that robot's best WIN            (/v1/robots/{id}/matches)
           ->  the fight's replay               (/v1/blobs/replays/...)
           ->  a decimated HIGHLIGHT CLIP + the winner's build

Everything it touches is anonymous: the leaderboard, the robot fight list and
the replay blobs are all AllowAnonymous, and a replay carries builds but never
programs (design doc §1.3). No credentials live in this script or in CI.

WHY IT BAKES INSTEAD OF LETTING THE BROWSER FETCH: the API sends no CORS
headers, so a page on cyberduck.club cannot read it directly. Running the
fetch server-side in CI sidesteps that entirely — and leaves the site fully
static, so it stays up and fast even when the API is down or cold-starting.

WHY A CLIP AND NOT THE WHOLE FIGHT: a full 80 s bout is ~780 KB gzipped per
match, which is both bad viewing and a repo that grows by megabytes a day.
The design doc makes the same point about content ("a 90 s match with 5 s of
fighting is bad replay content"), so this takes the CLIP_SECONDS ending at the
verdict — the finish, which is the part worth watching — at HZ_OUT.

Usage:  python3 website/tools/bake_showcase.py [--out PATH] [--api URL]
Exit 0 on success (including "nothing changed"), 1 only on a hard failure.
"""

import argparse, gzip, io, json, sys, urllib.request, urllib.error
from datetime import datetime, timezone

API_DEFAULT = "https://rb-api-902243335343.us-central1.run.app"
CATEGORIES = ["FEATHER", "LIGHT", "MIDDLE", "HEAVY", "SUPER"]

CLIP_SECONDS = 10.0     # maximum length of the highlight
CLIP_LEAD = 0.40        # put the biggest hit this far through the clip — see below
TAIL_PAD = 1.2          # end the clip this long after the LAST hit — see clip_window
MIN_ROOT_GAP = 1.5      # m between the two machines at the chosen blow — see clip_window

# ⚠ CLIP_LEAD WAS 0.72, AND IT COST TWO THINGS AT ONCE.
#
# At 0.72 the lead-in is 7.2 s and the tail trim leaves ~1.2 s, so the blow the
# whole clip exists for landed at 85% of it: seven seconds of driving, one hit,
# an abrupt stop. The hero copy promises "the biggest blow ... with the seconds
# EITHER SIDE of it", which is not what a 7-to-1 ratio is.
#
# The second cost was not obvious and is the more damaging one. The shot solver
# frames BOTH machines, so how far the camera sits back is decided by how far
# apart they are — and during a long run-up they are at opposite ends of the
# arena. Measured on the FEATHER champion at the clip's first frame: camera
# distance 9.94 against 4.66-5.47 for every other class, with the machines
# filling 21% of the frame height and ~79% empty floor. That is the DEFAULT
# view of the champions page, so the first thing every visitor saw was the
# widest, emptiest shot of the five. The camera was not wrong; it was framing
# a moment when the fight had not started.
#
# 0.40 gives four seconds of build-up, which is enough to see the machines
# close, and starts the clip when they are already closing.
HZ_PEAK = 10.0          # full recorded rate around the money shot
HZ_LEAD = 5.0           # half rate for the lead-in and the tail
PEAK_WINDOW = 2.0       # ± this many seconds of the hardest hit stays at HZ_PEAK
POS_DP, ROT_DP = 2, 3   # cm and ~0.06 degrees — far below what the eye sees
TIMEOUT = 30


def get(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": "cyberduck-showcase/1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
    return data if raw else json.loads(data.decode("utf-8"))


ORIENT = {"XP", "XN", "YP", "YN", "ZP", "ZN"}


def parse_build(build_text):
    """Build text -> [{id, mat, pos, axis, rot}] in placement order.
    Lines starting '#' are format markers (#fmt3-disc, #fmt4-gusset)."""
    out = []
    for line in (build_text or "").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split("|")
        if len(f) < 5:
            continue
        try:
            pos = [float(v) for v in f[1].split(",")]
            axis = [float(v) for v in f[3].split(",")]
        except ValueError:
            continue
        out.append({"id": f[0], "mat": (f[4].split(":")[0] or "Aluminum"),
                    "pos": [round(v, 3) for v in pos],
                    "axis": [round(v, 3) for v in axis],
                    "rot": float(f[2] or 0)})
    return out


def base_id(recorded_name):
    """'bladeZP_11' -> 'blade'; 'core_0' -> 'core'. The replay names a part
    <id><face>_<index>; the face suffix is a mounting orientation, not a
    different part, and the index is placement order."""
    stem = recorded_name.rsplit("_", 1)[0]
    if len(stem) > 2 and stem[-2:] in ORIENT:
        stem = stem[:-2]
    return stem


def orient_of(recorded_name):
    """The axis code baked into a recorded part name ("bladeZP_3" -> "ZP").

    ⚠ FOR SIX PART TYPES THE ORIENTATION IS NOT IN THE TRANSFORM. The builder
    does not rotate a pivot/spindle/ram/blade/wedge/hook — it draws it through
    `VisualId(def, part.DriveAxis())`, the id with this code appended, and
    PartVisualFactory turns the suffix back into the direction the part points.
    So a consumer holding only the recorded transform CANNOT recover which way
    the weapon faces, and this suffix is the only carrier. Dropping it, which
    this baker used to do, renders every one of them in its fallback
    orientation — a robot whose weapons all point the same wrong way."""
    stem = recorded_name.rsplit("_", 1)[0]
    return stem[-2:] if len(stem) > 2 and stem[-2:] in ORIENT else ""


def axis_code(vec):
    """AxisCode() from BuilderManager: dominant component, then its sign.
    Kept as a transcription — same tie-breaking order (x, then y, then z
    only on a strict >), same 0.5 deadband that yields no code at all."""
    if not vec or len(vec) < 3:
        return ""
    ax, best = 0, abs(vec[0])
    if abs(vec[1]) > best:
        ax, best = 1, abs(vec[1])
    if abs(vec[2]) > best:
        ax, best = 2, abs(vec[2])
    if best < 0.5:
        return ""
    return "XYZ"[ax] + ("P" if vec[ax] >= 0 else "N")


def align(build_parts, recorded_names):
    """Pair the BUILD list with the REPLAY's recorded-part list.

    ⚠ THEY ARE NOT THE SAME LENGTH, and assuming they were is how a robot
    ends up rendered with its parts shuffled. Measured on Spinner1: 45 build
    lines, 39 recorded — the six WHEELS are missing, because raycast wheels
    are not CompoundRobot parts and the recorder only walks parts. So the
    frames animate 39 things and the other six have to be carried some other
    way (rigidly, off the root, which IS recorded).

    Walks both in order matching base ids: matched -> animated by frame index;
    unmatched build entry -> a static extra pinned to the chassis."""
    animated, extras = [], []
    j = 0
    for b in build_parts:
        if j < len(recorded_names) and base_id(recorded_names[j]) == b["id"]:
            # Prefer the RECORDED name's suffix over the build text's axis
            # vector: it is what the game itself drew this part with, rather
            # than a re-derivation of it.
            ax = orient_of(recorded_names[j]) or axis_code(b.get("axis"))
            e = {"id": b["id"], "mat": b["mat"]}
            if ax:
                e["ax"] = ax
            # ⚠ YAW IS IN THE SHAPE, NOT THE TRANSFORM. BuilderManager passes
            # `part.Half() * 2` as the size, and Half() applies the yaw — so a
            # beam placed at 90 reaches BuildPart with x and z SWAPPED and is
            # drawn long-along-X. Nothing rotates. A consumer that draws the
            # unyawed shape at the recorded transform lays every turned beam
            # the wrong way across the chassis.
            if b.get("rot"):
                e["yaw"] = int(b["rot"]) % 360
            animated.append(e)
            j += 1
        else:
            # An extra has no recorded name to read a suffix from, so its axis
            # can only come from the build text's own vector.
            extra = dict(b)
            ax = axis_code(b.get("axis"))
            if ax:
                extra["ax"] = ax
            if b.get("rot"):
                extra["yaw"] = int(b["rot"]) % 360
            extras.append(extra)
    return animated, extras, j == len(recorded_names)


def is_house(owner):
    return (owner or "").strip().lower() == "the yard"


def ranked_wins(matches):
    """Every usable win, best first.

    "Best" is two keys deep. The OUTER key is whether the opponent was a real
    player: a win over another human's design is the story this page is here to
    tell, and three of five classes were showing a win over a house bot because
    rating gain alone ranked the tutorial machines highest. Where only a house
    win exists we still show it — framed honestly (see `opponentHouse`).

    The INNER key is rating gain, the ladder's own measure of 'who did you
    beat'. Falls back to most recent when the deltas are missing (older matches
    predate the field)."""
    wins = [m for m in matches if m.get("outcome") == "WON" and m.get("replayUrls")]

    def gain(m):
        try:
            d = json.loads(m.get("ratingDeltas") or "{}")
            side = d.get("challenger") if m.get("verdict") == "CHALLENGER" else d.get("defender")
            return float(side["after"]) - float(side["before"])
        except Exception:
            return -1e9
    wins.sort(key=lambda m: (0 if is_house(m.get("opponentOwner")) else 1,
                             gain(m), m.get("completedAt") or ""), reverse=True)
    return wins


def q_conj_rot(q, v):
    """Rotate v by the CONJUGATE of quaternion q (i.e. world -> local)."""
    x, y, z, w = -q[0], -q[1], -q[2], q[3]
    # v' = q v q*
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return [v[0] + w * tx + (y * tz - z * ty),
            v[1] + w * ty + (z * tx - x * tz),
            v[2] + w * tz + (x * ty - y * tx)]


def build_parts_matched(build_parts, recorded_names):
    """The build entries that DID match a recorded part, in frame order."""
    matched, j = [], 0
    for b in build_parts:
        if j < len(recorded_names) and base_id(recorded_names[j]) == b["id"]:
            matched.append(b)
            j += 1
    return matched


def place_extras(extras, matched, pose, log, cat):
    """Put unrecorded parts (wheels) into ROOT-LOCAL space.

    For every part we have both coordinates for, root-local position is
    conj(rootQuat) * (worldPos - rootPos). Subtracting its build position
    gives a constant offset between the two frames; averaging over all of
    them is robust to any single part having settled a millimetre."""
    if not extras or not matched or len(pose) < 14:
        return [dict(e, local=e["pos"]) for e in extras]
    rp, rq = pose[0:3], pose[3:7]
    deltas = []
    for i, b in enumerate(matched):
        o = 7 + i * 7
        if o + 2 >= len(pose):
            break
        rel = q_conj_rot(rq, [pose[o] - rp[0], pose[o + 1] - rp[1], pose[o + 2] - rp[2]])
        deltas.append([rel[k] - b["pos"][k] for k in range(3)])
    if not deltas:
        return [dict(e, local=e["pos"]) for e in extras]
    n = len(deltas)
    avg = [sum(d[k] for d in deltas) / n for k in range(3)]
    spread = max(max(abs(d[k] - avg[k]) for d in deltas) for k in range(3))
    if spread > 0.25:
        # Not a rigid translation — say so rather than quietly misplacing parts.
        log.append(f"{cat}: ⚠ build->root offset is not constant (spread {spread:.2f} m)")
    return [dict(e, local=[round(e["pos"][k] + avg[k], 3) for k in range(3)]) for e in extras]


def load_replay(url):
    raw = get(url, raw=True)
    if url.endswith(".gz"):
        raw = gzip.decompress(raw)
    header, frames, events = None, [], []
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        kind, _, payload = line.partition(" ")
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if kind == "H":
            header = obj
        elif kind == "F":
            frames.append(obj)
        elif kind == "E":
            events.append(obj)
    return header, frames, events


def root_gap_at(frames, t):
    """Distance between the two machines' roots at time t, in metres.

    A frame's first three floats are the root position (see ReplayRecorder's
    Pack): [rootPos3, rootRot4, then 7 per part]. Takes the sample nearest t on
    each side, so it is robust to the two sides not being written on exactly the
    same timestamps."""
    best = {}
    for f in frames:
        s = f.get("s", 0)
        d = abs(f.get("t", 0) - t)
        if s not in best or d < best[s][0]:
            vals = f.get("f") or []
            if len(vals) >= 3:
                best[s] = (d, vals[0:3])
    if 0 not in best or 1 not in best:
        return 1e9          # unknown: never let it disqualify a hit
    a, b = best[0][1], best[1][1]
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def clip_window(frames, events):
    """WHERE THE FIGHT ACTUALLY IS.

    ⚠ NOT the last N seconds. Measured on the FEATHER champion's winning
    match: all 47 damage events land between t=1.1 s and t=17.5 s, and then
    the bout runs a further 26 SECONDS to the verdict at t=44 with nothing
    happening at all. Taking "the finish" literally clipped the emptiest
    stretch of the whole match — two machines idling, zero hits — which is
    precisely why the page looked boring.

    So: find the hardest hit, and cut a window that leads into it and lands
    just after, giving build-up, the blow, and a beat to see the damage.

    ⚠ AND CUT THE TAIL. The window used to be a flat CLIP_SECONDS long, which
    on the FEATHER champion left 2.8 s — 28% of the clip — running after the
    last hit of the fight: two machines driving around an empty floor, on loop,
    as the closing image. The clip now ends TAIL_PAD after the final impact.
    Returns (t0, t1, peak)."""
    t_end = max(f["t"] for f in frames) if frames else 0.0
    hits = [e for e in events if e.get("e") == "hit" and float(e.get("a", 0)) > 0]
    if not hits:
        return max(0.0, t_end - CLIP_SECONDS), t_end, t_end
    # ⚠ PREFER THE HARDEST HIT WE CAN SHOW THE CONSEQUENCE OF. The single
    # biggest blow is often the FINISHING one, and a finishing blow has no
    # fight after it to cut to. Measured on the LIGHT champion: its hardest hit
    # (145.4) lands at t=35.81 in a match that ends at t=35.85 — forty
    # milliseconds later — so the clip ended ON the impact and the viewer never
    # saw what it did. That same match has a 110.4 at t=26.48 with nine seconds
    # of fight after it. So: take the hardest hit that still leaves TAIL_PAD of
    # footage, and fall back to the true peak only if no hit qualifies (a short
    # bout decided by its opening exchange).
    showable = [h for h in hits if h["t"] <= t_end - TAIL_PAD]

    # ⚠ AND PREFER A BLOW YOU CAN SEE BOTH MACHINES IN. A hit lands when the two
    # robots are touching, and the tightest ones leave them stacked front-to-back
    # from every camera bearing that has room behind it — so the opponent is
    # occluded and the frame reads as one robot with debris on it, not a fight.
    # Measured on the SUPER champion: its heaviest showable hit had the roots
    # 1.09 m apart, and the opponent's box rendered ~99% inside the champion's,
    # with no readable ring. The same match carries hits at 1.74–1.91 m.
    # The camera cannot fix this — separation the viewpoint does not have is not
    # recoverable by moving the viewpoint — so choose the heaviest blow with
    # enough daylight between the machines, and fall back to the plain heaviest
    # if no hit qualifies.
    spaced = [h for h in showable if root_gap_at(frames, h["t"]) >= MIN_ROOT_GAP]
    peak = max(spaced or showable or hits, key=lambda e: float(e.get("a", 0)))["t"]
    t0 = max(0.0, peak - CLIP_SECONDS * CLIP_LEAD)
    t1 = min(t_end, t0 + CLIP_SECONDS)
    last_hit = max((h["t"] for h in hits if t0 <= h["t"] <= t1), default=peak)
    return t0, min(t1, last_hit + TAIL_PAD), peak


def clip(frames, events):
    """Keep the highlight window, at full rate where it matters.

    Payload is a real constraint (this file ships in the repo and is fetched by
    every visitor), so the lead-in and the tail run at HZ_LEAD and only the
    PEAK_WINDOW around the hardest hit keeps every recorded frame. The page
    interpolates between samples either way; the difference is only visible
    where the geometry changes fast, which is exactly the window we keep."""
    if not frames:
        return [], [], 0.0, 0.0
    t0, t_end, peak = clip_window(frames, events)

    def keep(t):
        if abs(t - peak) <= PEAK_WINDOW:
            return True
        # ⚠ DECIMATE ON TIME, NOT ON PER-SIDE INDEX. Both sides are recorded at
        # the same instants, so a time-derived parity keeps them in lockstep; a
        # per-side index does not survive one side having a dropped sample, and
        # a clip where one robot updates twice as often as the other looks like
        # a physics bug.
        return int(round(t * 10.0)) % max(1, int(round(10.0 / HZ_LEAD))) == 0

    per_side = {0: [], 1: []}
    for f in frames:
        per_side.setdefault(f.get("s", 0), []).append(f)
    out = []
    for side, lst in per_side.items():
        lst.sort(key=lambda f: f["t"])
        for f in lst:
            if f["t"] < t0 or f["t"] > t_end or not keep(f["t"]):
                continue
            vals = f.get("f") or []
            packed = []
            for j in range(0, len(vals), 7):
                p = vals[j:j + 7]
                if len(p) < 7:
                    break
                packed += [round(p[0], POS_DP), round(p[1], POS_DP), round(p[2], POS_DP),
                           round(p[3], ROT_DP), round(p[4], ROT_DP),
                           round(p[5], ROT_DP), round(p[6], ROT_DP)]
            out.append({"t": round(f["t"] - t0, 2), "s": side, "f": packed})
    out.sort(key=lambda f: (f["t"], f["s"]))

    ev = [{"t": round(e["t"] - t0, 2), "e": e.get("e", ""), "s": e.get("s", -1),
           "a": round(float(e.get("a", 0)), 1),
           "x": round(float(e.get("x", 0)), 2), "y": round(float(e.get("y", 0)), 2),
           "z": round(float(e.get("z", 0)), 2)}
          for e in events if t0 <= e.get("t", 0) <= t_end]
    return out, ev, round(t_end - t0, 2), round(peak - t0, 2)


def pack_pose(frames, side):
    """The recorded OPENING frame for one side, flattened and rounded."""
    opening = min((f for f in frames if f.get("s") == side), key=lambda f: f["t"], default=None)
    pose = []
    for j in range(0, len((opening or {}).get("f") or []), 7):
        p = opening["f"][j:j + 7]
        if len(p) < 7:
            break
        pose += [round(p[0], POS_DP), round(p[1], POS_DP), round(p[2], POS_DP),
                 round(p[3], ROT_DP), round(p[4], ROT_DP),
                 round(p[5], ROT_DP), round(p[6], ROT_DP)]
    return pose


def build_category(api, cat, entry, log, used_matches):
    robot_id = entry["robotId"]
    name = entry.get("robotName") or "?"
    house = is_house(entry.get("owner"))
    card = {
        "category": cat,
        "robotName": name,
        "owner": entry.get("owner") or "",
        "rating": round(float(entry.get("rating") or 0), 1),
        "provisional": bool(entry.get("provisional")),
        "house": house,          # the class is unclaimed: a house bot still holds it
        "fight": None,
        "build": None,
    }
    try:
        ms = get(f"{api}/v1/robots/{robot_id}/matches?limit=50").get("matches", [])
    except urllib.error.HTTPError as e:
        log.append(f"{cat}: fight list HTTP {e.code} — showing the board entry only")
        return card
    wins = ranked_wins(ms)
    if not wins:
        log.append(f"{cat}: {name} has no completed win with a replay yet")
        return card

    # ⚠ ONE MATCH, ONE CLASS. The same robot id tops both HEAVY and SUPER, so
    # the naive "its best win" put the IDENTICAL clip under two tabs and the
    # page looked broken. Walk down this robot's wins to the best one no other
    # class has taken; if every one is spoken for, the class shows the
    # unclaimed treatment rather than a repeat.
    for win in wins:
        if win["id"] in used_matches:
            continue
        rurl = next((u for u in win["replayUrls"] if u.endswith(".rbr.gz")), None) \
            or next((u for u in win["replayUrls"] if u.endswith(".rbr")), None)
        if not rurl:
            log.append(f"{cat}: skipping {win['id'][:8]} — no .rbr replay")
            continue
        header, frames, events = load_replay(rurl)
        if not header or not frames:
            log.append(f"{cat}: replay {win['id'][:8]} was empty or unreadable")
            continue
        used_matches.add(win["id"])
        break
    else:
        log.append(f"{cat}: every win by {name} is already shown under another class")
        return card

    # Which side is the champion? The replay names the sides; match on the
    # robot name rather than assuming challenger==A.
    a_is_champ = (header.get("aName") or "") == name
    build_text = header.get("aBuild") if a_is_champ else header.get("bBuild")
    rec_names = header.get("aParts" if a_is_champ else "bParts") or []
    parts, extras, exact = align(parse_build(build_text), rec_names)
    if not exact:
        log.append(f"{cat}: ⚠ {name} build/replay part alignment is partial "
                   f"({len(parts)} matched of {len(rec_names)} recorded)")

    opp_build = parse_build(header.get("bBuild") if a_is_champ else header.get("aBuild"))
    opp_rec = header.get("bParts" if a_is_champ else "aParts") or []
    opp_parts, opp_extras, _ = align(opp_build, opp_rec)

    cf, ce, dur, peak_t = clip(frames, events)

    # THE MODEL POSE IS THE FIGHT'S OPENING FRAME, not the clip's first frame.
    # The clip starts 12 s from the end, where the champion may be tipped over
    # and missing an arm — a fine thing to watch and a poor thing to exhibit.
    # At t≈0 the machine stands exactly as it was built, and using a recorded
    # world pose means the viewer never has to re-derive orientation from the
    # build text's rot/axis fields (a second parser is a second thing to drift).
    champ_side = 0 if a_is_champ else 1
    foe_side = 1 - champ_side
    pose = pack_pose(frames, champ_side)
    opp_pose = pack_pose(frames, foe_side)

    # ⚠ BUILD COORDINATES ARE NOT ROOT-RELATIVE. A build line puts a wheel at
    # y=0.70 because that is where it sits in the BUILDER's space; the robot's
    # recorded root is somewhere else entirely (the chassis lands at world
    # y≈0.17). Pinning extras straight off the root floats them above the
    # machine — six wheels hanging in the air over the roof, which is exactly
    # how the first render came out. Recover the constant build->root offset
    # from parts we have BOTH coordinates for, then place the extras with it.
    #
    # ⚠ AND THE OPPONENT NEEDS THE SAME TREATMENT. This used to ship `[]`, on
    # the reasoning that the opponent is only seen mid-fight — but wheels are
    # extras, so every opponent slid around the arena on nothing at all. Its
    # own opening pose resolves its own offset; the champion's does not.
    card["build"] = {
        "parts": parts,            # frame-order, animated
        "extras": place_extras(extras, build_parts_matched(parse_build(build_text), rec_names),
                               pose, log, cat),
        "side": champ_side,
        "pose": pose,
        "opponentParts": opp_parts,
        "opponentExtras": place_extras(opp_extras, build_parts_matched(opp_build, opp_rec),
                                       opp_pose, log, cat + " (opponent)"),
    }
    opp_name = (win.get("opponentName")
                or header.get("bName" if a_is_champ else "aName") or "?")
    opp_owner = win.get("opponentOwner") or ""
    card["fight"] = {
        "matchId": win["id"],
        "opponent": opp_name,
        "opponentOwner": opp_owner,
        "opponentHouse": is_house(opp_owner),   # frame it honestly on the page
        "completedAt": win.get("completedAt"),
        "arenaHalf": header.get("arenaHalf", 7.0),
        "duration": dur,
        "peakAt": peak_t,          # clip-relative time of the hardest hit
        "frames": cf,
        "events": ce,
        "replayUrl": rurl,
    }
    log.append(f"{cat}: {name} vs {opp_name} — {len(cf)} frames, {len(parts)} parts, "
               f"{dur}s, peak at {peak_t}s, {len(card['build']['opponentExtras'])} opp extras")
    return card


def card_from_local_replay(path, champ_name, t0, t1, cat, owner, log):
    """One showcase card cut from a LOCAL .rbr.gz over an EXPLICIT window.

    Why this exists: the daily walk above picks its clip around the biggest
    HIT, because that is the champions page's promise. A promo shot may want a
    moment that lands nowhere near a damage peak — the 2026-08-20 cut wanted
    Spinner1 five metres in the air, which does no damage at all and which
    clip_window would never choose.

    Everything else is deliberately the SAME machinery — align, place_extras,
    pack_pose, the POS_DP/ROT_DP packing — so a promo clip and a champions
    clip render identically. The only substitution is the window.
    """
    raw = gzip.decompress(open(path, "rb").read()) if path.endswith(".gz") \
        else open(path, "rb").read()
    header, frames, events = None, [], []
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        kind, _, payload = line.partition(" ")
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if kind == "H":
            header = obj
        elif kind == "F":
            frames.append(obj)
        elif kind == "E":
            events.append(obj)
    if not header or not frames:
        raise SystemExit(f"{path}: no header or no frames")

    a_is_champ = (header.get("aName") or "") == champ_name
    build_text = header.get("aBuild") if a_is_champ else header.get("bBuild")
    rec_names = header.get("aParts" if a_is_champ else "bParts") or []
    parts, extras, exact = align(parse_build(build_text), rec_names)
    if not exact:
        log.append(f"⚠ {champ_name} build/replay alignment partial "
                   f"({len(parts)} of {len(rec_names)})")
    opp_build = parse_build(header.get("bBuild") if a_is_champ else header.get("aBuild"))
    opp_rec = header.get("bParts" if a_is_champ else "aParts") or []
    opp_parts, opp_extras, _ = align(opp_build, opp_rec)

    # The explicit window, packed exactly as clip() packs the daily one. Every
    # frame inside it is kept — a 2.8 s highlight is small, and decimating the
    # apex of a throw is how a launch turns into a teleport.
    out = []
    per_side = {}
    for f in frames:
        per_side.setdefault(f.get("s", 0), []).append(f)
    for side, lst in per_side.items():
        lst.sort(key=lambda f: f["t"])
        for f in lst:
            if f["t"] < t0 or f["t"] > t1:
                continue
            vals = f.get("f") or []
            packed = []
            for j in range(0, len(vals), 7):
                p = vals[j:j + 7]
                if len(p) < 7:
                    break
                packed += [round(p[0], POS_DP), round(p[1], POS_DP), round(p[2], POS_DP),
                           round(p[3], ROT_DP), round(p[4], ROT_DP),
                           round(p[5], ROT_DP), round(p[6], ROT_DP)]
            out.append({"t": round(f["t"] - t0, 2), "s": side, "f": packed})
    out.sort(key=lambda f: (f["t"], f["s"]))
    ev = [{"t": round(e["t"] - t0, 2), "e": e.get("e", ""), "s": e.get("s", -1),
           "a": round(float(e.get("a", 0)), 1),
           "x": round(float(e.get("x", 0)), 2), "y": round(float(e.get("y", 0)), 2),
           "z": round(float(e.get("z", 0)), 2)}
          for e in events if t0 <= e.get("t", 0) <= t1]

    champ_side = 0 if a_is_champ else 1
    pose = pack_pose(frames, champ_side)
    opp_pose = pack_pose(frames, 1 - champ_side)

    # ⚠ peakAt is the HEIGHT peak here, not a damage peak. The page uses it to
    # decide where to hold; pointing it at the apex is the whole point.
    peak_t, peak_y = 0.0, -1e9
    for f in frames:
        if f.get("s") != 1 - champ_side or not (t0 <= f["t"] <= t1):
            continue
        vals = f.get("f") or []
        for j in range(1, len(vals), 7):
            if vals[j] > peak_y:
                peak_y, peak_t = vals[j], f["t"]
    log.append(f"{champ_name}: window {t0}-{t1}s, {len(out)} frames, "
               f"opponent apex {peak_y:.2f} m at clip t={peak_t - t0:.2f}s")

    return {
        "category": cat, "robotName": champ_name, "owner": owner,
        "rating": 0.0, "provisional": False, "house": False,
        "build": {
            "parts": parts,
            "extras": place_extras(extras, build_parts_matched(parse_build(build_text), rec_names),
                                   pose, log, cat),
            "side": champ_side, "pose": pose,
            "opponentParts": opp_parts,
            "opponentExtras": place_extras(opp_extras, build_parts_matched(opp_build, opp_rec),
                                           opp_pose, log, cat + " (opponent)"),
        },
        "fight": {
            "matchId": header.get("matchId", "local"),
            "opponent": header.get("bName" if a_is_champ else "aName") or "?",
            "opponentOwner": "", "opponentHouse": False,
            "completedAt": None,
            "arenaHalf": header.get("arenaHalf", 7.0),
            "duration": round(t1 - t0, 2),
            "peakAt": round(peak_t - t0, 2),
            "frames": out, "events": ev, "replayUrl": "",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    # ⚠ PROMO MODE writes a SEPARATE file and never touches the daily walk.
    # The champions page fetches /data/showcase.json, so a promo cut is served
    # by pointing a LOCAL http server at a swapped copy — the public showcase
    # is never edited to make a video.
    ap.add_argument("--from-replay", help="local .rbr.gz to cut a promo clip from")
    ap.add_argument("--champ", default="", help="which side is the hero (replay aName/bName)")
    ap.add_argument("--t0", type=float, default=0.0)
    ap.add_argument("--t1", type=float, default=0.0)
    ap.add_argument("--api", default=API_DEFAULT)
    ap.add_argument("--out", default="website/data/showcase.json")
    args = ap.parse_args()

    if args.from_replay:
        log = []
        card = card_from_local_replay(args.from_replay, args.champ,
                                      args.t0, args.t1, "PROMO", "", log)
        doc = {"generated": datetime.now(timezone.utc).isoformat(),
               "season": 0, "seasonEndsAt": None,
               "clipSeconds": round(args.t1 - args.t0, 2),
               "champions": [card], "notes": log}
        with open(args.out, "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        print(f"wrote {args.out}  {len(json.dumps(doc))/1024:.0f} KB  (promo clip)")
        for line in log:
            print("  ·", line)
        return 0

    log = []
    board = get(f"{args.api}/v1/leaderboard?limit=200")
    entries = board.get("entries", [])
    cards = []
    used_matches = set()
    for cat in CATEGORIES:
        in_cat = [e for e in entries if e.get("category") == cat]
        if not in_cat:
            log.append(f"{cat}: no ranked robots")
            continue
        in_cat.sort(key=lambda e: float(e.get("rating") or 0), reverse=True)
        cards.append(build_category(args.api, cat, in_cat[0], log, used_matches))

    doc = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": board.get("season"),
        "seasonEndsAt": board.get("seasonEndsAt"),
        "clipSeconds": CLIP_SECONDS,
        "champions": cards,
        "notes": log,
    }
    with open(args.out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    size = len(json.dumps(doc, separators=(",", ":")))
    print(f"wrote {args.out}  {size/1024:.0f} KB  {len(cards)} classes")
    for line in log:
        print("  ·", line)
    # A showcase with no fights at all is a failure worth failing on: it means
    # the walk broke, not that the ladder is quiet.
    if cards and not any(c["fight"] for c in cards):
        print("NO fights resolved — refusing to publish an empty showcase", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
