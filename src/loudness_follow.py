"""Громкость оркестра следует за громкостью рояля (ORCH_FOLLOW=1, по умолчанию выкл.; на слух не проверено).

Зачем. Замер на тестовой пьесе на 2 минуты (2026-11-10, банк MS Basic): громкость рояля качается на 16 дБ,
громкость оркестра только на 8 дБ; в финале, самом громком месте рояля, оркестр был тише рояля на 5-8 дБ,
а в начале громче на 6-15 дБ. Причина: сила нажатия нот у оркестра берётся из трёх ступеней (mp/mf/f) и
не учитывает, сколько инструментов звучит одновременно.

Что делает. По нотам (без синтезатора) считается «энергия» звука в каждый момент: сумма квадратов силы
нажатия звучащих нот; у рояля нота затухает (постоянная 1,5 с), у остальных держится до конца ноты.
Разрыв «оркестр минус рояль» в дБ в каждой секунде (сглаженный по 4 с) сравнивается с обычным разрывом
(медиана); там, где оркестр громче обычного, ему убавляется громкость выражением CC11 (кривая плавная,
одна точка в секунду). Прибавить громкость выражением нельзя (максимум 127), поэтому убавляется всё
остальное, а самое «слабое» место остаётся как есть. Рояль не трогается.

Проверка расчёта: на тестовой пьесе разрыв по нотам и по настоящей записи совпадают с коэффициентом
корреляции 0,97 (рояль 0,97, оркестр 0,90). Все числа ниже (4 с, 1,5 с, предел 14 дБ) — эвристика.
Форма «громкость оркестра следует за роялем» — по жалобе пользователя (спад громкости со второй минуты).
"""
import os

import mido
import numpy as np

STEP = 0.05          # шаг расчёта, с
SMOOTH = 4.0         # сглаживание разрыва, с (эвристика)
DECAY = 1.5          # затухание ноты рояля, с (эвристика, подобрано по записи)
GAP_SCALE = 1.5      # во сколько раз разрыв на записи больше, чем по нотам (измерено на одной пьесе; проверить на других)
MAX_CUT_DB = 14.0    # самое большое убавление громкости (эвристика)
OUTLIER_RANGE_DB = 20.0   # разброс разрыва «оркестр − рояль», после которого считаем, что есть почти тихая секунда (эвристика)
BOOST_DB = 6.0       # на сколько дБ место может быть громче типичного (эвристика)
CC_STEP = 1.0        # шаг кривой CC11, с
SKIP_NAMES = ("piano", "organ", "percussion")


def enabled():
    return os.environ.get("ORCH_FOLLOW", "").strip().lower() in ("1", "true", "yes", "on")


def _notes(path):
    """[(начало, конец, сила, имя дорожки, канал)] по всем нотам файла, в секундах."""
    mid = mido.MidiFile(path)
    # карта темпа из всех дорожек
    ev = []
    for tr in mid.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "set_tempo":
                ev.append((t, m.tempo))
    ev.sort()
    tempo = ([(0, 500000)] + ev) if (not ev or ev[0][0] > 0) else ev
    tpb = mid.ticks_per_beat
    # накопленные секунды в точках смены темпа
    marks = []
    sec = 0.0
    last_t, last_tempo = 0, tempo[0][1]
    for t, tp in tempo:
        sec += (t - last_t) * last_tempo / 1e6 / tpb
        marks.append((t, sec, tp))
        last_t, last_tempo = t, tp

    def to_sec(tick):
        k = 0
        for j, (t, s, tp) in enumerate(marks):
            if t <= tick:
                k = j
            else:
                break
        t, s, tp = marks[k]
        return s + (tick - t) * tp / 1e6 / tpb

    out = []
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), "")
        t = 0
        on = {}
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity > 0:
                on.setdefault((m.channel, m.note), []).append((t, m.velocity))
            elif m.type in ("note_off", "note_on"):
                q = on.get((m.channel, m.note))
                if q:
                    t0, v = q.pop(0)
                    out.append((to_sec(t0), to_sec(t), v, name, m.channel))
    return out, to_sec, marks


def _energy(notes, n_steps, piano):
    amp = np.zeros(n_steps)
    for s, e, v, name, ch in notes:
        a = (v / 127.0) ** 2
        i0 = int(s / STEP)
        if i0 >= n_steps:
            continue
        if piano:
            L = int(6 / STEP)
            tt = np.arange(i0, min(n_steps, i0 + L)) * STEP - s
            amp[i0:i0 + len(tt)] += a * np.exp(-tt / DECAY)
        else:
            i1 = min(n_steps, int(e / STEP) + 1)
            amp[i0:i1] += a
    return amp


def _db_per_second(amp, seconds):
    k = int(round(1.0 / STEP))
    return np.array([10 * np.log10(amp[i * k:(i + 1) * k].mean() + 1e-9) for i in range(seconds)])


def curve(src_path, out_path):
    """Поправка громкости оркестра в дБ (≤ 0) по секундам. Возвращает (массив, сведения)."""
    src, _, _ = _notes(src_path)
    out, _, _ = _notes(out_path)
    out = [n for n in out if not any(k in n[3].lower() for k in SKIP_NAMES) and n[4] != 9]
    if not src or not out:
        return None, {"skipped": "нет нот"}
    T = max(max(n[1] for n in src), max(n[1] for n in out))
    seconds = int(T) + 1
    n_steps = int((seconds + 8) / STEP)
    p = _db_per_second(_energy(src, n_steps, True), seconds)
    o = _db_per_second(_energy(out, n_steps, False), seconds)
    gap = o - p
    w = int(SMOOTH)
    ker = np.ones(w) / w
    pad = np.pad(gap, (w // 2, w - 1 - w // 2), mode="edge")
    gap_s = np.convolve(pad, ker, mode="valid")
    typical = float(np.median(gap_s))
    # разрыв по нотам сжат сильнее, чем на настоящей записи: наклон 1,47 (корреляция 0,95, одна пьеса, 5-секундные окна)
    cut = -GAP_SCALE * (gap_s - gap_s.min())   # самое «слабое» место оркестра (относительно рояля) остаётся как есть
    # Одна почти тихая секунда (оркестр молчит, рояль играет: разрыв −40 дБ и ниже) тянет опору всей пьесы вниз:
    # на Мазурке (2026-11-10) весь оркестр сидел на −14 дБ, а одно место 89–92 с оставалось на полной громкости
    # (+14 дБ над соседями). Поэтому ни одно место не поднимается над типичным (медиана) больше чем на BOOST_DB.
    # Включается только при разбросе разрыва больше OUTLIER_RANGE_DB: на пьесах с обычным разбросом (7–10 дБ, в том числе
    # на одобренной на слух тестовой пьесе) кривая остаётся прежней, побайтно.
    if float(gap_s.max() - gap_s.min()) > OUTLIER_RANGE_DB:
        cut = np.minimum(cut, float(np.median(cut)) + BOOST_DB)
    cut = np.clip(cut, -MAX_CUT_DB, 0.0)
    info = {"typical_gap_db": round(typical, 1),
            "gap_range_before_db": round(float(gap_s.max() - gap_s.min()), 1),
            "cut_min_db": round(float(cut.min()), 1),
            "seconds": seconds}
    return cut, info


def apply(src_path, out_path):
    """Записывает кривую CC11 в дорожки оркестра файла out_path (рояль, орган, ударные не трогаются)."""
    cut, info = curve(src_path, out_path)
    if cut is None:
        return info
    mid = mido.MidiFile(out_path)
    _, to_sec, marks = _notes(out_path)
    tpb = mid.ticks_per_beat

    def to_tick(sec):
        k = 0
        for j, (t, s, tp) in enumerate(marks):
            if s <= sec:
                k = j
            else:
                break
        t, s, tp = marks[k]
        return int(round(t + (sec - s) * 1e6 * tpb / tp))

    changed = 0
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), "")
        chans = {m.channel for m in tr if m.type in ("note_on", "program_change")}
        if not chans or any(k in name.lower() for k in SKIP_NAMES) or 9 in chans:
            continue
        ch = sorted(chans)[0]
        # абсолютные времена, вставка CC11, обратно в относительные
        absm, t = [], 0
        for m in tr:
            t += m.time
            absm.append((t, m))
        last_cc = None
        n = 0
        for i, db in enumerate(cut):
            cc = int(round(127 * 10 ** (db / 40)))
            cc = max(30, min(127, cc))
            if cc == last_cc:
                continue
            absm.append((to_tick(i * CC_STEP), mido.Message("control_change", channel=ch, control=11, value=cc)))
            last_cc = cc
            n += 1
        absm.sort(key=lambda x: x[0])   # сортировка устойчивая: порядок событий в один тик сохраняется
        new, prev = [], 0
        for t, m in absm:
            new.append(m.copy(time=t - prev))
            prev = t
        tr[:] = new
        changed += n
    mid.save(out_path)
    info["cc11_events"] = changed
    return info
