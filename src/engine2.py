"""
Движок 2 «переложение нота в ноту» (проба 2026-11-10, включается ORCH_ENGINE=2, по умолчанию выключен).

Зачем. Замер на базе IRCAM (Projective Orchestral Database, 39 выровненных пар Bouliane): у мастеров оркестр играет
в тот же момент 99% нот рояля (медиана; минимум 80%), ритм рояля сохраняется на 100% (минимум 86%), «придуманных»
начал нот в оркестре 3–8%. Старый движок вместо этого сочинял гармонию заново (бас и два голоса на каждую долю):
на живой записи Шопена оркестр играл 48% нот рояля, а 40% нот оркестра были придуманы; на прежних пьесах 67–92%.

Принцип (ИЗМЕРЕНО по базе): каждая нота рояля звучит у кого-то в свой момент и на своей высоте; оркестр добавляет
только удвоения и «педаль» — тянущиеся ноты (в тактах с арпеджио у мастеров рояль→оркестр в такте 9 инструментов,
из них 2 бегут и 5 держат; 43% длинных нот оркестра — удлинённые или добавленные ноты аккорда).

Что здесь ЭВРИСТИКА (в книгах и базе не найдено, пороги рабочие): как ноты делятся на мелодию, бас и сопровождение;
границы регистров (виолончель ниже C3, альт до E5, выше скрипка II); кто из духовых держит какую ноту; длина
«педали» без педали в файле (такт); число держащих (до трёх).

Мелодию по-прежнему раздаёт план (кто ведёт фразу); движок заменяет только сопровождение.
"""
import bisect, os

SHORT = 0.6          # эвристика: короче — «бегущая» нота
BASS_WIN = 0.75      # эвристика: бас — самая низкая нота в окне ±0,75 доли
BAND_CELLO = 48      # эвристика: ниже C3 бегущие ноты у виолончели
BAND_VIOLA = 77      # эвристика: до E5 у альта, выше — у второй скрипки
WIND_GAP = 0.25      # эвристика: духовой снимает ноту на четверть доли раньше (вдох)
MAX_HOLDERS = 3      # эвристика
STRINGS_HIGH_TO_LOW = ["Violin I", "Violin II", "Viola", "Cello"]
WINDS_FOR_CHORDS = ["Clarinet", "Oboe", "Flute", "Horn", "Bassoon"]
HOLD_BAND = {"Horn": (53, 69), "Bassoon": (41, 60), "Clarinet": (55, 74), "Violin II": (57, 76), "Oboe": (60, 79)}


def enabled():
    return os.environ.get("ORCH_ENGINE", "") == "2"


def read_pedal(path):
    """[(нажата, отпущена)] в долях из MIDI (CC64, порог 64). Нет педали или не MIDI -> []."""
    try:
        import mido
        m = mido.MidiFile(path)
    except Exception:
        return []
    ev, t = [], 0
    for x in mido.merge_tracks(m.tracks):
        t += x.time
        if x.type == "control_change" and x.control == 64:
            ev.append((t / m.ticks_per_beat, x.value >= 64))
    spans, down = [], None
    for tt, d in ev:
        if d and down is None:
            down = tt
        elif not d and down is not None:
            if tt - down > 0.1:
                spans.append((down, tt))
            down = None
    if down is not None:
        spans.append((down, t / m.ticks_per_beat))
    return spans


def find_melody(allnotes):
    """Мелодия: верхний голос. Нота — кандидат, если в момент начала над ней ничего не звучит (пальцами, без педали).
    Короткий кандидат принимается, только если он не ниже последней ноты мелодии больше чем на большую терцию
    (иначе это нота сопровождения, выглянувшая после снятой ноты мелодии). Эвристика."""
    by_start = sorted(allnotes)
    res, i, active, last = [], 0, [], None
    while i < len(by_start):
        j = i
        while j < len(by_start) and by_start[j][0] - by_start[i][0] < 1e-6:
            j += 1
        on = by_start[i][0]
        active = [(p, e) for p, e in active if e > on + 1e-6]
        top = max(by_start[i:j], key=lambda n: n[2])
        if not any(p > top[2] for p, e in active):
            dur = top[1] - top[0]
            ok = True
            if dur < SHORT and last is not None and on - last[1] < 4.0 and top[2] < last[2] - 4:
                ok = False
            if ok:
                res.append({"offset": top[0], "dur": dur, "pitch": top[2]})
                last = top
        active += [(n[2], n[1]) for n in by_start[i:j]]
        i = j
    return res


def _sound_end(end, spans, starts):
    """Когда нота перестаёт звучать с учётом педали."""
    k = bisect.bisect_right(starts, end) - 1
    if k >= 0 and spans[k][0] <= end < spans[k][1]:
        return spans[k][1]
    return end


def accompany(lines, notes, melody, plan, bars, fit, ranges, log, spans=None):
    """Заполняет lines сопровождением: каждая нота рояля, не вошедшая в мелодию, отдаётся одному инструменту."""
    starts = [b[0] for b in bars]
    mel_keys = {(round(m["offset"], 4), m["pitch"]) for m in melody}
    acc = sorted((n[0], n[1], n[2]) for n in notes if (round(n[0], 4), n[2]) not in mel_keys)
    spans = spans or []
    sp_starts = [s[0] for s in spans]
    st = {"notes": len(acc), "placed": 0, "dropped": 0, "bass": 0, "holds": 0, "modes": {}, "pedal_spans": len(spans)}
    if not acc:
        log["engine2"] = st
        return
    acc_on = [a[0] for a in acc]
    pitches = sorted(a[2] for a in acc)
    med = pitches[len(pitches) // 2]
    snd = [_sound_end(a[1], spans, sp_starts) for a in acc]
    # --- бас: самая низкая из звучащих (с педалью) и из начинающихся рядом; только нижняя половина регистра
    is_bass, sounding = [False] * len(acc), []
    for i, (s, e, p) in enumerate(acc):
        sounding = [(pp, ee) for pp, ee in sounding if ee > s + 1e-6]
        lo, hi = bisect.bisect_left(acc_on, s - BASS_WIN), bisect.bisect_right(acc_on, s + BASS_WIN)
        near = min(a[2] for a in acc[lo:hi])
        held = min((pp for pp, ee in sounding), default=999)
        if p <= near and p < held and p <= med:
            is_bass[i] = True
        sounding.append((p, snd[i]))
    bass_idx = [i for i, b in enumerate(is_bass) if b]
    bass_on = [acc[i][0] for i in bass_idx]

    def bar_i(off):
        return max(0, bisect.bisect_right(starts, off + 1e-9) - 1)

    def rng(name):
        return ranges[name]

    def place(name, off, dur, pitch, role):
        f = fit(pitch, name)
        if f is None or dur <= 1e-6:
            return False
        lines[name].append([off, dur, f, role])
        return True

    mel_on = [m["offset"] for m in melody]

    def melody_at(t):
        k = bisect.bisect_right(mel_on, t + 1e-6) - 1
        if k >= 0 and melody[k]["offset"] + melody[k]["dur"] > t - 1.0:
            return melody[k]["pitch"]
        return None

    for ph in plan["phrases"]:
        a_, b_ = ph["bars"]
        t0 = starts[a_ - 1]
        t1 = starts[b_] if b_ < len(starts) else starts[-1] + bars[-1][1] + 1e6
        idx = [i for i in range(bisect.bisect_left(acc_on, t0 - 1e-6), bisect.bisect_left(acc_on, t1 - 1e-6))]
        if not idx:
            continue
        busy = {spec[0] for spec in ph.get("melody", [])}
        free = [n for n in lines if n not in busy]
        rest = [i for i in idx if not is_bass[i]]
        groups = []
        for i in rest:
            if groups and acc[i][0] - acc[groups[-1][0]][0] < 0.05:
                groups[-1].append(i)
            else:
                groups.append([i])
        per_on = len(rest) / max(1, len(groups))
        short = sum(1 for i in rest if acc[i][1] - acc[i][0] < SHORT) / max(1, len(rest))
        mode = "figure" if rest and per_on < 1.4 and short >= 0.5 else "chords"
        st["modes"]["%d-%d" % (a_, b_)] = mode
        # --- бас: виолончель играет как написано, контрабас держит до следующего баса (но не дольше педали)
        bass_lit = next((n for n in ("Cello", "Bassoon", "Double Bass") if n in free), None)
        bass_hold = "Double Bass" if "Double Bass" in free and bass_lit != "Double Bass" else None
        for i in idx:
            if not is_bass[i]:
                continue
            s, e, p = acc[i]
            ok = bool(bass_lit) and place(bass_lit, s, e - s, p, "bass")
            if bass_hold:
                k = bisect.bisect_right(bass_on, s + 1e-6)
                nxt = bass_on[k] if k < len(bass_on) else snd[i]
                place(bass_hold, s, max(e, min(nxt, snd[i], s + 8.0)) - s, p, "bass")
                ok = True
            st["bass"] += 1
            st["placed" if ok else "dropped"] += 1
        used = {bass_lit, bass_hold}
        if mode == "figure":
            strings = [n for n in STRINGS_HIGH_TO_LOW if n in free]
            winds = [n for n in ("Clarinet", "Bassoon", "Flute", "Oboe") if n in free and n != bass_lit]
            # один «бегун» на фразу: струнный, в чей диапазон ложится не меньше 85% бегущих нот (эвристика);
            # у мастеров бегущая линия на 82% остаётся у одного инструмента (медиана 11 пар рояль->оркестр)
            cover = {n: sum(1 for i in rest if rng(n)[0] <= acc[i][2] <= rng(n)[1]) / len(rest) for n in strings}
            primary = next((n for n in ("Viola", "Cello", "Violin II") if cover.get(n, 0) >= 0.85), None)
            st.setdefault("runner", {})["%d-%d" % (a_, b_)] = primary
            for i in rest:
                s, e, p = acc[i]
                home = "Cello" if p < BAND_CELLO else ("Viola" if p < BAND_VIOLA else "Violin II")
                order = ([primary] if primary else []) + [home] + [n for n in ("Viola", "Cello", "Violin II", "Violin I") if n != home]
                done = False
                for n in order:
                    if n in strings and rng(n)[0] <= p <= rng(n)[1]:
                        done = place(n, s, e - s, p, "figuration"); used.add(n)
                        break
                if not done:
                    for n in winds:
                        if rng(n)[0] <= p <= rng(n)[1]:
                            done = place(n, s, e - s, p, "figuration"); used.add(n)
                            break
                st["placed" if done else "dropped"] += 1
            # --- «педаль»: духовые держат ноты аккорда, пока звучит педаль (нет педали в файле — такт)
            holders = [n for n in ("Horn", "Bassoon", "Violin II", "Clarinet", "Oboe") if n in free and n not in used][:MAX_HOLDERS]
            if spans:
                regions = [(max(s, t0), min(e, t1)) for s, e in spans if e > t0 and s < t1]
            else:
                regions = [(starts[b], starts[b] + bars[b][1]) for b in range(a_ - 1, min(b_, len(bars)))]
            for r0, r1 in regions:
                if r1 - r0 < 1.0:
                    continue
                inr = [acc[i] for i in idx if r0 - 1e-6 <= acc[i][0] < r1 - 1e-6]
                if not inr:
                    continue
                w, first, real = {}, {}, {}
                for s, e, p in inr:
                    pc = p % 12
                    w[pc] = w.get(pc, 0.0) + (e - s)
                    first.setdefault(pc, s)
                    real.setdefault(pc, []).append(p)
                bass_pc = min(inr, key=lambda x: x[2])[2] % 12
                ranked = [pc for pc in sorted(w, key=lambda k: -w[k]) if pc != bass_pc]
                taken = set()
                for h in holders:
                    pc = bass_pc if h == "Bassoon" else next((x for x in ranked if x not in taken), None)
                    if pc is None:
                        continue
                    taken.add(pc)
                    start = first[pc]
                    end = r1 - (WIND_GAP if h != "Violin II" else 0.0)
                    if start - r0 > 0.6 * (r1 - r0) or end - start < 1.0:
                        continue
                    lo, hi = HOLD_BAND[h]
                    cands = [q for q in range(lo, hi + 1) if q % 12 == pc]
                    if not cands:
                        continue
                    target = sum(real[pc]) / len(real[pc])
                    q = min(cands, key=lambda c: abs(c - target))
                    mp = melody_at(start)
                    while mp is not None and q >= mp and q - 12 >= rng(h)[0]:
                        q -= 12
                    if place(h, start, end - start, q, "inner1" if h in ("Horn", "Violin II") else "inner2"):
                        st["holds"] += 1
        else:
            order = [n for n in STRINGS_HIGH_TO_LOW + WINDS_FOR_CHORDS if n in free and n != bass_lit and n != bass_hold]
            if bass_lit == "Cello" and "Cello" in free:
                order.append("Cello")          # в аккорде без баса виолончель может взять нижний голос
            for g in groups:
                took = set()
                for i in sorted(g, key=lambda k: -acc[k][2]):
                    s, e, p = acc[i]
                    done = False
                    for n in order:
                        if n in took or not (rng(n)[0] <= p <= rng(n)[1]):
                            continue
                        if n == "Cello" and any(is_bass[k] and abs(acc[k][0] - s) < 0.05 for k in idx):
                            continue
                        done = place(n, s, e - s, p, "inner1" if n in STRINGS_HIGH_TO_LOW else "inner2")
                        took.add(n)
                        break
                    st["placed" if done else "dropped"] += 1
    log["engine2"] = st
