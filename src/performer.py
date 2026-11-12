"""Слой «исполнитель»: оркестр играет фразами, а не ровными нотами (ORCH_PERFORM=1; по умолчанию выкл.).

Повод (пользователь, 2026-11-12): «дело в аранжировке и манере исполнения… чтобы не колхозно, а по-настоящему».
Что было: сила нажатия ноты зависела только от ступени громкости фразы (mp/mf/f) и роли; внутри фразы все ноты
одного инструмента одинаковы, длинная нота стоит на одной громкости от начала до конца.

Что делает (нот, высот, начал и длин НЕ меняет; меняет только силу нажатия и кривую выражения CC11):
1. Фраза инструмента = ноты подряд без паузы длиннее `PHRASE_GAP` доли. Внутри фразы громкость идёт дугой:
   от начала нарастает к вершине (самая высокая нота, если она между 30% и 80% фразы, иначе 60%) и спадает к концу.
   Глубина дуги у мелодии `ARC_MELODY_DB`, у сопровождения `ARC_OTHER_DB`.
2. Последняя нота фразы (не короче доли) затихает («снятие смычка / конец дыхания»).
3. Долгая нота внутри фразы (от `LONG_NOTE` долей) слегка «раскрывается» после начала, а не стоит столбом.
4. У мелодии более высокие ноты фразы чуть сильнее, низкие чуть слабее (`HIGH_LOUD` на полутон).
5. У сопровождения короткие ноты на сильной доле такта чуть сильнее, между долями чуть слабее.
Дуга для тянущихся инструментов делается выражением CC11 (громкость меняется и во время ноты), и той же дугой
немного сдвигается сила нажатия (атака). Кривая ORCH_FOLLOW (тоже CC11) сохраняется: дуга умножается на неё.
CC11 может только убавлять (потолок 127), поэтому вершина фразы остаётся как была, края тише.

Статус: смысл («фразировка дугой», метрические акценты, артикуляция) — общие принципы исполнения, описанные в
системе правил KTH (Friberg, Bresin, Sundberg, «Overview of the KTH rule system for musical performance»,
Advances in Cognitive Psychology, 2006: в аннотации названы phrasing, metrical patterns, articulation; сама статья
не прочитана, названия отдельных правил и числа из неё НЕ взяты). Все числа ниже — эвристика. На слух не проверено.
"""
import os

import mido

PHRASE_GAP = 0.5       # доли: пауза, после которой начинается новая фраза инструмента (эвристика)
PHRASE_MAX = 16.0      # доли: фраза длиннее делится по границам фраз плана (эвристика)
PHRASE_MIN = 2.0       # доли: короче — дуги нет
ARC_MELODY_DB = 4.0    # глубина дуги у мелодии, дБ (эвристика)
ARC_OTHER_DB = 2.5     # глубина дуги у сопровождения, дБ (эвристика)
END_SHARE = 0.8        # конец фразы тише вершины на эту долю глубины
TAPER_DB = 3.0         # затухание последней ноты фразы, дБ (эвристика)
LONG_NOTE = 3.0        # доли: «долгая нота» (эвристика)
SWELL_DB = 1.5         # раскрытие долгой ноты, дБ (эвристика)
ARC_VEL = 6            # сдвиг силы нажатия по дуге: от −ARC_VEL у края до +ARC_VEL на вершине (эвристика)
HIGH_LOUD = 0.4        # сила нажатия на полутон выше/ниже середины фразы, только мелодия (эвристика)
HIGH_LOUD_MAX = 4
METRIC_VEL = 3         # сопровождение: сильная доля +, между долями − (эвристика)
MIN_DB = -9.0          # дуга и затухание вместе не убавляют больше этого
GRID = 8               # точек кривой CC11 на долю
SKIP_NAMES = ("piano", "organ", "percussion")
RENAME = {"Violoncello": "Cello", "Contrabass": "Double Bass"}


def enabled():
    return os.environ.get("ORCH_PERFORM", "").strip().lower() in ("1", "true", "yes", "on")


def _ease(x):
    """Плавный ход 0→1 (косинус)."""
    import math
    x = max(0.0, min(1.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def _phrases(notes, tpb, cuts):
    """notes: [[начало, конец, высота, сила, мелодия?]] по началу. Возвращает список фраз (списков нот)."""
    out, cur, end = [], [], None
    for n in notes:
        if cur and n[0] - end > PHRASE_GAP * tpb:
            out.append(cur); cur = []
        cur.append(n)
        end = n[1] if end is None or not cur[:-1] else max(end, n[1])
    if cur:
        out.append(cur)
    res = []
    for ph in out:
        s, e = ph[0][0], max(n[1] for n in ph)
        inner = [c for c in cuts if s + 4 * tpb <= c <= e - 4 * tpb] if e - s > PHRASE_MAX * tpb else []
        if not inner:
            res.append(ph); continue
        edges = [s] + inner + [e + 1]
        for a, b in zip(edges, edges[1:]):
            part = [n for n in ph if a <= n[0] < b]
            if part:
                res.append(part)
    return res


def _shape(ph, tpb, is_mel):
    """Возвращает (функция env(t) в дБ ≤ 0, начало, конец) или None, если фраза слишком короткая."""
    s, e = ph[0][0], max(n[1] for n in ph)
    length = e - s
    if length < PHRASE_MIN * tpb:
        return None
    depth = ARC_MELODY_DB if is_mel else ARC_OTHER_DB
    single = len({n[0] for n in ph}) == 1
    top = max(ph, key=lambda n: (n[2], -n[0]))
    frac = (top[0] - s) / length
    peak = top[0] if (0.3 <= frac <= 0.8 and not single) else s + (0.35 if single else 0.6) * length
    last = max(ph, key=lambda n: (n[0], n[1]))
    longs = [n for n in ph if n[1] - n[0] >= LONG_NOTE * tpb and n is not last]

    def env(t):
        if t <= peak:
            v = -depth * (1.0 - _ease((t - s) / max(1, peak - s)))
        else:
            v = -END_SHARE * depth * _ease((t - peak) / max(1, e - peak))
        if not single and last[1] - last[0] >= tpb:
            half = last[0] + 0.5 * (last[1] - last[0])
            if t > half:
                v -= TAPER_DB * ((t - half) / max(1, last[1] - half)) ** 2
        for n in longs:
            if n[0] <= t < n[1]:
                v -= SWELL_DB * (1.0 - _ease((t - n[0]) / (0.35 * (n[1] - n[0]))))
                break
        return max(MIN_DB, min(0.0, v))
    return env, s, e, depth


def apply(path, bar_starts=None, phrase_starts=None, melody=None):
    """path — оркестровый MIDI (меняется на месте). bar_starts, phrase_starts — в долях; melody = {дорожка: {начала в долях}}.
    Возвращает сведения для отчёта."""
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat
    bars = sorted({int(round(b * tpb)) for b in (bar_starts or [])})
    cuts = sorted({int(round(b * tpb)) for b in (phrase_starts or [])})
    beats_in_bar = {}
    for a, b in zip(bars, bars[1:]):
        beats_in_bar[a] = b
    info = {"phrases": 0, "velocity_changed": 0, "cc11_events": 0, "by_instrument": {}}
    violins = 0
    tol = max(1, tpb // 16)
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), "")
        chans = {m.channel for m in tr if m.type == "note_on"}
        if not chans or 9 in chans or any(k in name.lower() for k in SKIP_NAMES):
            continue
        key = RENAME.get(name, name)
        if key == "Violin":
            violins += 1
            key = "Violin I" if violins == 1 else "Violin II"
        ch = sorted(chans)[0]
        mel_ticks = sorted(int(round(x * tpb)) for x in (melody or {}).get(key, ()))
        import bisect

        def is_melody(t):
            i = bisect.bisect_left(mel_ticks, t - tol)
            return i < len(mel_ticks) and mel_ticks[i] <= t + tol

        absm, t = [], 0
        for m in tr:
            t += m.time
            absm.append([t, m])
        open_, notes = {}, []
        for item in absm:
            t, m = item
            if m.type == "note_on" and m.velocity > 0:
                open_.setdefault(m.note, []).append(item)
            elif m.type in ("note_off", "note_on") and open_.get(m.note):
                on = open_[m.note].pop(0)
                notes.append([on[0], t, m.note, on[1].velocity, is_melody(on[0]), on])
        notes.sort(key=lambda n: (n[0], -n[2]))
        if not notes:
            continue
        # прежняя кривая CC11 (ORCH_FOLLOW) как ступенчатая функция
        base_pts = [(t, m.value) for t, m in absm if m.type == "control_change" and m.control == 11]

        def base(t):
            v = 127
            for bt, bv in base_pts:
                if bt <= t:
                    v = bv
                else:
                    break
            return v

        segs, changed = [], 0
        for ph in _phrases(notes, tpb, cuts):
            n_mel = sum(1 for n in ph if n[4])
            is_mel = n_mel * 2 >= len(ph)
            sh = _shape(ph, tpb, is_mel)
            med = sorted(n[2] for n in ph)[len(ph) // 2]
            for n in ph:
                dv = 0.0
                if sh:
                    env, s, e, depth = sh
                    dv += ARC_VEL * (1.0 + 2.0 * max(-depth, env(n[0])) / depth)
                if is_mel:
                    dv += max(-HIGH_LOUD_MAX, min(HIGH_LOUD_MAX, HIGH_LOUD * (n[2] - med)))
                elif n[1] - n[0] < tpb and bars:
                    i = bisect.bisect_right(bars, n[0]) - 1
                    pos = n[0] - bars[max(0, i)]
                    if pos < tol:
                        dv += METRIC_VEL
                    elif pos % tpb >= tol and tpb - (pos % tpb) >= tol:
                        dv -= METRIC_VEL
                new = int(max(20, min(124, round(n[3] + dv))))
                if new != n[3]:
                    n[5][1] = n[5][1].copy(velocity=new)
                    changed += 1
            if sh:
                segs.append(sh)
                info["phrases"] += 1
        # новая кривая CC11: прежние точки + дуги
        absm = [it for it in absm if not (it[1].type == "control_change" and it[1].control == 11)]
        times = {bt for bt, _ in base_pts}
        step = max(1, tpb // GRID)
        for env, s, e, _ in segs:
            times.update(range(s, e + 1, step))
            times.add(e)
        cc, last = [], None
        segs.sort(key=lambda x: x[1])
        starts = [x[1] for x in segs]
        for t in sorted(times):
            db = 0.0
            i = bisect.bisect_right(starts, t) - 1
            if i >= 0 and t <= segs[i][2]:
                db = segs[i][0](t)
            v = int(max(20, min(127, round(base(t) * 10 ** (db / 40.0)))))
            if v != last:
                cc.append([t, mido.Message("control_change", channel=ch, control=11, value=v)])
                last = v
        merged = sorted([(t, 0, i, m) for i, (t, m) in enumerate(cc)] +
                        [(t, 1, i, m) for i, (t, m) in enumerate(absm)], key=lambda x: (x[0], x[1], x[2]))
        # конец дорожки должен остаться последним
        eot = [x for x in merged if x[3].type == "end_of_track"]
        merged = [x for x in merged if x[3].type != "end_of_track"]
        if eot:
            merged.append((max(eot[0][0], merged[-1][0] if merged else 0), 2, 0, eot[0][3]))
        new, prev = [], 0
        for t, _, _, m in merged:
            new.append(m.copy(time=t - prev)); prev = t
        tr[:] = new
        info["velocity_changed"] += changed
        info["cc11_events"] += len(cc)
        info["by_instrument"][key] = {"phrases": len(segs), "velocity_changed": changed, "cc11": len(cc)}
    mid.save(path)
    return info
