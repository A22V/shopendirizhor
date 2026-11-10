import json, collections, statistics as st, sys
A = json.load(open("analysis.json"))
seen = set(); B = []
for o in A:
    key = (o["name"], o["nbars"])
    if key in seen: continue
    seen.add(key); B.append(o)
def group(o):
    if o["folder"] == "bouliane":
        n = o["name"]
        orig = any(x in n for x in ("OrchBouliane", "OrcBouliane", "OrchCaplet", "Ravel", "Hung_Dance", "Moussorgsky"))
        return "A рояль→оркестр (мастер)" if orig else "B оркестр→рояль (Bouliane)"
    return "C камерные (≤6 дорожек)" if o["tracks"] <= 6 else "D прочие оркестровые"
G = collections.defaultdict(list)
for o in B: G[group(o)].append(o)
for g in sorted(G):
    print("\n=====", g, "пар:", len(G[g]), "тактов:", sum(o["nbars"] for o in G[g]))
    if g.startswith("A"): print("  ", "; ".join(o["name"][:28] for o in G[g]))
    T = collections.defaultdict(list)
    for o in G[g]:
        for b in o["bars"]:
            if b["type"] != "пусто" and b["n_inst"] > 0: T[b["type"]].append((o, b))
    for t, lst in sorted(T.items(), key=lambda x: -len(x[1])):
        pieces = len({id(o) for o, b in lst})
        tr = collections.Counter(); roles = collections.Counter(); fam_role = collections.defaultdict(collections.Counter); litfam = collections.Counter()
        frac_inst = []
        for o, b in lst:
            tr.update(b["treat"]); litfam.update(b["lit_short_fam"])
            for k, (fam, role, snd, ns) in b["roles"].items():
                roles[role] += 1; fam_role[fam][role] += 1
            frac_inst.append(b["n_inst"] / o["tracks"])
        s = tr["lits"] + tr["helds"] + tr["drops"]; l = tr["litl"] + tr["heldl"] + tr["dropl"]
        R = sum(roles.values())
        print("\n-- %s: тактов %d, пьес %d; играет %.0f%% дорожек (медиана)" % (t, len(lst), pieces, 100 * st.median(frac_inst)))
        if s: print("   короткие ноты рояля (%d): сыграны буквально %.0f%%, растворены в тянущейся ноте %.0f%%, пропущены %.0f%%" % (s, 100*tr["lits"]/s, 100*tr["helds"]/s, 100*tr["drops"]/s))
        if l: print("   длинные ноты рояля (%d): буквально %.0f%%, в тянущейся %.0f%%, пропущены %.0f%%" % (l, 100*tr["litl"]/l, 100*tr["heldl"]/l, 100*tr["dropl"]/l))
        print("   роли инструментов в такте: держит %.0f%%, средне %.0f%%, быстро %.0f%%" % (100*roles["держит"]/R, 100*roles["средне"]/R, 100*roles["быстро"]/R))
        if t in ("арпеджио", "гаммы/линия", "быстрое смешанное"):
            for fam, c in sorted(fam_role.items(), key=lambda x: -sum(x[1].values())):
                n = sum(c.values())
                if n >= 8: print("      %-11s тактов-участий %4d: держит %3.0f%% средне %3.0f%% быстро %3.0f%%" % (fam, n, 100*c["держит"]/n, 100*c["средне"]/n, 100*c["быстро"]/n))
