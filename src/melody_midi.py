"""
Напетая мелодия → MIDI (2026-11-08, этап 1 записи с микрофона).
Распознавание высоты делается в браузере (web/mic_recorder/index.html, алгоритм YIN: de Cheveigné & Kawahara,
JASA 111(4), 2002). Сюда приходят ноты в секундах; здесь они выравниваются по сетке темпа и записываются в MIDI.

Все пороги и правила в этом файле — эвристика (так и помечено), подбирались на синтезированном голосе.
"""
import io

import mido

GRID = {"нет": None, "восьмые": 0.5, "шестнадцатые": 0.25}   # доля четверти


def auto_octave(pitches):
    """Сдвиг в октавах, чтобы середина мелодии легла около C4–C5 (эвристика: удобно для оркестровки)."""
    if not pitches:
        return 0
    s = sorted(pitches)
    med = s[len(s) // 2]
    shift = 0
    while med + 12 * shift < 60:
        shift += 1
    while med + 12 * shift > 74:
        shift -= 1
    return shift


def quantize(notes, tempo, grid, poly=False):
    """notes: [[начало_с, длина_с, высота, громкость], ...] → [[начало_доли, длина_доли, высота, громкость]]."""
    spb = 60.0 / tempo
    out = []
    for t0, dur, p, v in sorted(notes):
        b0, b1 = t0 / spb, (t0 + dur) / spb
        if grid:
            b0 = round(b0 / grid) * grid
            b1 = max(b0 + grid, round(b1 / grid) * grid)
        out.append([b0, b1 - b0, int(p), int(v)])
    if poly:    # несколько нот сразу: оставляем всё; только одинаковую высоту не накладываем саму на себя
        last_end = {}
        res = []
        for n in sorted(out):
            prev = last_end.get(n[2])
            if prev is not None and prev[0] + prev[1] > n[0]:
                prev[1] = max(0.0, n[0] - prev[0])
            last_end[n[2]] = n
            res.append(n)
        return [n for n in res if n[1] > 1e-6]
    # одна линия: нота не залезает на следующую; две ноты в одной клетке сетки — оставляем первую
    clean = []
    for n in out:
        if clean and n[0] < clean[-1][0] + 1e-6:
            continue
        if clean and clean[-1][0] + clean[-1][1] > n[0]:
            clean[-1][1] = n[0] - clean[-1][0]
        clean.append(n)
    return [n for n in clean if n[1] > 1e-6]


def notes_to_midi(notes, tempo=80, grid="восьмые", octave="авто", name="Sung melody", program=0, poly=False):
    """Возвращает (байты MIDI, сведения). octave: "авто" или целое число октав.
    name — латиницей: mido пишет названия дорожек в latin-1, кириллицу не принимает."""
    if not notes:
        raise ValueError("нот нет: запись слишком тихая или короткая")
    tempo = max(30, min(240, float(tempo)))
    shift = (0 if poly else auto_octave([n[2] for n in notes])) if octave == "авто" else int(octave)
    q = quantize([[a, b, max(0, min(127, p + 12 * shift)), v] for a, b, p, v in notes], tempo, GRID.get(grid), poly)
    tpb = 480
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=name, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(meta)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name="Piano", time=0))
    tr.append(mido.Message("program_change", program=program, channel=0, time=0))
    ev = []
    for b0, d, p, v in q:
        ev.append((round(b0 * tpb), 1, p, v))
        ev.append((round((b0 + d) * tpb), 0, p, 0))
    ev.sort()
    last = 0
    for tick, on, p, v in ev:
        tr.append(mido.Message("note_on" if on else "note_off", note=p, velocity=max(1, v) if on else 0,
                               channel=0, time=tick - last))
        last = tick
    mid.tracks.append(tr)
    buf = io.BytesIO()
    mid.save(file=buf)
    info = {"notes": len(q), "tempo": tempo, "octave_shift": shift, "grid": grid,
            "beats": round(max((n[0] + n[1] for n in q), default=0), 2), "poly": bool(poly)}
    return buf.getvalue(), info
