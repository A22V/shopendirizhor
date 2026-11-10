import statistics as st, collections, bisect
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

