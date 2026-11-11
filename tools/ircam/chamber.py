"""Камерные пары базы IRCAM (2–5 дорожек): как мастера раздают ноты рояля малому составу.
Запуск: python tools/ircam/chamber.py   (база лежит вне репозитория, путь в common.ROOT)
Считает по каждой паре: сколько нот рояля сыграно ансамблем; кто держит верхний и нижний звук;
как часто голоса перекрещиваются; как часто один инструмент берёт две ноты сразу; сколько времени звучит каждый.
"""
import collections, statistics as st
from common import load, mapping, pairs

ORDER = ["flute", "oboe", "clarinet", "horn", "bassoon", "trumpet", "trombone", "bass-trombone", "violin", "viola", "violoncello", "contrabass"]


def norm(x):
    return x.strip().lower()


def main():
    rows = []
    for folder, d, solo, orch in pairs():
        if not solo: continue
        try:
            o, bpb, end, _, _ = load(orch); p, _, pend, _, _ = load(solo)
        except Exception:
            continue
        mp = mapping(orch)
        tracks = [(norm(mp.get(k, k)), v) for k, v in o.items()]
        if not (2 <= len(tracks) <= 5) or end < 16: continue
        if any(("voice" in n or "unknown" in n or "organ" in n or "continuo" in n) for n, _ in tracks): continue
        pn = [n for v in p.values() for n in v]
        on = collections.defaultdict(set)
        for n, v in tracks:
            for s, e, pit, _ in v: on[round(s * 4)].add(pit % 12)
        hit = sum(1 for s, e, pit, _ in pn if any(pit % 12 in on.get(round(s * 4) + k, ()) for k in (-1, 0, 1)))
        # моменты начала нот: кто сверху, кто снизу, перекрещивания, двойные ноты
        moments = sorted({round(s * 4) for _, v in tracks for s, _, _, _ in v})
        top = collections.Counter(); bot = collections.Counter(); cross = 0; multi = collections.Counter(); cnt = 0
        for m in moments:
            t = m / 4.0 + 1e-6
            snd = []
            for i, (n, v) in enumerate(tracks):
                ps = [pit for s, e, pit, _ in v if s <= t < e]
                starts = [pit for s, e, pit, _ in v if round(s * 4) == m]
                if len(starts) >= 2: multi[i] += 1
                if ps: snd.append((i, max(ps), min(ps)))
            if len(snd) < 2: continue
            cnt += 1
            top[max(snd, key=lambda x: x[1])[0]] += 1; bot[min(snd, key=lambda x: x[2])[0]] += 1
            if any(a[1] < b[1] for a, b in zip(snd, snd[1:])): cross += 1      # дорожки идут сверху вниз по партитуре
        act = []
        for n, v in tracks:
            cov = 0.0; last = 0.0
            for s, e, _, _ in sorted(v):
                s2 = max(s, last)
                if e > s2: cov += e - s2; last = e
            act.append(cov / end)
        if not cnt: continue
        rows.append(dict(folder=folder, d=d, names=[n for n, _ in tracks], cover=hit / max(1, len(pn)),
                         top=[top[i] / cnt for i in range(len(tracks))], bot=[bot[i] / cnt for i in range(len(tracks))],
                         cross=cross / cnt, multi=[multi[i] / max(1, len(moments)) for i in range(len(tracks))], act=act,
                         ratio=sum(len(v) for _, v in tracks) / max(1, len(pn))))
    for r in rows:
        print("%s/%s %s | сыграно %.0f%% | нот ансамбля/рояля %.2f | верх %s | низ %s | перекрещ. %.0f%% | две ноты сразу %s | звучит %s" % (
            r["folder"][:6], r["d"], "+".join(x[:6] for x in r["names"]), 100 * r["cover"], r["ratio"],
            " ".join("%.0f" % (100 * x) for x in r["top"]), " ".join("%.0f" % (100 * x) for x in r["bot"]), 100 * r["cross"],
            " ".join("%.0f" % (100 * x) for x in r["multi"]), " ".join("%.0f" % (100 * x) for x in r["act"])))
    good = [r for r in rows if r["cover"] >= 0.9]
    print("\nпар всего %d, выровненных (сыграно ≥90%%) %d" % (len(rows), len(good)))
    if good:
        print("медианы по выровненным: сыграно %.0f%%, нот ансамбля/рояля %.2f, перекрещивания %.0f%%, верхний звук у первой дорожки %.0f%%, нижний у последней %.0f%%, две ноты сразу (макс. по дорожкам) %.0f%%, звучит дорожка %.0f%%" % (
            100 * st.median(r["cover"] for r in good), st.median(r["ratio"] for r in good), 100 * st.median(r["cross"] for r in good),
            100 * st.median(r["top"][0] for r in good), 100 * st.median(r["bot"][-1] for r in good),
            100 * st.median(max(r["multi"]) for r in good), 100 * st.median(x for r in good for x in r["act"])))


if __name__ == "__main__":
    main()
