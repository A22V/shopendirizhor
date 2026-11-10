import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2")
import json, collections, bisect, os, statistics as st
from common import *
TOL = 0.13
inv = json.load(open("inventory.json"))
pair_cnt = collections.Counter(); solo_cnt = collections.Counter(); oct_cnt = collections.defaultdict(collections.Counter)
role_dbl = collections.defaultdict(lambda: collections.Counter())
for r in inv:
    if r["folder"] != "bouliane" or r["align"] < 0.95: continue
    base = os.path.join(ROOT, r["folder"], r["idx"])
    P, bpb, pend, _, _ = load(os.path.join(base, r["solo"])); O, _, oend, _, _ = load(os.path.join(base, r["orch"]))
    mp = mapping(os.path.join(base, r["orch"]))
    fam = {k: FAM.get(mp.get(k, k), mp.get(k, k)) for k in O}
    pn = sorted(n for v in P.values() for n in v)
    # melody of piano = skyline
    top = {}
    for s, e, p, v in pn:
        if s not in top or p > top[s][0]: top[s] = (p, e)
    on = sorted((s, e, p, fam[k]) for k, v in O.items() for s, e, p, _ in v); os_ = [x[0] for x in on]
    for s, (p, e) in top.items():
        if e - s < 0.5: continue
        lo, hi = bisect.bisect_left(os_, s - TOL), bisect.bisect_right(os_, s + TOL)
        who = [(f, q - p) for s2, e2, q, f in on[lo:hi] if q % 12 == p % 12]
        fams = sorted({f for f, d in who})
        if not who: continue
        solo_cnt[len(fams)] += 1
        for f, d in who: oct_cnt[f][d // 12 * 12 if d % 12 == 0 else d] += 1
        for a in fams:
            for b in fams:
                if a < b: pair_cnt[(a, b)] += 1
print("сколько семейств играют долгую ноту мелодии рояля одновременно:", dict(sorted(solo_cnt.items())))
tot = sum(solo_cnt.values()); print("  доля нот мелодии, где семейств >= 2: %.0f%%" % (100 * sum(v for k, v in solo_cnt.items() if k >= 2) / tot))
print("частые пары семейств на мелодии:", pair_cnt.most_common(12))
print("октава относительно рояля по семействам (0 = унисон, 12 = октавой выше):")
for f, c in sorted(oct_cnt.items(), key=lambda x: -sum(x[1].values())):
    n = sum(c.values()); print("  %-11s %5d: " % (f, n) + ", ".join("%+d %.0f%%" % (k, 100 * v / n) for k, v in c.most_common(4)))
