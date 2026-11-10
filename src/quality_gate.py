"""
Контроль брака оркестровки (2026-11-07). Сравнивает оркестровку с фортепианным оригиналом и ловит
ОБЪЕКТИВНЫЕ ошибки, которые видны без слуха. Ничего не исправляет и не меняет звук.

Проверки (у каждой статус: что измерено, что эвристика):
  Б1 «Фальшь»: нота оркестра, которой нет у фортепиано в пределах той же доли (с учётом педали).
     Измерение. Порог брака (больше 2% нот или больше 5% у одного инструмента) — эвристика.
     Нашла ошибку 2026-11-07: скрипка I на полтона выше гармонии (172 из 292 нот).
  Б2 «Мелодия потеряна»: доля нот мелодии фортепиано, которые кто-то в оркестре играет в то же время
     (та же нота с точностью до октавы). Измерение. Порог брака (меньше 85%) — эвристика.
  Б3 «Мелодия скачет»: сколько раз мелодия переходит к другому инструменту (у двух соседних нот мелодии
     нет общего исполнителя). Измерение. Порог брака (чаще раза в 4 такта в среднем) — эвристика:
     пользователь 2026-11-07 назвал пересадки каждые 2 такта «трешем»; в прочитанных книгах предписания
     менять тембр так часто не найдено.
  Б4 «Молчащий инструмент»: инструмент состава без единой ноты. Измерение; брак — по решению пользователя
     («ожидаются все инструменты», 2026-11-06).
  Б5 «Длительность»: оркестровка короче или длиннее оригинала больше чем на 3% (порог — эвристика).
  П3 (предупреждение, 2026-11-10) «Параллельные квинты, которых нет у фортепиано»: два инструмента идут квинтами
     в одну сторону, а в нотах рояля в эти моменты нет обоих звуков. Запрет параллельных квинт — Римский-Корсаков,
     «Практический учебник гармонии», §13; квинты композитора не считаются (их оркестровка лишь повторяет).
  П1 (предупреждение) «Мелодию перекрывают сверху»: доля нот мелодии, над которыми звучит инструмент,
     не играющий мелодию. Эвристика (смысл: мелодия должна быть слышна, Римский-Корсаков гл. II, правило G02
     проекта); порог 25% — эвристика.
Запуск: python src/quality_gate.py фортепиано.mid оркестровка.mid
"""
import os, sys, bisect, collections

import mido

FOREIGN_MAX = 0.02        # эвристика
FOREIGN_INSTR_MAX = 0.05  # эвристика
MELODY_MIN = 0.85         # эвристика
HOP_BARS = 4.0            # эвристика: в среднем не чаще одной пересадки на 4 такта
LEN_TOL = 0.03            # эвристика
COVER_MAX = 0.25          # эвристика (только предупреждение)
TOL = 0.13                # допуск по времени, доли (квантование music21 ~1/12 доли)

RU = {"Flute": "Флейта", "Oboe": "Гобой", "Clarinet": "Кларнет", "Bassoon": "Фагот", "Horn": "Валторна",
      "Violin I": "Скрипка I", "Violin II": "Скрипка II", "Viola": "Альт", "Violoncello": "Виолончель",
      "Cello": "Виолончель", "Contrabass": "Контрабас", "Double Bass": "Контрабас", "Piano": "Фортепиано",
      "Organ": "Орган", "Accordion": "Аккордеон", "Guitar": "Гитара"}


def _notes(path):
    """[(начало, конец, нота, инструмент)] в долях; имена дорожек; длительность в секундах; педаль; доли в такте."""
    m = mido.MidiFile(path)
    tpb = m.ticks_per_beat
    out, names, pedal, bpb, violins = [], [], [], 4.0, 0
    for k, tr in enumerate(m.tracks):
        name = (tr.name or "").strip()
        if name == "Violin":                       # music21 пишет обе скрипки как "Violin"
            violins += 1
            name = "Violin I" if violins == 1 else "Violin II"
        t, on, has = 0, {}, False
        for x in tr:
            t += x.time
            if x.type == "time_signature" and t == 0:
                bpb = x.numerator * 4.0 / x.denominator
            if x.type == "control_change" and x.control == 64:
                pedal.append((t / tpb, x.value >= 64))
            if x.type in ("note_on", "note_off") and x.channel == 9:
                continue                              # ударные (10-й канал GM) — не ноты гармонии
            if x.type == "note_on" and x.velocity > 0:
                on.setdefault((x.channel, x.note), []).append(t)
            elif x.type in ("note_on", "note_off") and on.get((x.channel, x.note)):
                s = on[(x.channel, x.note)].pop(0)
                out.append((s / tpb, t / tpb, x.note, name or str(k)))
                has = True
        if name in RU and name not in names:          # дорожки состава, даже пустые (для Б4)
            names.append(name)
    return out, names, m.length, sorted(pedal), bpb


def _with_pedal(notes, pedal):
    if not pedal:
        return notes
    times = [p[0] for p in pedal]

    def release(e):
        i = bisect.bisect_right(times, e) - 1
        if i < 0 or not pedal[i][1]:
            return e
        for t, down in pedal[i + 1:]:
            if not down:
                return t
        return e
    return [(s, max(e, release(e)), p, n) for s, e, p, n in notes]


def _bars(times, bpb):
    """'1–4, 7' из списка моментов (в долях)."""
    bars = sorted({int(t // bpb) + 1 for t in times})
    out, i = [], 0
    while i < len(bars):
        j = i
        while j + 1 < len(bars) and bars[j + 1] == bars[j] + 1:
            j += 1
        out.append(str(bars[i]) if i == j else "%d–%d" % (bars[i], bars[j]))
        i = j + 1
    return ", ".join(out[:12]) + (" …" if len(out) > 12 else "")


def melody_of(piano_path):
    """Мелодия так, как её видит оркестратор (те же переключатели окружения)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import orchestrator
    _, _, mel, _ = orchestrator.analyze(piano_path)
    return [(m["offset"], m["offset"] + m["dur"], m["pitch"]) for m in mel]


def _new_fifths(O, p_on, p_starts):
    """Параллельные квинты между двумя инструментами (оба меняют ноту в одни и те же моменты, квинта до и после,
    движение в одну сторону), если у фортепиано в эти моменты нет обоих звуков (иначе это квинта композитора)."""
    by = collections.defaultdict(dict)
    for s, e, p, n in O:
        k = round(s, 3)
        by[n][k] = max(p, by[n].get(k, -1))
    def piano_pcs(t):
        i = bisect.bisect_left(p_starts, t + TOL)
        return {q % 12 for (s2, e2, q, _) in p_on[:i] if e2 > t - TOL}
    names = sorted(by)
    found, total = [], 0
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = by[names[a]], by[names[b]]
            common = sorted(set(A) & set(B))
            for t0, t1 in zip(common, common[1:]):
                a0, b0, a1, b1 = A[t0], B[t0], A[t1], B[t1]
                if a0 == a1 or abs(a0 - b0) % 12 != 7 or abs(a1 - b1) % 12 != 7 or (a1 - a0) * (b1 - b0) <= 0:
                    continue
                total += 1
                if not ({a0 % 12, b0 % 12} <= piano_pcs(t0) and {a1 % 12, b1 % 12} <= piano_pcs(t1)):
                    found.append((t1, names[a], names[b]))
    return found, total


def check(piano_path, orch_path, melody=None, solo=False):
    """Возвращает {"ok": bool, "defects": [(код, текст, статус)], "warnings": [...], "stats": {...}}."""
    P, _, p_len, pedal, bpb = _notes(piano_path)
    P = _with_pedal(P, pedal)
    O, names, o_len, _, obpb = _notes(orch_path)
    bpb = obpb or bpb
    if melody is None:
        melody = melody_of(piano_path)
    defects, warnings, stats = [], [], {}
    p_on = sorted(P)
    p_starts = [x[0] for x in p_on]

    # Б1 фальшь
    tot, bad, where = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    for s, e, p, n in O:
        tot[n] += 1
        i = bisect.bisect_left(p_starts, s + 1.0)
        pcs = {q % 12 for (s2, e2, q, _) in p_on[:i] if e2 > s}
        if pcs and p % 12 not in pcs:
            bad[n] += 1
            where[n].append(s)
    nb, nt = sum(bad.values()), max(sum(tot.values()), 1)
    stats["foreign"] = {"bad": nb, "total": nt, "by_instrument": dict(bad)}
    worst = [n for n in bad if bad[n] / tot[n] > FOREIGN_INSTR_MAX]
    if nb / nt > FOREIGN_MAX or worst:
        detail = "; ".join("%s %d из %d (такты %s)" % (RU.get(n, n), bad[n], tot[n], _bars(where[n], bpb))
                           for n in sorted(bad, key=lambda n: -bad[n])[:4])
        defects.append(("Б1", "Фальшь: %d из %d нот оркестра не совпадают с тем, что в этой доле играет фортепиано. %s."
                        % (nb, nt, detail), "измерение; порог 2% (5% у инструмента) — эвристика"))

    # Б2 мелодия и Б3 пересадки, П1 перекрытие сверху
    o_sorted = sorted(O)
    o_starts = [x[0] for x in o_sorted]
    carriers, found, covered = [], 0, []
    for s, e, p in melody:
        lo, hi = bisect.bisect_left(o_starts, s - TOL), bisect.bisect_right(o_starts, s + TOL)
        who = {n for (s2, e2, q, n) in o_sorted[lo:hi] if q % 12 == p % 12}
        carriers.append((s, who))
        if who:
            found += 1
            top = max(q for (s2, e2, q, n) in o_sorted[lo:hi] if n in who and q % 12 == p % 12)
            j = bisect.bisect_right(o_starts, s + TOL)
            if any(q > top and n not in who and e2 > s + TOL for (s2, e2, q, n) in o_sorted[:j]):
                covered.append(s)
    share = found / max(len(melody), 1)
    stats["melody_found"] = round(share, 3)
    if melody and share < MELODY_MIN:
        lost = [s for s, w in carriers if not w]
        defects.append(("Б2", "Мелодия потеряна: в оркестре звучит только %d%% нот мелодии фортепиано (нет в тактах %s)."
                        % (round(100 * share), _bars(lost, bpb)), "измерение; порог 85% — эвристика"))
    hops, prev = [], None
    for s, who in carriers:
        if not who:
            continue
        if prev is not None and not (who & prev):
            hops.append(s)
        prev = who
    n_bars = max(1.0, (max((e for _, e, _, _ in O), default=0.0)) / bpb)
    stats["melody_hops"] = len(hops)
    stats["bars"] = round(n_bars)
    if hops and n_bars / len(hops) < HOP_BARS:
        defects.append(("Б3", "Мелодия скачет: %d переходов к другому инструменту за %d тактов, в среднем раз в %.1f такта "
                        "(места: такты %s)." % (len(hops), round(n_bars), n_bars / len(hops), _bars(hops, bpb)),
                        "измерение; порог «раз в 4 такта» — эвристика"))
    cov = len(covered) / max(found, 1)
    stats["melody_covered"] = round(cov, 3)
    if found and cov > COVER_MAX:
        warnings.append(("П1", "Мелодию перекрывают сверху: над %d%% нот мелодии звучит инструмент, который её не играет "
                         "(такты %s). Мелодию может быть плохо слышно." % (round(100 * cov), _bars(covered, bpb)),
                         "эвристика (смысл: мелодия должна выделяться, Римский-Корсаков гл. II)"))

    # Б4 молчащие
    playing = {n for *_, n in O}
    silent = [n for n in names if n not in playing and n in RU and n not in ("Piano", "Organ", "Accordion", "Guitar")]
    stats["silent"] = silent
    if silent and solo:      # с солистом молчащие в сопровождении — норма (Форсайт с. 197: «twelve stringed-instruments only»)
        warnings.append(("П2", "С солистом молчат: %s." % ", ".join(RU.get(n, n) for n in silent),
                         "так задумано: лёгкое сопровождение солиста"))
    elif silent:
        defects.append(("Б4", "Не играют ни одной ноты: %s." % ", ".join(RU.get(n, n) for n in silent),
                        "измерение; брак по решению пользователя (нужен полный состав)"))

    # П3 параллельные квинты, которых нет у фортепиано (2026-11-10)
    new5, all5 = _new_fifths(O, p_on, p_starts)
    stats["parallel_fifths"] = {"total": all5, "not_in_piano": len(new5)}
    if new5:
        warnings.append(("П3", "Параллельные квинты, которых нет в нотах фортепиано: %d (%s; такты %s)."
                         % (len(new5), ", ".join(sorted({"%s–%s" % (RU.get(a, a), RU.get(b, b)) for _, a, b in new5})[:4]),
                            _bars([t for t, _, _ in new5], bpb)),
                         "измерение; правило — Римский-Корсаков, «Практический учебник гармонии», §13 (с. 22–23); "
                         "квинты от октавных удвоений «не имеют значения» (Основы оркестровки, т. 1, с. 56)"))

    # Б5 длительность
    stats["seconds"] = {"piano": round(p_len, 1), "orchestra": round(o_len, 1)}
    if p_len > 0 and abs(o_len - p_len) / p_len > LEN_TOL:
        defects.append(("Б5", "Длительность не совпадает: фортепиано %.0f с, оркестр %.0f с." % (p_len, o_len),
                        "измерение; допуск 3% — эвристика"))
    return {"ok": not defects, "defects": defects, "warnings": warnings, "stats": stats}


def text(res):
    lines = ["КОНТРОЛЬ БРАКА: " + ("брака не найдено" if res["ok"] else "есть брак (%d)" % len(res["defects"]))]
    for code, t, st in res["defects"]:
        lines.append("[%s] %s  (статус: %s)" % (code, t, st))
    for code, t, st in res["warnings"]:
        lines.append("[%s, предупреждение] %s  (статус: %s)" % (code, t, st))
    s = res["stats"]
    lines.append("Измерено: чужих нот %d из %d; мелодии в оркестре %d%%; переходов мелодии %d за %d тактов; "
                 "длительность %s с / %s с." % (s["foreign"]["bad"], s["foreign"]["total"], round(100 * s["melody_found"]),
                                                s["melody_hops"], s["bars"], s["seconds"]["piano"], s["seconds"]["orchestra"]))
    lines.append("Контроль считает, а не слушает: «брака нет» не значит «звучит хорошо».")
    return "\n".join(lines)


if __name__ == "__main__":
    print(text(check(sys.argv[1], sys.argv[2])))
