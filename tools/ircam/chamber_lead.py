"""Камерные пары базы IRCAM: кто из инструментов ведёт мелодию рояля и как часто она переходит от одного к другому.
Запуск: python tools/ircam/chamber_lead.py   (база вне репозитория, путь в common.ROOT)
Мелодия рояля = самая высокая нота, начинающаяся в данный момент, если она не ниже уже звучащих (упрощение).
Для каждой такой ноты ищется дорожка ансамбля, которая в тот же момент (±1/4 доли) начинает ту же ноту
(сначала на той же высоте, иначе в другой октаве)."""
import collections, statistics as st
from common import load, mapping, pairs


def main():
    rows = []
    for folder, d, solo, orch in pairs():
        if not solo: continue
        try:
            o, bpb, end, _, _ = load(orch); p, _, pend, _, _ = load(solo)
        except Exception:
            continue
        mp = mapping(orch)
        tracks = [(str(mp.get(k, k)).strip().lower(), v) for k, v in o.items()]
        if not (2 <= len(tracks) <= 5) or end < 16: continue
        if any(("voice" in n or "unknown" in n or "organ" in n or "continuo" in n) for n, _ in tracks): continue
        pn = sorted(n for v in p.values() for n in v)
        on = collections.defaultdict(set)
        for n, v in tracks:
            for s, e, pit, _ in v: on[round(s * 4)].add(pit % 12)
        hit = sum(1 for s, e, pit, _ in pn if any(pit % 12 in on.get(round(s * 4) + k, ()) for k in (-1, 0, 1)))
        if hit / max(1, len(pn)) < 0.9: continue
        idx = []
        for i, (n, v) in enumerate(tracks):
            m = collections.defaultdict(list)
            for s, e, pit, _ in v: m[round(s * 4)].append(pit)
            idx.append(m)
        by = collections.defaultdict(list)
        for s, e, pit, _ in pn: by[round(s * 4)].append((pit, e))
        mel, live = [], []
        for q in sorted(by):
            t = q / 4.0
            live = [(pp, ee) for pp, ee in live if ee > t + 1e-6]
            top = max(by[q])[0]
            if not live or top >= max(pp for pp, _ in live): mel.append((q, top))
            live += by[q]
        seq = []          # (доля, номер дорожки, сдвиг в октавах)
        for q, pit in mel:
            found = None
            for i in range(len(tracks)):
                for k in (0, -1, 1):
                    if pit in idx[i].get(q + k, ()): found = (i, 0); break
                if found: break
            if not found:
                for i in range(len(tracks)):
                    for k in (0, -1, 1):
                        c = [x for x in idx[i].get(q + k, ()) if x % 12 == pit % 12]
                        if c: found = (i, round((c[0] - pit) / 12)); break
                    if found: break
            if found: seq.append((q / 4.0, found[0], found[1]))
        if len(seq) < 20: continue
        share = collections.Counter(i for _, i, _ in seq)
        runs, cur, start = [], seq[0][1], seq[0][0]
        for t, i, _ in seq[1:]:
            if i != cur:
                runs.append((cur, (t - start) / bpb)); cur, start = i, t
        runs.append((cur, (seq[-1][0] - start) / bpb))
        long_runs = [r for r in runs if r[1] >= 1.0]          # короче такта — не передача мелодии, а случайность замера
        bars = end / bpb
        rows.append(dict(name="%s/%s" % (folder[:6], d), tracks=[n for n, _ in tracks], bars=bars,
                         share=[share[i] / len(seq) for i in range(len(tracks))],
                         runs=[r[1] for r in long_runs], n_long=len(long_runs),
                         octave=sum(1 for _, i, sh in seq if sh != 0) / len(seq)))
    for r in rows:
        print("%-22s %-40s тактов %4.0f | мелодию ведут (доля нот по дорожкам сверху вниз) %s | кусков от такта: %d, медиана %.1f такта | в другой октаве %.0f%%" % (
            r["name"], "+".join(x[:7] for x in r["tracks"]), r["bars"], " ".join("%.0f" % (100 * x) for x in r["share"]),
            r["n_long"], st.median(r["runs"]) if r["runs"] else 0, 100 * r["octave"]))
    if rows:
        print("\nпар %d; медианы: верхняя дорожка ведёт мелодию %.0f%% нот (25–75%%: %.0f–%.0f); вторая %.0f%%; нижняя %.0f%%; "
              "кусок без смены ведущего (от такта) %.1f такта; ведущий меняется раз в %.1f такта" % (
                  len(rows), 100 * st.median(r["share"][0] for r in rows),
                  100 * st.quantiles([r["share"][0] for r in rows], n=4)[0], 100 * st.quantiles([r["share"][0] for r in rows], n=4)[2],
                  100 * st.median(r["share"][1] for r in rows), 100 * st.median(r["share"][-1] for r in rows),
                  st.median(x for r in rows for x in r["runs"]), st.median(r["bars"] / max(1, r["n_long"]) for r in rows)))


if __name__ == "__main__":
    main()
