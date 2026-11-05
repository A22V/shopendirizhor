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
