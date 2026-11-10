import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2")
import json, statistics as st, bisect, os, collections
from common import *
TOL = 0.13
def cover(solo, orch):
    P, bpb, pend, _, _ = load(solo); O, _, oend, _, _ = load(orch)
    pn = sorted(n for v in P.values() for n in v); ps = [x[0] for x in pn]
    on = sorted((s, e, p, k) for k, v in O.items() for s, e, p, _ in v); os_ = [x[0] for x in on]
    hit = hs = ns = 0
    for n in pn:
        lo, hi = bisect.bisect_left(os_, n[0] - TOL), bisect.bisect_right(os_, n[0] + TOL)
        h = any(q % 12 == n[2] % 12 for s2, e2, q, k in on[lo:hi]); hit += h
        if n[1] - n[0] < 0.5: ns += 1; hs += h
    # moments: piano onset moments vs orchestra onset moments (rhythm kept?)
    pm = sorted({round(x * 8) for x in ps}); om = {round(x * 8) for x in os_}
    rhythm = sum(1 for m in pm if m in om or m - 1 in om or m + 1 in om) / len(pm)
    # orchestra onsets that have no piano onset of that pitch class (re-struck or invented)
    extra = 0
    for s, e, p, k in on:
        lo, hi = bisect.bisect_left(ps, s - TOL), bisect.bisect_right(ps, s + TOL)
        if not any(n[2] % 12 == p % 12 for n in pn[lo:hi]): extra += 1
    return dict(all=hit / len(pn), short=(hs / ns if ns else None), nshort=ns / len(pn), rhythm=rhythm, extra=extra / len(on), ratio=len(on) / len(pn), tracks=len(P))
S = "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/"
inv = json.load(open("inventory.json")); G = collections.defaultdict(list)
for r in inv:
    if r["folder"] != "bouliane" or r["pn"] < 80: continue
    orig = any(x in r["solo"] for x in ("OrchBouliane", "OrcBouliane", "OrchCaplet", "Ravel", "Hung_Dance", "Moussorgsky"))
    base = os.path.join(ROOT, r["folder"], r["idx"])
    G["A" if orig else "B"].append(cover(os.path.join(base, r["solo"]), os.path.join(base, r["orch"])))
f = lambda x: "  —" if x is None else "%3.0f%%" % (100 * x)
print("%-28s %6s %6s %6s %6s %7s" % ("", "все", "корот", "ритм", "нов.", "нот×"))
for g, name in (("A", "мастера: рояль→оркестр (11)"), ("B", "Bouliane: оркестр→рояль")):
    for q, lab in ((0, "мин"), (1, "медиана"), (2, "макс")):
        vals = {k: sorted(d[k] for d in G[g] if d[k] is not None) for k in ("all", "short", "rhythm", "extra", "ratio")}
        pick = lambda v: v[0] if q == 0 else (st.median(v) if q == 1 else v[-1])
        print("%-28s %6s %6s %6s %6s %7.1f" % ((name if q == 1 else "") + " " + lab, f(pick(vals["all"])), f(pick(vals["short"])), f(pick(vals["rhythm"])), f(pick(vals["extra"])), pick(vals["ratio"])))
for p, solo in (("Nocturne_Aminor", None), ("Waltz_Dmajor", None), ("Prelude_Eminor", None), ("Piece53", None), ("Rybnikov", None), ("K545", None), ("Chopin", S + "chopin_orig.mid")):
    solo = solo or "/home/claude/shopendirizhor/tests/pieces/%s_piano.mid" % p
    d = cover(solo, S + "lop2/ours/%s.mid" % p)
    print("%-28s %6s %6s %6s %6s %7.1f   дорожек рояля %d, коротких нот %s" % ("НАШ " + p, f(d["all"]), f(d["short"]), f(d["rhythm"]), f(d["extra"]), d["ratio"], d["tracks"], f(d["nshort"])))
