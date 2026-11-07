"""
Автоисправление партитуры по замечаниям рецензента (src/score_review.py).

Правило F2 (к замечанию K2): быстрые ноты у валторны, фагота, контрабаса.
  Смысл подтверждён: Черни, Op. 600, т. 3, с. 22 и 28 (быстрое отдаётся струнным, валторна держит длинные ноты).
  Как исправляем (эвристика): в каждой доле, где у такого инструмента есть ноты короче полдоли, остаётся одна
  опорная нота (та, что звучит на начале доли, иначе первая в доле) длиной до конца доли. Ноты длиной от
  полдоли не трогаются. Высоты не меняются, новые ноты не придумываются.

Два входа:
  * simplify_fast(notes) работает со списком нот [старт, длина, высота, ...] (в долях); его вызывает оркестратор
    при ORCH_FIX_FAST=1 до записи MIDI и MusicXML;
  * fix_midi(вход.mid, выход.mid) исправляет готовый оркестровый MIDI (режим «Проверить партитуру»).
Оба возвращают список изменений по-русски.
"""
import os
import mido

FAST_BEATS = 0.5   # как в score_review (эвристика)
SLOW_KEYS = {"horn", "bassoon", "double_bass"}
RU_LINES = {"Horn": "Валторна", "Bassoon": "Фагот", "Double Bass": "Контрабас"}


def enabled():
    return os.environ.get("ORCH_FIX_FAST", "") not in ("", "0", "false", "False")


def simplify_fast(notes, beat=1.0):
    """notes: список [старт, длина, высота, *прочее] в долях. Возвращает (новые_ноты, затронутые_доли)."""
    notes = sorted([list(n) for n in notes], key=lambda n: (n[0], n[2]))
    fast_beats = {int(n[0] // beat + 1e-9) for n in notes if n[1] < FAST_BEATS * beat - 1e-9}
    if not fast_beats:
        return notes, []
    out = []
    for b in sorted(fast_beats):
        lo, hi = b * beat, (b + 1) * beat
        inside = [n for n in notes if lo - 1e-9 <= n[0] < hi - 1e-9]
        if not inside: continue
        if all(n[1] >= FAST_BEATS * beat - 1e-9 for n in inside): continue
        # если доля накрыта длинной нотой, начатой раньше, быстрые ноты внутри просто убираем
        covering = any(n[0] < lo - 1e-9 and n[0] + n[1] > lo + 1e-9 and n[1] >= FAST_BEATS * beat - 1e-9 for n in notes)
        on_beat = [n for n in inside if abs(n[0] - lo) < 1e-6]
        keep = None if covering else (on_beat or inside)[0]
        for n in inside:
            if n is keep: continue
            if n[1] >= FAST_BEATS * beat - 1e-9: continue   # длинные ноты остаются как были
            n.append("__drop__")                              # быстрая нота убирается
        if keep is not None:
            keep[0], keep[1] = lo, max(keep[1], hi - lo)      # опорная нота с начала доли до её конца
        out.append(b)
    res = [n for n in notes if not (n and n[-1] == "__drop__")]
    res.sort(key=lambda n: (n[0], n[2]))
    # без перекрытий: нота обрезается по началу следующей (урок из CLAUDE.md, раздел 5)
    for i in range(len(res) - 1):
        if res[i][0] + res[i][1] > res[i + 1][0] + 1e-9 and res[i + 1][0] > res[i][0] + 1e-9:
            res[i][1] = res[i + 1][0] - res[i][0]
    res = [n for n in res if n[1] > 1e-6]
    return res, out


def _bars(beats, bpb):
    import score_review
    return score_review._rng(sorted({int(b // bpb) + 1 for b in beats}))


def fix_lines(lines, beats_per_bar=4.0, ru_name=None):
    """Для оркестратора: lines = {"Horn": [[старт, длина, высота, роль], ...], ...}. Меняет на месте."""
    changes = []
    for name in ("Horn", "Bassoon", "Double Bass"):
        seq = lines.get(name)
        if not seq: continue
        before = len(seq)
        new, beats = simplify_fast(seq)
        if beats:
            lines[name] = new
            label = (ru_name or RU_LINES).get(name, name)
            changes.append(f"{label}: быстрые ноты заменены опорными по долям в тактах {_bars(beats, beats_per_bar)}; нот было {before}, стало {len(new)}.")
    return changes


def fix_midi(src, dst):
    """Исправляет готовый MIDI оркестра. Дорожки ищутся по названию (как в рецензенте). Возвращает список изменений."""
    import score_review
    m = mido.MidiFile(src)
    tpb = m.ticks_per_beat
    _, bpb, _ = score_review.read_midi(src)
    changes, seen_violin = [], 0
    for ti, tr in enumerate(m.tracks):
        key = score_review._key(tr.name or "")
        if key not in SLOW_KEYS: continue
        ticks, on, notes, other = 0, {}, [], []
        for msg in tr:
            ticks += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault(msg.note, []).append((ticks, msg.velocity, msg.channel))
            elif msg.type in ("note_off", "note_on") and msg.note in on and on[msg.note]:
                st, vel, ch = on[msg.note].pop(0)
                notes.append([st / tpb, max(ticks - st, 1) / tpb, msg.note, vel, ch])
            elif not msg.type.startswith("note_"):
                other.append((ticks, msg))
        new, beats = simplify_fast(notes)
        if not beats: continue
        ev = [(t, 2, msg) for t, msg in other if msg.type != "end_of_track"]
        for s, d, p, vel, ch in new:
            a, b = int(round(s * tpb)), int(round((s + d) * tpb))
            ev.append((a, 1, mido.Message("note_on", note=p, velocity=vel, channel=ch)))
            ev.append((b, 0, mido.Message("note_off", note=p, velocity=0, channel=ch)))
        ev.sort(key=lambda e: (e[0], e[1]))
        tr2, last = mido.MidiTrack(), 0
        for t, _, msg in ev:
            tr2.append(msg.copy(time=t - last)); last = t
        end = max([t for t, _, _ in ev] + [0])
        tr2.append(mido.MetaMessage("end_of_track", time=0))
        m.tracks[ti] = tr2
        changes.append(f"{score_review.RU[key]}: быстрые ноты заменены опорными по долям в тактах {_bars(beats, bpb)}; нот было {len(notes)}, стало {len(new)}.")
    m.save(dst)
    return changes


# ---------------------------------------------------------------------------
# F4 (к замечанию K4 «нет ни одной ноты ниже C3»), 2026-11-07, по просьбе пользователя («есть функция исправления?»).
# Только по кнопке, отдельным файлом; по умолчанию в оркестровку не входит. На слух НЕ одобрено.
# Способ (эвристика): в таких тактах контрабас берёт бас на октаву ниже:
#   * если контрабас в такте играет — его ноты опускаются на октаву (не ниже E1 = 28);
#   * если молчит, а играет виолончель — контрабас удваивает самые низкие ноты виолончели октавой ниже;
#   * если нет ни контрабаса, ни виолончели — такт не трогается (лёгкая фактура может быть задумана).
# Новых высот не придумывает: только октавное удвоение баса. Внимание: Форсайт (с. 439) советует держать контрабасы
# повыше («keep the Basses up»); поэтому это проба, а не правило. Граница C3 — эвристика рецензента.
# ---------------------------------------------------------------------------
LOW_LIMIT = 48      # C3, как в score_review (эвристика)
DB_LOWEST = 28      # E1, нижняя нота контрабаса (Берлиоз: 28–57 в таблице проекта)


def _read_tracks(m):
    tpb = m.ticks_per_beat
    out = []
    for ti, tr in enumerate(m.tracks):
        ticks, on, notes, other = 0, {}, [], []
        for msg in tr:
            ticks += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault(msg.note, []).append((ticks, msg.velocity, msg.channel))
            elif msg.type in ("note_off", "note_on") and msg.note in on and on[msg.note]:
                st, vel, ch = on[msg.note].pop(0)
                notes.append([st / tpb, max(ticks - st, 1) / tpb, msg.note, vel, ch])
            elif not msg.type.startswith("note_"):
                other.append((ticks, msg))
        out.append((ti, tr, notes, other))
    return out


def _write_track(m, ti, notes, other):
    tpb = m.ticks_per_beat
    ev = [(t, 2, msg) for t, msg in other if msg.type != "end_of_track"]
    for s, d, p, vel, ch in notes:
        a, b = int(round(s * tpb)), int(round((s + d) * tpb))
        ev.append((a, 1, mido.Message("note_on", note=p, velocity=vel, channel=ch)))
        ev.append((max(b, a + 1), 0, mido.Message("note_off", note=p, velocity=0, channel=ch)))
    ev.sort(key=lambda e: (e[0], e[1]))
    tr2, last = mido.MidiTrack(), 0
    for t, _, msg in ev:
        tr2.append(msg.copy(time=t - last)); last = t
    tr2.append(mido.MetaMessage("end_of_track", time=0))
    m.tracks[ti] = tr2


def fix_low(src, dst):
    """Исправляет K4 в готовом MIDI оркестра. Возвращает список изменений по-русски."""
    import score_review
    m = mido.MidiFile(src)
    _, bpb, _ = score_review.read_midi(src)
    tracks = _read_tracks(m)
    keyed = {}
    for ti, tr, notes, other in tracks:
        k = score_review._key(tr.name or "")
        if k and k not in keyed and (notes or k == "double_bass"):
            keyed[k] = (ti, tr, notes, other)
    allnotes = [n for _, tr, notes, _ in tracks if not any(x.type in ("note_on",) and x.channel == 9 for x in tr)
                for n in notes]
    if not allnotes or "double_bass" not in keyed:
        m.save(dst)
        return [] if allnotes else []
    n_bars = int(max(s + d for s, d, *_ in allnotes) // bpb) + 1
    low = [None] * n_bars
    for s, d, p, *_ in allnotes:
        b = int(s // bpb)
        if 0 <= b < n_bars:
            low[b] = p if low[b] is None else min(low[b], p)
    hollow = {b for b in range(n_bars) if low[b] is not None and low[b] >= LOW_LIMIT}
    if not hollow:
        m.save(dst)
        return []
    ti, tr, db, other = keyed["double_bass"]
    cello = keyed.get("cello", (None, None, [], None))[2]
    db_bars = {int(s // bpb) for s, *_ in db}
    lowered, doubled = set(), set()
    new_db = []
    for s, d, p, vel, ch in db:
        b = int(s // bpb)
        if b in hollow and p - 12 >= DB_LOWEST:
            new_db.append([s, d, p - 12, vel, ch]); lowered.add(b)
        else:
            new_db.append([s, d, p, vel, ch])
    ch_db = db[0][4] if db else next((x.channel for x in tr if hasattr(x, "channel")), 0)
    by_start = {}
    for s, d, p, vel, ch in cello:
        b = int(s // bpb)
        if b in hollow and b not in db_bars:
            if s not in by_start or p < by_start[s][2]:
                by_start[s] = [s, d, p, vel, ch]
    for s, d, p, vel, _ in sorted(by_start.values()):
        if p - 12 >= DB_LOWEST:
            new_db.append([s, d, p - 12, max(20, vel - 6), ch_db]); doubled.add(int(s // bpb))
    new_db.sort()
    for i in range(len(new_db) - 1):          # один инструмент — одна нота: обрезать по началу следующей
        if new_db[i][0] + new_db[i][1] > new_db[i + 1][0] and new_db[i + 1][0] > new_db[i][0]:
            new_db[i][1] = new_db[i + 1][0] - new_db[i][0]
    if not (lowered or doubled):
        m.save(dst)
        return []
    _write_track(m, ti, new_db, other)
    m.save(dst)
    ch = []
    if lowered:
        ch.append("Контрабас опущен на октаву в тактах " + _bars([b * bpb for b in sorted(lowered)], bpb) + ".")
    if doubled:
        ch.append("Контрабас удваивает виолончель октавой ниже в тактах " + _bars([b * bpb for b in sorted(doubled)], bpb) + ".")
    left = sorted(hollow - lowered - doubled)
    if left:
        ch.append("Не тронуты такты " + _bars([b * bpb for b in left], bpb) + ": там нет ни контрабаса, ни виолончели.")
    return ch


FIXES = {   # код замечания -> (подпись кнопки, функция, одобрено ли на слух)
    "K2": ("Быстрые ноты валторны, фагота, контрабаса → опорные ноты по долям", fix_midi, True),
    "K4": ("Пустой низ → контрабас берёт бас октавой ниже (проба)", fix_low, False),
}
