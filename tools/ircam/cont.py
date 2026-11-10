import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2")
import json, statistics as st, collections, bisect, os
from common import *
TOL = 0.13
def measure(solo, orch):
    P, bpb, pend, _, _ = load(solo); O, _, oend, _, _ = load(orch)
    pn = sorted(n for v in P.values() for n in v)
    on = sorted((s, e, p, k) for k, v in O.items() for s, e, p, _ in v); ostarts = [x[0] for x in on]
    # 1. short piano notes: literal carriers
    shorts = [n for n in pn if n[1] - n[0] < 0.5]
    car = []
    for n in shorts:
        lo, hi = bisect.bisect_left(ostarts, n[0] - TOL), bisect.bisect_right(ostarts, n[0] + TOL)
        car.append({k for s2, e2, q, k in on[lo:hi] if q % 12 == n[2] % 12})
    lit = sum(1 for c in car if c) / max(1, len(shorts))
    # 2. continuity of fast stream: consecutive short notes (gap<=0.6 beat) share an instrument
    pairs = same = 0
    for (a, ca), (b, cb) in zip(zip(shorts, car), zip(shorts[1:], car[1:])):
        if 1e-6 < b[0] - a[0] <= 0.6 and ca and cb:
            pairs += 1; same += bool(ca & cb)
    # 3. segments per instrument (gap >= 1 beat splits), in bars
    segs = []; 
    for k, v in O.items():
        v = sorted(v); s0, e0 = v[0][0], v[0][1]
        for s, e, p, _ in v[1:]:
            if s - e0 >= 1.0: segs.append((e0 - s0) / bpb); s0 = s
            e0 = max(e0, e)
        segs.append((e0 - s0) / bpb)
    nb = max(pend, oend) / bpb
    # 4. sounding share: how much of piece each instrument sounds
    snd = []
    for k, v in O.items():
        tot = 0; cur_s, cur_e = None, None
        for s, e, p, _ in sorted(v):
            if cur_e is None or s > cur_e: 
                if cur_e is not None: tot += cur_e - cur_s
                cur_s, cur_e = s, e
            else: cur_e = max(cur_e, e)
        tot += cur_e - cur_s; snd.append(tot / max(pend, oend))
    # 5. silence between consecutive notes inside a segment ("дырявость"): share of notes followed by a rest 0.1..1 beat
    holes = tot_n = 0
    for k, v in O.items():
        v = sorted(v)
        for a, b in zip(v, v[1:]):
            if b[0] > a[0] + 1e-6:
                tot_n += 1; g = b[0] - a[1]
                if 0.1 <= g < 1.0: holes += 1
    return dict(bars=round(nb), tracks=len(O), short_share=round(len(shorts) / len(pn), 2), lit=round(lit, 2), stream_same=round(same / max(1, pairs), 2), pairs=pairs,
                seg_med=round(st.median(segs), 1), seg_short=round(sum(1 for x in segs if x < 1.0) / len(segs), 2), entries_per_track_100bars=round(100 * len(segs) / len(O) / nb, 1),
                sounding=round(st.median(snd), 2), holes=round(holes / max(1, tot_n), 2))
if __name__ == "__main__":
    S = "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/"
    inv = json.load(open("inventory.json"))
    rows = []
    for r in inv:
        if r["folder"] != "bouliane": continue
        orig = any(x in r["solo"] for x in ("OrchBouliane", "OrcBouliane", "OrchCaplet", "Ravel", "Hung_Dance", "Moussorgsky"))
        base = os.path.join(ROOT, r["folder"], r["idx"])
        rows.append((("A " if orig else "B ") + r["solo"][:34], measure(os.path.join(base, r["solo"]), os.path.join(base, r["orch"]))))
    rows.sort(key=lambda x: x[0])
    for lab, o in (("НАШ A как сейчас", "ab1/A_как_сейчас.mid"), ("НАШ B фактура", "ab1/B_фактура.mid")):
        rows.append((lab, measure(S + "chopin_orig.mid", S + o)))
    print("%-36s %4s %3s %6s %6s %6s %6s %6s %6s %6s %6s" % ("пьеса", "такт", "дор", "корот", "букв", "поток", "кусок", "<1такт", "вступ", "звучит", "дыры"))
    for lab, d in rows:
        print("%-36s %4d %3d %6.2f %6.2f %6.2f %6.1f %6.2f %6.1f %6.2f %6.2f" % (lab, d["bars"], d["tracks"], d["short_share"], d["lit"], d["stream_same"], d["seg_med"], d["seg_short"], d["entries_per_track_100bars"], d["sounding"], d["holes"]))
    for g in "AB":
        sel = [d for lab, d in rows if lab.startswith(g + " ")]
        print("медиана группы", g, {k: st.median([d[k] for d in sel]) for k in ("lit", "stream_same", "seg_med", "seg_short", "entries_per_track_100bars", "sounding", "holes")})
