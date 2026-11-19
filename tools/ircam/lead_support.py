"""Кто что делает под мелодией: по базе IRCAM (выровненные пары рояль <-> оркестр) и по нашим оркестровкам.
Для каждого такта: «ведущий» = семейство, которое играет больше всего долгих нот верхнего голоса рояля;
остальные семейства (кроме тех, кто играет почти столько же, то есть удваивает мелодию) — сопровождение:
есть ли в такте (присутствие) и что делает (бежит / держит / тянет / прочее), играет ли самый низкий звук оркестра (бас).
Все пороги — рабочие (эвристика для группировки), не законы. Запуск: python lead_support.py (пути: ROOT в common.py)."""
import sys, os, json, bisect, collections, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load, mapping, FAM, ROOT
from analyze_lib import skyline

TOL = 0.13
CO = 0.5            # семейство, у которого ≥ 50% нот ведущего, считается удвоением мелодии, а не сопровождением
ORDER = ["флейта", "гобой", "кларнет", "фагот", "валторна", "медь", "скрипки", "альт", "виолончель", "контрабас", "арфа"]


def bars_of(P, O, fam, bpb, nb):
    """-> список словарей по тактам: lead, co (удвоители), roles {семейство: роль}, bass {семейства}"""
    pn = sorted(n for v in P.values() for n in v)
    mel = [n for n in skyline(pn) if n[1] - n[0] >= 0.5]
    on = sorted((s, e, p, fam[k]) for k, v in O.items() for s, e, p, _ in v)
    starts = [x[0] for x in on]
    out = []
    for b in range(nb):
        t0, t1 = b * bpb, (b + 1) * bpb
        lit = collections.Counter()
        for s, e, p, v in mel:
            if not (t0 - 1e-6 <= s < t1 - 1e-6):
                continue
            lo, hi = bisect.bisect_left(starts, s - TOL), bisect.bisect_right(starts, s + TOL)
            for f in {x[3] for x in on[lo:hi] if x[2] % 12 == p % 12}:
                lit[f] += 1
        if not lit:
            out.append(None); continue
        top, cnt = lit.most_common(1)[0]
        co = {f for f, c in lit.items() if f != top and c >= CO * cnt}
        # ноты оркестра в такте
        by = collections.defaultdict(list)       # семейство -> [(s,e,p)] звучащие в такте
        lowest = None
        for s, e, p, f in on:
            if e > t0 + 1e-6 and s < t1 - 1e-6:
                by[f].append((s, e, p))
        if not by:
            out.append(None); continue
        low = min(p for v in by.values() for s, e, p in v)
        roles, bass = {}, set()
        for f, v in by.items():
            st_ = [x for x in v if t0 - 1e-6 <= x[0] < t1 - 1e-6]
            if not st_:
                roles[f] = "тянет"
            else:
                short = sum(1 for x in st_ if x[1] - x[0] < 0.5) / len(st_)
                med = st.median(x[1] - x[0] for x in st_)
                roles[f] = "бежит" if (short >= 0.6 and len(st_) >= 3) else ("держит" if med >= 1.0 else "прочее")
            if min(p for s, e, p in v) <= low + 3:
                bass.add(f)
        out.append(dict(lead=top, co=co, roles=roles, bass=bass, nfam=len(by)))
    return out


def tally(allbars, title, minbars=40):
    """allbars: список (lead, co, roles, bass) -> печать таблиц по ведущему"""
    byl = collections.defaultdict(list)
    for r in allbars:
        byl[r["lead"]].append(r)
    print("\n=== %s: тактов с понятным ведущим %d ===" % (title, len(allbars)))
    res = {}
    for lead in sorted(byl, key=lambda k: -len(byl[k])):
        rs = byl[lead]
        if len(rs) < minbars:
            continue
        print("\nведущий = %s (тактов %d); семейств в такте в среднем %.1f" % (lead, len(rs), st.mean(r["nfam"] for r in rs)))
        row = {}
        for f in ORDER:
            if f == lead:
                continue
            pres = [r for r in rs if f in r["roles"] and f not in r["co"]]
            co = sum(1 for r in rs if f in r["co"])
            if not pres and not co:
                row[f] = (0, 0, {}, 0); continue
            c = collections.Counter(r["roles"][f] for r in pres)
            nb = sum(1 for r in pres if f in r["bass"])
            row[f] = (len(pres) / len(rs), co / len(rs), {k: v / max(1, len(pres)) for k, v in c.items()}, nb / len(rs))
            print("   %-11s играет %3.0f%% тактов, удваивает мелодию ещё %2.0f%%; роль: %s; бас %2.0f%%" % (
                f, 100 * row[f][0], 100 * row[f][1],
                ", ".join("%s %.0f%%" % (k, 100 * v) for k, v in sorted(row[f][2].items(), key=lambda x: -x[1])), 100 * row[f][3]))
        res[lead] = (len(rs), row)
    return res


def masters():
    inv = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory.json")))
    rows, npairs = [], 0
    for r in inv:
        ok = r["align"] >= 0.95 and abs(r["pbeats"] - r["obeats"]) <= max(4, 0.03 * r["pbeats"]) and r["bpb"] == r["obpb"]
        if not ok:
            continue
        base = os.path.join(ROOT, r["folder"], r["idx"])
        P, bpb, pend, _, _ = load(os.path.join(base, r["solo"]))
        O, _, oend, _, _ = load(os.path.join(base, r["orch"]))
        mp = mapping(os.path.join(base, r["orch"]))
        fam = {k: FAM.get(mp.get(k, k), mp.get(k, k)) for k in O}
        nb = int(max(pend, oend) / bpb + 0.999)
        bs = [b for b in bars_of(P, O, fam, bpb, nb) if b]
        rows += bs; npairs += 1
    return rows, npairs


NAMES = {"Flute": "флейта", "Oboe": "гобой", "Clarinet": "кларнет", "Bassoon": "фагот", "Horn": "валторна",
         "Violin": "скрипки", "Violin'": "скрипки", "Violin I": "скрипки", "Violin II": "скрипки", "Viola": "альт",
         "Violoncello": "виолончель", "Contrabass": "контрабас", "Percussion": "ударные"}


def ours(piano, orch):
    P, bpb, pend, _, _ = load(piano)
    O, _, oend, _, _ = load(orch)
    O = {k: v for k, v in O.items() if k in NAMES and k != "Percussion"}
    P = {k: v for k, v in P.items()}
    fam = {k: NAMES[k] for k in O}
    nb = int(max(pend, oend) / bpb + 0.999)
    return [b for b in bars_of(P, O, fam, bpb, nb) if b]


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "masters"
    if mode == "masters":
        rows, n = masters()
        print("пар %d" % n)
        json.dump([dict(r, co=sorted(r["co"]), bass=sorted(r["bass"])) for r in rows], open("lead_support_masters.json", "w"), ensure_ascii=False)
        tally(rows, "мастера (IRCAM)")
    else:
        rows = ours(sys.argv[2], sys.argv[3])
        tally(rows, "наша оркестровка " + os.path.basename(sys.argv[3]), minbars=5)
