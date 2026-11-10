import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2")
import sys, json, collections
from common import *
rows = []
for folder, idx, solo, orch in pairs():
    if not solo: print("нет пары", folder, idx); continue
    try:
        P, bpb, pend, pped, pts = load(solo); O, obpb, oend, _, ots = load(orch)
    except Exception as e:
        print("не читается", folder, idx, repr(e)[:80]); continue
    pn = sorted(n for v in P.values() for n in v)
    mp = mapping(orch)
    fams = collections.Counter(FAM.get(mp.get(k, "?"), mp.get(k, "?")) for k in O)
    # alignment: share of piano onsets whose pitch class starts/sounds in orchestra within 0.25 beat
    on = sorted((s, e, p) for v in O.values() for s, e, p, _ in v)
    starts = [x[0] for x in on]
    hit = 0
    for s, e, p, _ in pn:
        j = bisect.bisect_right(starts, s + 0.25)
        i = bisect.bisect_left(starts, s - 8)
        if any(q % 12 == p % 12 and e2 > s - 0.25 and s2 <= s + 0.25 for s2, e2, q in on[i:j]): hit += 1
    rows.append(dict(folder=folder, idx=idx, solo=os.path.basename(solo), orch=os.path.basename(orch), pn=len(pn), on=len(on),
                     pbeats=round(pend, 1), obeats=round(oend, 1), bpb=bpb, obpb=obpb, align=round(hit / max(1, len(pn)), 3),
                     ped=pped, tracks=len(O), fams=dict(fams), nts=len(pts), unmapped=[k for k in O if k not in mp][:3]))
json.dump(rows, open("inventory.json", "w"), ensure_ascii=False, indent=0)
for r in rows:
    print("%-9s %3s pn%5d on%6d beats %6.0f/%6.0f bpb %.1f/%.1f align %.2f ped%d tr%2d %s" % (r["folder"][:9], r["idx"], r["pn"], r["on"], r["pbeats"], r["obeats"], r["bpb"], r["obpb"], r["align"], r["ped"], r["tracks"], r["solo"][:45]))
