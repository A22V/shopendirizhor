import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2")
import json, statistics as st, heapq
from common import *
inv = json.load(open("inventory.json"))
TOL = 0.13

def texture(notes, bpb):
    """тип фактуры рояля в такте по нотам, начавшимся в такте. Все пороги — мои рабочие (эвристика для группировки)."""
    if not notes: return "пусто", {}
    ons = sorted({round(n[0] * 12) for n in notes})
    per_on = len(notes) / len(ons)
    short = sum(1 for n in notes if n[1] - n[0] < 0.5) / len(notes)
    dens = len(ons) / bpb                       # моментов начала на долю
    seq = sorted(notes)
    leaps = [abs(b[2] - a[2]) for a, b in zip(seq, seq[1:]) if b[0] > a[0] + 1e-6]
    leap = st.median(leaps) if leaps else 0
    f = dict(per_on=per_on, short=short, dens=dens, leap=leap)
    if dens < 1.0: t = "редкие ноты"
    elif per_on >= 2.5: t = "аккорды"
    elif dens >= 2.0 and per_on < 1.5: t = "арпеджио" if leap >= 3 else "гаммы/линия"
    elif dens >= 2.0: t = "быстрое смешанное"
    else: t = "умеренное (мелодия+сопровождение)"
    return t, f

def skyline(pn):
    """верхний голос: нота — мелодия, если в момент начала над ней ничего не звучит (и не начинается)."""
    res = []; active = []  # heap of (-pitch, end)
    i = 0; pn = sorted(pn)
    while i < len(pn):
        j = i
        while j < len(pn) and pn[j][0] - pn[i][0] < 1e-6: j += 1
        s = pn[i][0]
        active = [(p, e) for p, e in active if e > s + 1e-6]
        top = max(pn[i:j], key=lambda n: n[2])
        if not any(p > top[2] for p, e in active): res.append(top)
        active += [(n[2], n[1]) for n in pn[i:j]]
        i = j
    return res

out = []
for r in inv:
    ok = r["align"] >= 0.95 and abs(r["pbeats"] - r["obeats"]) <= max(4, 0.03 * r["pbeats"]) and r["bpb"] == r["obpb"]
    if not ok: continue
    base = os.path.join(ROOT, r["folder"], r["idx"])
    P, bpb, pend, _, _ = load(os.path.join(base, r["solo"])); O, _, oend, _, _ = load(os.path.join(base, r["orch"]))
    mp = mapping(os.path.join(base, r["orch"]))
    inst = {k: mp.get(k, k) for k in O}
    pn = sorted(n for v in P.values() for n in v)
    on = sorted((s, e, p, k) for k, v in O.items() for s, e, p, _ in v)
    ostarts = [x[0] for x in on]
    pstarts = [x[0] for x in pn]
    nb = int(max(pend, oend) / bpb + 0.999)
    # --- per piano note treatment
    def treat(n):
        s, e, p = n[0], n[1], n[2]
        lo, hi = bisect.bisect_left(ostarts, s - TOL), bisect.bisect_right(ostarts, s + TOL)
        lit = [(k, e2 - s2, q - p) for s2, e2, q, k in on[lo:hi] if q % 12 == p % 12]
        if lit: return "lit", lit
        i0 = bisect.bisect_left(ostarts, s - 16)
        if any(q % 12 == p % 12 and e2 > s + TOL for s2, e2, q, k in on[i0:lo]): return "held", []
        return "drop", []
    mel = skyline(pn); melset = {(n[0], n[2]) for n in mel}
    bars = []
    for b in range(nb):
        t0, t1 = b * bpb, (b + 1) * bpb
        pb = pn[bisect.bisect_left(pstarts, t0 - 1e-6):bisect.bisect_left(pstarts, t1 - 1e-6)]
        typ, f = texture(pb, bpb)
        rec = dict(bar=b + 1, type=typ, pn=len(pb), **{k: round(v, 2) for k, v in f.items()})
        tr = collections.Counter(); lit_short = collections.Counter(); ratios = []
        for n in pb:
            kind, lit = treat(n)
            sh = "s" if n[1] - n[0] < 0.5 else "l"
            tr[kind + sh] += 1
            if kind == "lit":
                for k, d, sft in lit:
                    if sh == "s": lit_short[FAM.get(inst[k], inst[k])] += 1
                    ratios.append((FAM.get(inst[k], inst[k]), sh, d / (n[1] - n[0])))
        rec["treat"] = dict(tr); rec["lit_short_fam"] = dict(lit_short)
        # orchestra instruments in bar
        ins = collections.defaultdict(list)
        for s, e, p, k in on[bisect.bisect_left(ostarts, t0 - 64):bisect.bisect_left(ostarts, t1 - 1e-6)]:
            if e > t0 + 1e-6: ins[k].append((s, e, p))
        roles = {}
        for k, v in ins.items():
            sounding = sum(min(e, t1) - max(s, t0) for s, e, p in v)
            started = [x for x in v if x[0] >= t0 - 1e-6]
            med = st.median([e - s for s, e, p in v])
            role = "держит" if med >= 1.0 else ("быстро" if med < 0.5 else "средне")
            roles[k] = (FAM.get(inst[k], inst[k]), role, round(sounding / bpb, 2), len(started))
        rec["roles"] = roles
        rec["n_inst"] = len(roles); rec["n_fam"] = len({v[0] for v in roles.values()})
        bars.append(rec)
    # melody carriers
    carriers = []
    for n in mel:
        lo, hi = bisect.bisect_left(ostarts, n[0] - TOL), bisect.bisect_right(ostarts, n[0] + TOL)
        who = {k for s2, e2, q, k in on[lo:hi] if q % 12 == n[2] % 12}
        carriers.append((n[0], sorted(who)))
    hops = 0; prev = None; found = 0; ndbl = []
    for s, who in carriers:
        if not who: continue
        found += 1; ndbl.append(len(who))
        if prev is not None and not (set(who) & prev): hops += 1
        prev = set(who)
    out.append(dict(folder=r["folder"], idx=r["idx"], name=r["solo"][:60], bpb=bpb, nbars=nb, tracks=r["tracks"],
                    inst=inst, bars=bars, mel_n=len(mel), mel_found=found, hops=hops, mel_dbl=(st.median(ndbl) if ndbl else 0)))
json.dump(out, open("analysis.json", "w"), ensure_ascii=False)
print("проанализировано пар:", len(out), "тактов:", sum(len(o["bars"]) for o in out))
print(collections.Counter(o["folder"] for o in out))
