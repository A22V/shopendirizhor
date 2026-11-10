import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2")
import json, statistics as st
from common import *
from analyze_lib import texture, skyline
TOL = 0.13
def study(solo, orch, inst=None, label=""):
    P, bpb, pend, _, _ = load(solo); O, _, oend, _, _ = load(orch)
    mp = inst if inst is not None else mapping(orch)
    fam = {k: FAM.get(mp.get(k, k), mp.get(k, k)) for k in O}
    pn = sorted(n for v in P.values() for n in v); pstarts = [x[0] for x in pn]
    nb = int(max(pend, oend) / bpb + 0.999)
    btype = {}
    for b in range(nb):
        pb = pn[bisect.bisect_left(pstarts, b * bpb - 1e-6):bisect.bisect_left(pstarts, (b + 1) * bpb - 1e-6)]
        btype[b] = texture(pb, bpb)[0]
    res = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    fastcount = collections.defaultdict(list); holdcount = collections.defaultdict(list); nin = collections.defaultdict(list); nfam = collections.defaultdict(list)
    perbar = collections.defaultdict(lambda: collections.defaultdict(list))
    for k, v in O.items():
        for s, e, p, _ in v:
            b = int((s + 1e-6) // bpb); t = btype.get(b, "пусто")
            lo, hi = bisect.bisect_left(pstarts, s - TOL), bisect.bisect_right(pstarts, s + TOL)
            m = [n for n in pn[lo:hi] if n[2] % 12 == p % 12]
            d = e - s
            oc = "длинная" if d >= 1.0 else ("короткая" if d < 0.5 else "средняя")
            if m:
                pd = max(n[1] - n[0] for n in m)
                src = "удлинена ×2+" if d >= 2 * pd and d - pd >= 0.4 else ("как у рояля" if d >= 0.6 * pd else "укорочена")
            else:
                i0 = bisect.bisect_left(pstarts, s - 16)
                src = "повтор звучащей" if any(n[2] % 12 == p % 12 and n[1] > s + TOL for n in pn[i0:lo]) else "добавлена"
            res[t][oc][src] += 1
            for bb in range(b, int(max(s, e - 1e-6) // bpb) + 1): perbar[bb][k].append(d)
    for b, d in perbar.items():
        t = btype.get(b, "пусто")
        meds = {k: st.median(v) for k, v in d.items()}
        fastcount[t].append(sum(1 for m in meds.values() if m < 0.5)); holdcount[t].append(sum(1 for m in meds.values() if m >= 1.0))
        nin[t].append(len(meds)); nfam[t].append(len({fam[k] for k in meds}))
    return res, fastcount, holdcount, nin, nfam, len(O)

if __name__ == "__main__":
    A = json.load(open("analysis.json")); seen = set()
    groups = collections.defaultdict(list)
    for o in A:
        key = (o["name"], o["nbars"])
        if key in seen: continue
        seen.add(key)
        if o["folder"] == "bouliane":
            g = "A" if any(x in o["name"] for x in ("OrchBouliane", "OrcBouliane", "OrchCaplet", "Ravel", "Hung_Dance", "Moussorgsky")) else "B"
        else: g = "C" if o["tracks"] <= 6 else "D"
        groups[g].append(o)
    inv = {(r["folder"], r["idx"]): r for r in json.load(open("inventory.json"))}
    for g in "ABD":
        tot = collections.defaultdict(lambda: collections.defaultdict(collections.Counter)); FC = collections.defaultdict(list); HC = collections.defaultdict(list); NI = collections.defaultdict(list); NF = collections.defaultdict(list)
        for o in groups[g]:
            r = inv[(o["folder"], o["idx"])]; base = os.path.join(ROOT, r["folder"], r["idx"])
            res, fc, hc, ni, nf, ntr = study(os.path.join(base, r["solo"]), os.path.join(base, r["orch"]))
            for t in res:
                for oc in res[t]: tot[t][oc].update(res[t][oc])
            for t in fc: FC[t] += fc[t]; HC[t] += hc[t]; NI[t] += ni[t]; NF[t] += nf[t]
        print("\n===== группа", g, "пар", len(groups[g]))
        for t in ("арпеджио", "гаммы/линия", "быстрое смешанное", "аккорды", "умеренное (мелодия+сопровождение)", "редкие ноты"):
            if t not in tot: continue
            print("-- %s (тактов %d): в такте инструментов медиана %s, семейств %s; быстрых %s (25–75%%: %s–%s), держащих %s" % (
                t, len(NI[t]), st.median(NI[t]), st.median(NF[t]), st.median(FC[t]), st.quantiles(FC[t], n=4)[0] if len(FC[t]) > 3 else "?", st.quantiles(FC[t], n=4)[2] if len(FC[t]) > 3 else "?", st.median(HC[t])))
            for oc in ("длинная", "средняя", "короткая"):
                c = tot[t][oc]; n = sum(c.values())
                if n: print("     ноты оркестра %-8s %6d: " % (oc, n) + ", ".join("%s %.0f%%" % (k, 100 * v / n) for k, v in c.most_common()))
