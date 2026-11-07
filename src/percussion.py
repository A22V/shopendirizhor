"""
Лёгкие ударные для ритма (2026-11-07, по просьбе пользователя: «неоклассическая оркестровка, как у оркестра
Поля Мориа, где для ритма играют ненавязчивые ударные»). Включается галочкой в приложении, по умолчанию выключено.

Что делает: после того как оркестровка готова (и громкость инструментов выровнена), добавляет в MIDI отдельную
дорожку «Percussion» на 10-м канале General MIDI (ударная установка). Ноты оркестра не меняются.
Рисунок по размеру такта:
  * 4/4 (и 2/4): тихая бочка на 1 (в mf и f ещё на 3), удар по ободу малого барабана на 2 и 4,
    закрытый хай-хэт восьмыми (в медленном темпе — четвертями);
  * 3/4: бочка на 1, хай-хэт на 2 и 3 (вальсовое «ум-па-па»);
  * 6/8: бочка на 1, обод на 4, хай-хэт восьмыми.
Громкость следует громкости фраз (mp/mf/f), в начале кульминации — тихая тарелка, в последнем такте — бочка и
тарелка на сильную долю, после этого тишина.
Статус: ВСЁ эвристика. Номера ударных — стандарт General MIDI; рисунки и громкости — наши, в источниках проекта
(Берлиоз, Форсайт, Римский-Корсаков, Черни, Праут) ритм-секция эстрадного оркестра не описана. Стиль Поля Мориа
по записям мы не сверяли: это «похоже по духу», а не копия.
В нотах (MusicXML) ударных нет: только в MIDI и MP3.
"""
import mido

KICK, STICK, HAT, CRASH, SHAKER = 36, 37, 42, 49, 70     # General MIDI, 10-й канал
CH = 9
LEVEL_SCALE = {"mp": 0.75, "mf": 1.0, "f": 1.2}             # эвристика
BASE_VEL = {KICK: 52, STICK: 40, HAT: 34, CRASH: 50, SHAKER: 34}   # эвристика: ненавязчиво
SLOW_BPM = 72              # эвристика: медленнее — хай-хэт четвертями


def _pattern(num, den, bpm, level):
    """[(доля от начала такта, нота)] для одного такта; доли — четверти."""
    beat = 4.0 / den
    if num == 3 and den == 4:
        return [(0.0, KICK), (1.0, HAT), (2.0, HAT)]
    if num == 6 and den == 8:
        return [(0.0, KICK), (1.5, STICK)] + [(i * 0.5, HAT) for i in range(6)]
    bar = num * beat
    out = [(0.0, KICK)]
    if level in ("mf", "f") and num >= 4:
        out.append((2.0 * beat, KICK))
    out += [(k * beat, STICK) for k in range(1, num, 2)]
    step = beat if bpm < SLOW_BPM else beat / 2
    t = 0.0
    while t < bar - 1e-9:
        out.append((t, HAT)); t += step
    return out


def add(midi_path, bars, dyn, climax_bars=(), tsigs=None, bpm=100.0):
    """bars: [(начало, длина)] в долях; dyn: {номер_такта_с_0: "mp"/"mf"/"f"}; climax_bars: номера тактов с 0, где
    начинается кульминация. Возвращает число добавленных ударов."""
    mid = mido.MidiFile(midi_path)
    tpb = mid.ticks_per_beat
    sigs = sorted(tsigs or [(0.0, "4/4")])
    ev = []
    for bi, (start, length) in enumerate(bars):
        ratio = [r for off, r in sigs if off <= start + 1e-9][-1] if sigs else "4/4"
        num, den = (int(x) for x in str(ratio).split("/"))
        level = dyn.get(bi, "mf")
        scale = LEVEL_SCALE.get(level, 1.0)
        last = bi == len(bars) - 1
        hits = [(0.0, KICK), (0.0, CRASH)] if last else _pattern(num, den, bpm, level)
        if bi in climax_bars and not last:
            hits.append((0.0, CRASH))
        for pos, note in hits:
            if pos >= length - 1e-9:
                continue
            vel = int(max(12, min(110, BASE_VEL[note] * scale)))
            if note == HAT and pos % 1.0 > 1e-6:
                vel = int(vel * 0.8)          # слабые восьмые тише
            on = int(round((start + pos) * tpb))
            ev.append((on, 1, note, vel))
            ev.append((on + int(tpb * (1.5 if note == CRASH else 0.2)), 0, note, 0))
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name="Percussion", time=0))
    tr.append(mido.Message("control_change", channel=CH, control=7, value=90, time=0))
    tr.append(mido.Message("control_change", channel=CH, control=91, value=40, time=0))
    prev = 0
    for tick, kind, note, vel in sorted(ev, key=lambda e: (e[0], e[1])):
        msg = "note_on" if kind else "note_off"
        tr.append(mido.Message(msg, channel=CH, note=note, velocity=vel, time=tick - prev))
        prev = tick
    tr.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(tr)
    mid.save(midi_path)
    return sum(1 for e in ev if e[1])
