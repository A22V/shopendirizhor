"""
Проверка переложения для фортепиано (готовый MIDI рояля), по образцу проверки партитуры (score_review.py).
Ничего не исправляет и не меняет звук: только находит места и честно называет статус каждого правила.

Как определяются руки:
  * если в файле две и больше дорожек с нотами: верхняя по средней высоте = правая рука, остальные = левая;
  * если дорожка одна (так пишет переложение нашей программы: обе руки в одном треке «Piano»),
    каждый аккорд (ноты, начатые вместе) делится на две руки так, чтобы обеим было удобно (размах не шире ноны,
    не больше 5 нот), а граница была ближе к до первой октавы. Это приблизительно: настоящая аппликатура неизвестна.

Правила:
  P1 растяжка одной руки больше 14 полутонов (ноны). Подтверждено: Берлиоз, «Трактат об инструментовке», глава
     о фортепиано (крайние звуки руки в пределах октавы, самое большее ноны, шире только с педалью); Fujita 2008 и
     Chiu 2009 по Nakamura & Yoshii 2018 (arXiv 1808.05006), введение («less than 14 semitones or so»; авторы
     подчёркивают, что это не строгое правило). При одной дорожке: аккорд, который нельзя разделить на две руки без такой растяжки.
  P2 больше 5 нот в одной руке одновременно. Эвристика (по числу пальцев; в книгах число не проверено).
  P3 руки перекрещиваются (нота левой выше ноты правой в одном аккорде). Только при двух дорожках. Эвристика:
     перекрещивание бывает приёмом, но в переложении обычно неудобно.
  P4 расстояние между руками больше 18 полутонов. НЕ ПОДТВЕРЖДЕНО (reduction.HAND_GAP_LIMIT, число из непроверенного
     отчёта). Только справка, не замечание: на фортепианных оригиналах (ноктюрн, прелюдия) это обычное дело (43 и 54 места).
  P5 скачок верхнего голоса правой или нижнего голоса левой руки больше октавы за четверть доли и быстрее. Эвристика.
  P6 сохранённая гармония (если дан оркестровый оригинал): какая доля высот (без учёта октавы) оригинала звучит у рояля
     в те же моменты. Измерение; порог «в такте сохранено меньше половины» эвристика.
"""
import os, sys, collections
import mido

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reduction

SPAN = reduction.HAND_SPAN_LIMIT      # 14 (подтверждено)
GAP = reduction.HAND_GAP_LIMIT        # 18 (не подтверждено)
MAX_NOTES = 5                         # эвристика: пять пальцев
LEAP, LEAP_BEATS = 12, 0.25           # эвристика (при 0,5 доли правило ложно срабатывало на обычном аккомпанементе ноктюрна: 40 мест)
LOW_COVER = 0.5                       # эвристика
MIDDLE_C = 60
PERCUSSION = reduction.PERCUSSION
RH, LH = "Правая рука", "Левая рука"

ST_SPAN = ("подтверждено: Берлиоз, глава о фортепиано; Fujita 2008 и Chiu 2009 по Nakamura & Yoshii 2018, введение "
           "(14 полутонов «или около того», не строгое правило)")
ST_NOTES = "эвристика (по числу пальцев, в книгах число не проверено)"
ST_CROSS = "эвристика (перекрещивание бывает приёмом, но в переложении обычно неудобно)"
ST_GAP = "не подтверждено (число 18 из непроверенного отчёта; оставлено в программе за пользу на слух)"
ST_LEAP = "эвристика (октава и четверть доли — наши числа)"
ST_COVER = "измерение; порог «меньше половины в такте» — эвристика"


def read(path):
    """Ноты (старт, длина, высота, дорожка) в долях, доли в такте, темп. Ударные пропускаются."""
    m = mido.MidiFile(path)
    tpb, tempo, bpb = m.ticks_per_beat, 500000, 4.0
    notes = []
    for ti, tr in enumerate(m.tracks):
        t, on = 0, {}
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo" and t == 0: tempo = msg.tempo
            if msg.type == "time_signature" and t == 0: bpb = msg.numerator * 4.0 / msg.denominator
            ch = getattr(msg, "channel", 0)
            if ch in PERCUSSION: continue
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault((ch, msg.note), []).append(t)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                k = (ch, msg.note)
                if on.get(k):
                    s = on[k].pop(0)
                    notes.append((s / tpb, max(t - s, 1) / tpb, msg.note, ti))
    return sorted(notes), bpb, 60e6 / tempo


def _groups(notes, tol=0.125):
    out = []
    for n in notes:
        if out and n[0] - out[-1][0] <= tol: out[-1][1].append(n)
        else: out.append([n[0], [n]])
    return out


def _span(ps):
    return max(ps) - min(ps) if ps else 0


def split_chord(pitches):
    """Делит аккорд на (левая, правая) так, чтобы обе руки были удобны; если нельзя, берёт наименее неудобное."""
    p = sorted(set(pitches))
    best = None
    for k in range(len(p) + 1):
        lh, rh = p[:k], p[k:]
        bad = max(_span(lh) - SPAN, 0) + max(_span(rh) - SPAN, 0) + 3 * (max(len(lh) - MAX_NOTES, 0) + max(len(rh) - MAX_NOTES, 0))
        border = (lh[-1] + rh[0]) / 2 if lh and rh else (rh[0] - 6 if rh else lh[-1] + 6)
        key = (bad, abs(border - MIDDLE_C))
        if best is None or key < best[0]:
            best = (key, lh, rh)
    return best[1], best[2]


def review(piano_path, original_path=None):
    notes, bpb, bpm = read(piano_path)
    findings, marks = [], []

    def add(code, status, text, cells=()):
        findings.append(("замечание", code, status, text)); marks.append(sorted(set(cells), key=lambda c: (c[1], c[0])))

    def bar(beat): return int(beat // bpb) + 1

    tracks = collections.defaultdict(list)
    for n in notes: tracks[n[3]].append(n[2])
    by_tracks = len(tracks) >= 2
    if by_tracks:
        top = max(tracks, key=lambda k: sum(tracks[k]) / len(tracks[k]))
        hand_of = lambda n: RH if n[3] == top else LH
    groups = _groups(notes)
    chords = []        # (старт, левая, правая)
    for start, items in groups:
        if by_tracks:
            lh = sorted({n[2] for n in items if hand_of(n) == LH}); rh = sorted({n[2] for n in items if hand_of(n) == RH})
        else:
            lh, rh = split_chord([n[2] for n in items])
        chords.append((start, lh, rh))
    n_bars = bar(max(n[0] + n[1] for n in notes) - 1e-6) if notes else 0
    play = [set() for _ in range(n_bars)]
    for start, lh, rh in chords:
        b = bar(start) - 1
        if 0 <= b < n_bars:
            if lh: play[b].add(LH)
            if rh: play[b].add(RH)

    # P1 растяжка
    bad = [(h, bar(s)) for s, lh, rh in chords for h, ps in ((LH, lh), (RH, rh)) if _span(ps) > SPAN]
    if bad:
        worst = max(_span(ps) for s, lh, rh in chords for ps in (lh, rh))
        what = ("аккорд нельзя взять двумя руками без растяжки шире ноны" if not by_tracks
                else "одна рука растянута шире ноны")
        add("P1", ST_SPAN, "Растяжка руки больше 14 полутонов: %s; мест: %d, самая широкая растяжка %d полутонов, такты %s."
            % (what, len(bad), worst, _rng(sorted({b for _, b in bad}))), bad)
    # P2 нот в руке
    many = [(h, bar(s)) for s, lh, rh in chords for h, ps in ((LH, lh), (RH, rh)) if len(ps) > MAX_NOTES]
    if many:
        add("P2", ST_NOTES, "Больше %d нот в одной руке одновременно; мест: %d, такты %s." % (MAX_NOTES, len(many), _rng(sorted({b for _, b in many}))), many)
    # P3 перекрещивание
    if by_tracks:
        cross = [bar(s) for s, lh, rh in chords if lh and rh and max(lh) > min(rh)]
        if cross:
            add("P3", ST_CROSS, "Руки перекрещиваются (нота левой выше ноты правой); мест: %d, такты %s." % (len(cross), _rng(sorted(set(cross)))),
                [(h, b) for b in cross for h in (LH, RH)])
    # P4 расстояние между руками: только справка (число не подтверждено, на оригиналах срабатывает постоянно)
    gaps = [bar(s) for s, lh, rh in chords if GAP and lh and rh and min(rh) - max(lh) > GAP]
    # P5 скачки (верх правой и низ левой не зависят от того, как поделён аккорд)
    leaps = []
    for h, pick in ((RH, lambda c: max(c[2]) if c[2] else None), (LH, lambda c: min(c[1]) if c[1] else None)):
        prev = None
        for c in chords:
            p = pick(c)
            if p is None: continue
            if prev and c[0] - prev[0] <= LEAP_BEATS + 1e-9 and abs(p - prev[1]) > LEAP:
                leaps.append((h, bar(c[0])))
            prev = (c[0], p)
    if leaps:
        add("P5", ST_LEAP, "Скачок больше октавы за четверть доли и быстрее; мест: %d, такты %s." % (len(leaps), _rng(sorted({b for _, b in leaps}))), leaps)
    # P6 сохранённая гармония
    cover = None
    if original_path:
        orig, _, _ = read(original_path)
        per_bar = collections.defaultdict(list)
        vals = []
        for start, items in _groups(orig):
            pcs = {n[2] % 12 for n in items}
            sounding = {n[2] % 12 for n in notes if n[0] <= start + 0.125 and n[0] + n[1] > start + 1e-6}
            v = len(pcs & sounding) / len(pcs)
            vals.append(v); per_bar[bar(start)].append(v)
        if vals:
            cover = {"среднее": round(sum(vals) / len(vals), 3), "все_высоты": round(sum(1 for v in vals if v >= 0.999) / len(vals), 3)}
            low = sorted(b for b, vs in per_bar.items() if sum(vs) / len(vs) < LOW_COVER)
            if low:
                add("P6", ST_COVER, "Мало гармонии оригинала: в тактах %s у рояля звучит меньше половины высот оркестра (в среднем по пьесе %.0f%%)."
                    % (_rng(low), 100 * cover["среднее"]), [("*", b) for b in low])
    counts = [len(s) for s in play]
    stats = {"тактов": n_bars, "темп_уд_мин": round(bpm), "нот": len(notes),
             "руки": "по дорожкам" if by_tracks else "по аккордам (одна дорожка, деление приблизительное)",
             "гармония": cover, "между_руками_больше_18": len(gaps)}
    return {"stats": stats, "findings": findings, "counts": counts, "marks": marks,
            "grid": {"instruments": [RH, LH], "play": [sorted(s) for s in play]}}


def _rng(bars):
    import score_review
    return score_review._rng(bars)


def report_text(res, title):
    s = res["stats"]
    L = [f"# Проверка переложения: {title}", "",
         f"Тактов: {s['тактов']}, темп около {s['темп_уд_мин']} уд/мин, нот: {s['нот']}. Руки определены {s['руки']}."]
    if s.get("гармония"):
        L.append("Сохранено высот гармонии оригинала: в среднем %.0f%%; все высоты аккорда звучат в %.0f%% моментов."
                 % (100 * s["гармония"]["среднее"], 100 * s["гармония"]["все_высоты"]))
    if s.get("между_руками_больше_18"):
        L.append("Справка: между руками больше 18 полутонов в %d аккордах (число не подтверждено источником; в фортепианной музыке это обычно)."
                 % s["между_руками_больше_18"])
    L += ["", "Модуль считает, а не слушает. Звучание оценивает слушатель.", ""]
    if not res["findings"]:
        L.append("Замечаний нет.")
    for i, (_, code, st, text) in enumerate(res["findings"], 1):
        L += [f"{i}. [{code}] {text}", f"   Статус правила: {st}.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Использование: python src/piano_review.py переложение.mid [оркестровый_оригинал.mid] [--map]"); sys.exit(1)
    r = review(args[0], args[1] if len(args) > 1 else None)
    print(report_text(r, os.path.basename(args[0])))
    if "--map" in sys.argv:
        import score_review
        out = os.path.splitext(args[0])[0] + "_карта_замечаний.html"
        open(out, "w", encoding="utf-8").write(score_review.map_html(r, standalone=True)); print("Карта:", out)
