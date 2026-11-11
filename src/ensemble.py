"""Камерные ансамбли из фортепианной пьесы: дуэт, трио, квартет (2026-11-11, версия 1; на слух не проверено).

Запуск: python src/ensemble.py пьеса.mid выход_без_расширения quartet_string
Список составов: python src/ensemble.py --list

ЧТО ПОДТВЕРЖДЕНО ИСТОЧНИКАМИ
- Составы. Britannica, статья «quartet (music)»: струнный квартет — «two violins, viola, and cello»; фортепианный,
  флейтовый, гобойный квартеты — «usually a string trio combined with a fourth instrument». Britannica, «chamber
  music», раздел «Structural elements»: скрипичные и виолончельные сонаты с фортепиано, фортепианное трио
  (фортепиано, скрипка, виолончель). Струнное трио (скрипка, альт, виолончель) — следует из той же фразы про
  «string trio» и есть в базе мастеров (IRCAM). Дуэт скрипки и виолончели — есть в базе мастеров (5 пар).
  Флейта с фортепиано и кларнетовые составы — НЕ ПОДТВЕРЖДЕНО открытой страницей (Форсайт, «Orchestration», глава
  о кларнете, только называет «Beethoven's Clarinet Trio» без состава); состав «флейта и фортепиано» общеизвестен.
- Один исполнитель на партию: Britannica, «chamber music» («no more than one player to a part»). Отсюда: каждый
  голос ансамбля одноголосен, удвоений нет.
- Равноправие партий: там же («no instrument dominated the others», пианист — «an equal partner»). В версии 1
  НЕ СДЕЛАНО: мелодию ведёт верхний голос (см. «Что не сделано» в CLAUDE.md).

ЧТО ИЗМЕРЕНО У МАСТЕРОВ (база IRCAM, 19 выровненных камерных пар из 42; tools/ircam/chamber.py)
- ансамбль играет 99% нот рояля (медиана); нот у ансамбля столько же, сколько у рояля (отношение 1,01): удвоений нет;
- голоса не перекрещиваются (медиана 0% моментов); нижний звук у нижнего инструмента в 70% моментов;
- две ноты сразу у одного инструмента — редкость (медиана 0%), кроме дуэта скрипки и виолончели (38% у скрипки);
- каждый инструмент звучит около 72% времени.
Отсюда способ для составов без рояля: каждая нота рояля отдаётся одному голосу, голоса идут по высоте сверху вниз.

ЧТО ЭВРИСТИКА (в книгах не найдено): все числа ниже («штрафы», пороги), выбор октавы для мелодии, двойные ноты
струнных, а также весь способ для составов С РОЯЛЕМ: рояль играет всё, кроме мелодии; виолончель удваивает бас
длинными нотами; альт удваивает средний голос. В базе мастеров пар «рояль → ансамбль с роялем» нет.
"""
import bisect
import os
import sys

import mido

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# название голоса: (название дорожки MIDI, программа GM, ключ диапазона, струнный?, панорама)
INSTR = {
    "Violin": ("Violin", 40, "violin", True, 40), "Violin II": ("Violin", 40, "violin", True, 56),
    "Viola": ("Viola", 41, "viola", True, 76), "Cello": ("Violoncello", 42, "cello", True, 92),
    "Flute": ("Flute", 73, "flute", False, 44), "Oboe": ("Oboe", 68, "oboe", False, 44),
    "Clarinet": ("Clarinet", 71, "clarinet", False, 44),
}
RU = {"Violin": "скрипка", "Violin II": "скрипка II", "Viola": "альт", "Cello": "виолончель", "Flute": "флейта",
      "Oboe": "гобой", "Clarinet": "кларнет", "Piano": "фортепиано"}
# диапазоны (MIDI): скрипка, виолончель, флейта — Берлиоз (как validator.RANGES_BERLIOZ); альт, гобой, кларнет —
# таблица проекта, не подтверждено
RANGE = {"violin": (55, 96), "viola": (48, 84), "cello": (36, 76), "flute": (60, 96), "oboe": (58, 91), "clarinet": (50, 91)}
# удобная середина для мелодии (эвристика; у флейты — «нежная, невысокая», просьба пользователя 2026-11-07)
COMFORT = {"violin": (57, 88), "viola": (50, 76), "cello": (43, 69), "flute": (62, 86), "oboe": (60, 84), "clarinet": (52, 84)}

SRC_Q = "подтверждено: Britannica, «quartet (music)»"
SRC_C = "подтверждено: Britannica, «chamber music», Structural elements"
ENSEMBLES = {
    "duo_violin_piano": {"ru": "Дуэт: скрипка и фортепиано", "group": "Дуэт", "voices": ["Violin"], "piano": True, "source": SRC_C},
    "duo_cello_piano": {"ru": "Дуэт: виолончель и фортепиано", "group": "Дуэт", "voices": ["Cello"], "piano": True, "source": SRC_C},
    "duo_flute_piano": {"ru": "Дуэт: флейта и фортепиано", "group": "Дуэт", "voices": ["Flute"], "piano": True,
                        "source": "состав общеизвестен; открытой страницей не подтверждён"},
    "duo_violin_cello": {"ru": "Дуэт: скрипка и виолончель", "group": "Дуэт", "voices": ["Violin", "Cello"], "piano": False,
                         "source": "есть у мастеров: база IRCAM, 5 пар"},
    "trio_piano": {"ru": "Трио: скрипка, виолончель, фортепиано", "group": "Трио", "voices": ["Violin", "Cello"], "piano": True, "source": SRC_C},
    "trio_string": {"ru": "Трио: скрипка, альт, виолончель", "group": "Трио", "voices": ["Violin", "Viola", "Cello"], "piano": False,
                    "source": SRC_Q + " («string trio»); есть у мастеров: база IRCAM"},
    "quartet_string": {"ru": "Квартет: две скрипки, альт, виолончель", "group": "Квартет",
                       "voices": ["Violin", "Violin II", "Viola", "Cello"], "piano": False, "source": SRC_Q},
    "quartet_piano": {"ru": "Квартет: скрипка, альт, виолончель, фортепиано", "group": "Квартет",
                      "voices": ["Violin", "Viola", "Cello"], "piano": True, "source": SRC_Q},
    "quartet_flute": {"ru": "Квартет: флейта, скрипка, альт, виолончель", "group": "Квартет",
                      "voices": ["Flute", "Violin", "Viola", "Cello"], "piano": False, "source": SRC_Q},
    "quartet_oboe": {"ru": "Квартет: гобой, скрипка, альт, виолончель", "group": "Квартет",
                     "voices": ["Oboe", "Violin", "Viola", "Cello"], "piano": False, "source": SRC_Q},
}

# --- числа способа: всё эвристика ---
SKIP = 40.0          # нота рояля никому не досталась (дороже любого хода голоса)
SKIP_DUP = 2.0       # то же, но все голоса заняты и такой звук (в другой октаве) уже есть
OCT_PEN = 8.0        # ноту пришлось перенести на октаву (вне диапазона)
CROSS = 10.0         # голос оказался выше верхнего соседа или ниже нижнего
HOLD_PEN = 6.0       # прервана ещё звучащая нота (за каждую оставшуюся долю, не больше двух)
MEL_CUT = 30.0       # прервана нота мелодии
MEL_PIN = 1000.0     # нота мелодии ушла не в верхний голос
MEL_VEL, INNER_VEL = 8, -4             # мелодия чуть громче, средний голос чуть тише (сила нажатия берётся у пианиста)
BASS_TOP = 57        # бас виолончели в составах с роялем: не выше ля малой октавы
BASS_WIN = 0.75      # и ниже всех нот в окне ±0,75 доли (как в engine2)
BASS_HOLD_MAX = 4.0  # виолончель держит бас до следующего баса, но не дольше 4 долей
VIOLA_BAND = (53, 76)  # откуда альт берёт средний голос в фортепианном квартете
VIOLA_STEP = 0.5     # альт берёт новую ноту не чаще раза в полдоли
LEGATO_GAP = 0.5     # ORCH_LEGATO=1: как в src/smooth.py


def fit(p, key):
    lo, hi = RANGE[key]
    while p < lo: p += 12
    while p > hi: p -= 12
    return p


def read(path):
    """Ноты рояля в тиках: [{s, e, p, v, id}], служебные события (темп, размер, тональность), педаль, тиков на долю."""
    mid = mido.MidiFile(path)
    notes, meta, pedal = [], [], []
    for tr in mid.tracks:
        t, on = 0, {}
        for m in tr:
            t += m.time
            if m.is_meta:
                if m.type in ("set_tempo", "time_signature", "key_signature"): meta.append((t, m))
            elif m.type == "control_change" and m.control == 64:
                pedal.append((t, m.value))
            elif m.type == "note_on" and m.velocity > 0 and m.channel != 9:
                on.setdefault((m.channel, m.note), []).append((t, m.velocity))
            elif m.type in ("note_off", "note_on") and m.channel != 9 and on.get((m.channel, m.note)):
                s, v = on[(m.channel, m.note)].pop(0)
                if t > s: notes.append({"s": s, "e": t, "p": m.note, "v": v})
    best = {}
    for n in notes:                              # одна и та же нота в двух дорожках: оставляем длинную
        k = (n["s"], n["p"])
        if k not in best or n["e"] > best[k]["e"]: best[k] = n
    notes = sorted(best.values(), key=lambda n: (n["s"], -n["p"]))
    for i, n in enumerate(notes): n["id"] = i
    return notes, meta, pedal, mid.ticks_per_beat


def melody_ids(notes, tpb):
    import engine2
    alln = sorted((n["s"] / tpb, n["e"] / tpb, n["p"], 0) for n in notes)
    by = {(n["s"], n["p"]): n["id"] for n in notes}
    ids = set()
    for m in engine2.find_melody(alln):
        k = (int(round(m["offset"] * tpb)), m["pitch"])
        if k in by: ids.add(by[k])
    return ids


def melody_shift(notes, mel, key):
    """Одна октава на всю пьесу для мелодии верхнего голоса: чтобы больше нот легло в удобную середину."""
    ps = [n["p"] for n in notes if n["id"] in mel]
    if not ps: return 0
    lo, hi = COMFORT[key]
    best = None
    for sh in (0, 12, -12, 24, -24, 36, -36):
        bad = sum(1 for p in ps if not lo <= p + sh <= hi)
        cand = (bad, abs(sh))
        if best is None or cand < best[0]: best = (cand, sh)
    return best[1]


def _groups(notes, tpb):
    tol = max(1, tpb // 12)
    out, cur = [], []
    for n in notes:
        if cur and n["s"] - cur[0]["s"] > tol:
            out.append(cur); cur = []
        cur.append(n)
    if cur: out.append(cur)
    return out


def distribute(notes, voices, mel, tpb, shift0=0):
    """Составы без рояля: каждая нота рояля — одному голосу; голоса по высоте сверху вниз (voices: сверху вниз)."""
    K = len(voices)
    keys = [INSTR[v][2] for v in voices]
    strings = [INSTR[v][3] for v in voices]
    center = [sum(COMFORT[k]) / 2.0 for k in keys]
    st = [{"last": None, "cur": [], "notes": []} for _ in range(K)]
    stat = {"skipped": 0, "skipped_dup": 0, "double": 0, "octave": 0, "crossings": 0, "cut_notes": 0}

    def pitch_for(n, i):
        p = n["p"] + (shift0 if (i == 0 and n["id"] in mel) else 0)
        return fit(p, keys[i])

    for g in _groups(notes, tpb):
        on = g[0]["s"]
        g = sorted(g, key=lambda n: -n["p"])
        if len(g) > 8:                      # очень широкий аккорд: мелодия, бас и самые долгие
            keep = {g[0]["id"], g[-1]["id"]} | {n["id"] for n in g if n["id"] in mel}
            rest = sorted((n for n in g if n["id"] not in keep), key=lambda n: -(n["e"] - n["s"]))
            keep |= {n["id"] for n in rest[:8 - len(keep)]}
            stat["skipped"] += len(g) - len(keep)
            g = [n for n in g if n["id"] in keep]
        snd = []                            # что звучит у каждого голоса в этот момент
        for i in range(K):
            live = [c for c in st[i]["cur"] if c["e"] > on + tpb // 20]
            snd.append(live)
        best = [None, None]

        def cost_one(n, i):
            p = pitch_for(n, i)
            c = 0.0
            if n["id"] in mel and i != 0: c += MEL_PIN
            raw = n["p"] + (shift0 if (i == 0 and n["id"] in mel) else 0)
            if p != raw: c += OCT_PEN
            ref = st[i]["last"]
            c += min(24.0, abs(p - ref)) if ref is not None else 0.3 * abs(p - center[i])
            if snd[i]:
                rem = max(x["e"] - on for x in snd[i]) / float(tpb)
                c += HOLD_PEN * min(2.0, rem)
                if any(x.get("mel") for x in snd[i]) and n["id"] not in mel: c += MEL_CUT
            return c, p

        def rec(j, imin, acc, total):
            if best[0] is not None and total >= best[0]: return
            if j == len(g):
                used = {i for _, i, _ in acc}
                extra = 0.0
                pcs = {p % 12 for _, _, p in acc} | {x["p"] % 12 for i in range(K) if i not in used for x in snd[i]}
                for n in g:
                    if not any(a[0] is n for a in acc):
                        extra += SKIP_DUP if (len(used) == K and n["p"] % 12 in pcs) else SKIP
                for _, i, p in acc:                       # перекрещивание с тянущимися нотами других голосов
                    for k in range(K):
                        if k in used or not snd[k]: continue
                        q_hi = max(x["p"] for x in snd[k]); q_lo = min(x["p"] for x in snd[k])
                        if (k < i and p > q_hi) or (k > i and p < q_lo): extra += CROSS
                if best[0] is None or total + extra < best[0]:
                    best[0], best[1] = total + extra, list(acc)
                return
            n = g[j]
            for i in range(imin, K):
                c, p = cost_one(n, i)
                if acc and acc[-1][2] < p: c += CROSS      # голос ниже оказался бы выше соседа
                acc.append((n, i, p)); rec(j + 1, i + 1, acc, total + c); acc.pop()
            rec(j + 1, imin, acc, total)                   # нота никому (штраф считается в конце)

        rec(0, 0, [], 0.0)
        acc = best[1] or []
        used = {}
        for n, i, p in acc:
            for c in st[i]["cur"]:
                if c["e"] > on:
                    c["e"] = on; stat["cut_notes"] += 1
            st[i]["notes"] = [c for c in st[i]["notes"] if c["e"] > c["s"]]
            raw = n["p"] + (shift0 if (i == 0 and n["id"] in mel) else 0)
            if p != raw: stat["octave"] += 1
            new = {"s": n["s"], "e": n["e"], "p": p, "v": n["v"], "mel": n["id"] in mel, "src": n["id"]}
            st[i]["notes"].append(new); st[i]["cur"] = [new]; st[i]["last"] = p; used[i] = new
        for k in range(K):                                 # счёт перекрещиваний после раздачи
            pass
        taken = {id(a[0]) for a in acc}
        pcs = {x["p"] % 12 for i in used for x in [used[i]]}
        for n in g:
            if id(n) in taken: continue
            done = False
            for i in sorted(used, key=lambda i: abs(used[i]["p"] - n["p"])):
                if not strings[i] or len(st[i]["cur"]) != 1: continue
                p = fit(n["p"], keys[i])
                if len(used) == K and 3 <= abs(p - used[i]["p"]) <= 12 and p == n["p"]:
                    new = {"s": n["s"], "e": min(n["e"], used[i]["e"]) if used[i]["e"] > n["s"] else n["e"], "p": p,
                           "v": n["v"], "mel": False, "src": n["id"], "double": True}
                    st[i]["notes"].append(new); st[i]["cur"].append(new); stat["double"] += 1; done = True
                    break
            if not done:
                if n["p"] % 12 in pcs: stat["skipped_dup"] += 1
                else: stat["skipped"] += 1
        hi = None
        for i in range(K):
            live = [c for c in st[i]["cur"] if c["e"] > on]
            if not live: continue
            top = max(c["p"] for c in live)
            if hi is not None and top > hi: stat["crossings"] += 1
            hi = min(c["p"] for c in live) if hi is None else min(hi, min(c["p"] for c in live))
    return {v: st[i]["notes"] for i, v in enumerate(voices)}, stat


def with_piano(notes, voices, mel, tpb):
    """Составы с роялем: верхний инструмент — мелодия; рояль — всё остальное; виолончель и альт удваивают бас и середину."""
    out = {v: [] for v in voices}
    stat = {"octave": 0, "piano_notes": 0, "bass_notes": 0, "inner_notes": 0}
    lead = voices[0]
    key = INSTR[lead][2]
    sh = melody_shift(notes, mel, key)
    stat["melody_shift"] = sh
    for n in notes:
        if n["id"] in mel:
            p = fit(n["p"] + sh, key)
            if p != n["p"] + sh: stat["octave"] += 1
            out[lead].append({"s": n["s"], "e": n["e"], "p": p, "v": n["v"], "mel": True, "src": n["id"]})
    rest = [n for n in notes if n["id"] not in mel]
    stat["piano_notes"] = len(rest)
    starts = [n["s"] for n in rest]
    if "Cello" in voices[1:]:
        win = int(BASS_WIN * tpb)
        bass = []
        for n in rest:
            if n["p"] > BASS_TOP: continue
            a = bisect.bisect_left(starts, n["s"] - win); b = bisect.bisect_right(starts, n["s"] + win)
            if any(m["p"] < n["p"] for m in rest[a:b]): continue
            if any(m["p"] < n["p"] and m["s"] < n["s"] < m["e"] for m in rest[max(0, a - 40):a]): continue
            bass.append(n)
        for i, n in enumerate(bass):
            nxt = bass[i + 1]["s"] if i + 1 < len(bass) else n["e"]
            e = max(n["e"], min(nxt, n["s"] + int(BASS_HOLD_MAX * tpb)))
            if nxt > n["s"]: e = min(e, nxt)
            out["Cello"].append({"s": n["s"], "e": e, "p": fit(n["p"], "cello"), "v": n["v"], "mel": False, "src": n["id"]})
        stat["bass_notes"] = len(bass)
        bass_ids = {n["id"] for n in bass}
    else:
        bass_ids = set()
    if "Viola" in voices[1:]:
        last, cur_end, last_on = None, -1, -10 ** 9
        step = int(VIOLA_STEP * tpb)
        for g in _groups(rest, tpb):
            on = g[0]["s"]
            cand = [n for n in g if n["id"] not in bass_ids and VIOLA_BAND[0] <= n["p"] <= VIOLA_BAND[1]]
            if not cand or on - last_on < step: continue
            n = min(cand, key=lambda n: abs(n["p"] - last)) if last is not None else max(cand, key=lambda n: n["p"])
            if out["Viola"] and out["Viola"][-1]["e"] > on: out["Viola"][-1]["e"] = on
            out["Viola"].append({"s": n["s"], "e": n["e"], "p": n["p"], "v": max(20, n["v"] + INNER_VEL), "mel": False, "src": n["id"]})
            last, last_on = n["p"], on
        stat["inner_notes"] = len(out["Viola"])
    return out, rest, stat


def _sustain(seq, pedal, tpb):
    """У смычка и дыхания педали нет: нота, которую у рояля держала педаль, тянется до снятия педали
    (но не дольше, чем до следующей ноты той же партии). Педаль читается из файла (CC64)."""
    spans, down = [], None
    for t, val in sorted(pedal):
        if val >= 64 and down is None: down = t
        elif val < 64 and down is not None:
            spans.append((down, t)); down = None
    if not spans: return 0
    s0 = [a for a, _ in spans]
    starts = sorted({n["s"] for n in seq})
    nxt = dict(zip(starts, starts[1:]))
    k = 0
    for n in seq:
        i = bisect.bisect_right(s0, n["e"]) - 1
        if i < 0 or not (spans[i][0] <= n["e"] < spans[i][1]): continue
        target = spans[i][1]
        b = nxt.get(n["s"])
        if b is not None: target = min(target, b)
        if target > n["e"]:
            n["e"] = target; k += 1
    return k


def _legato(seq, tpb):
    if os.environ.get("ORCH_LEGATO", "").strip().lower() not in ("1", "true", "yes", "on"): return 0
    starts = sorted({n["s"] for n in seq})
    nxt = dict(zip(starts, starts[1:]))
    k = 0
    for n in seq:
        b = nxt.get(n["s"])
        if b is None: continue
        gap = b - n["e"]
        if 0 < gap <= LEGATO_GAP * tpb and gap <= n["e"] - n["s"]:
            n["e"] = b; k += 1
    return k


def _track(name, ch, program, pan, seq, extra=()):
    ev = []
    for n in seq:
        v = max(20, min(120, n["v"] + (MEL_VEL if n.get("mel") else 0)))
        ev.append((n["s"], 1, mido.Message("note_on", channel=ch, note=n["p"], velocity=v)))
        ev.append((n["e"], 0, mido.Message("note_off", channel=ch, note=n["p"], velocity=0)))
    for t, m in extra: ev.append((t, 2, m))
    ev.sort(key=lambda x: (x[0], x[1]))
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name=name, time=0))
    tr.append(mido.Message("program_change", channel=ch, program=program, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=10, value=pan, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=91, value=40, time=0))
    last = 0
    for t, _, m in ev:
        tr.append(m.copy(time=t - last)); last = t
    return tr


def arrange(in_path, out_stem, ensemble):
    """Пишет <out_stem>.mid и возвращает отчёт (словарь). ensemble — ключ из ENSEMBLES."""
    ens = ENSEMBLES[ensemble]
    notes, meta, pedal, tpb = read(in_path)
    if not notes: raise ValueError("в файле нет нот")
    mel = melody_ids(notes, tpb)
    voices = ens["voices"]
    if ens["piano"]:
        parts, piano, stat = with_piano(notes, voices, mel, tpb)
    else:
        sh = melody_shift(notes, mel, INSTR[voices[0]][2])
        parts, stat = distribute(notes, voices, mel, tpb, sh)
        stat["melody_shift"] = sh
        piano = None
    stat["pedal_sustained"] = sum(_sustain(parts[v], pedal, tpb) for v in voices)
    stat["legato_extended"] = sum(_legato(parts[v], tpb) for v in voices)
    mid = mido.MidiFile(ticks_per_beat=tpb)
    cond = mido.MidiTrack(); last = 0
    for t, m in sorted(meta, key=lambda x: x[0]):
        cond.append(m.copy(time=t - last)); last = t
    mid.tracks.append(cond)
    ch = 0
    for v in voices:
        name, prog, _, _, pan = INSTR[v]
        mid.tracks.append(_track(name, ch, prog, pan, parts[v])); ch += 1
    if piano is not None:
        ped = [(t, mido.Message("control_change", channel=ch, control=64, value=val)) for t, val in pedal]
        mid.tracks.append(_track("Piano", ch, 0, 64, [dict(n, mel=False) for n in piano], ped))
    mid.save(out_stem + ".mid")
    end = max(n["e"] for n in notes)
    rep = {"ensemble": ensemble, "name": ens["ru"], "source": ens["source"], "piano_notes": len(notes),
           "melody_notes": len(mel), "stat": stat, "parts": {}}
    played = set()
    for v in voices:
        seq = parts[v]
        played |= {n["src"] for n in seq}
        cov, lastt = 0, 0
        for n in sorted(seq, key=lambda n: n["s"]):
            s2 = max(n["s"], lastt)
            if n["e"] > s2: cov += n["e"] - s2; lastt = n["e"]
        rep["parts"][v] = {"ru": RU[v], "notes": len(seq), "low": min((n["p"] for n in seq), default=None),
                           "high": max((n["p"] for n in seq), default=None), "sounding_share": round(cov / float(end), 2)}
    if piano is not None:
        played |= {n["id"] for n in piano}
        rep["parts"]["Piano"] = {"ru": "фортепиано", "notes": len(piano)}
    rep["played_share"] = round(len(played) / float(len(notes)), 3)
    return rep


def text(rep):
    """Отчёт по-русски."""
    L = [rep["name"], "Состав: " + rep["source"] + ".",
         "Нот рояля сыграно: %.0f%% (у мастеров в базе IRCAM медиана 99%%)." % (100 * rep["played_share"])]
    for v, p in rep["parts"].items():
        if v == "Piano":
            L.append("  фортепиано: %d нот (всё, кроме мелодии)" % p["notes"])
        else:
            L.append("  %s: %d нот, звучит %.0f%% времени" % (p["ru"], p["notes"], 100 * p["sounding_share"]))
    s = rep["stat"]
    if "skipped" in s:
        L.append("Не досталось никому: %d нот (ещё %d — повторы того же звука в другой октаве); вторая нота у струнного: %d; "
                 "перенос на октаву: %d; перекрещиваний голосов: %d." % (s["skipped"], s["skipped_dup"], s["double"], s["octave"], s["crossings"]))
    else:
        L.append("Виолончель удваивает бас: %d нот; альт удваивает средний голос: %d нот; перенос на октаву: %d."
                 % (s.get("bass_notes", 0), s.get("inner_notes", 0), s["octave"]))
    if s.get("pedal_sustained"):
        L.append("Нот, которые у рояля держала педаль, продлено: %d (у смычка и дыхания педали нет)." % s["pedal_sustained"])
    if s.get("melody_shift"):
        L.append("Мелодия перенесена на %d окт. (%s), чтобы лечь в удобную середину инструмента."
                 % (abs(s["melody_shift"]) // 12, "вверх" if s["melody_shift"] > 0 else "вниз"))
    L.append("Статус: составы и «один исполнитель на партию» — по источникам; раздача нот — по замеру у мастеров (без рояля) "
             "и эвристика (с роялем). Программа считает, а не слушает.")
    return "\n".join(L)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        for k, e in ENSEMBLES.items(): print("%-18s %s  [%s]" % (k, e["ru"], e["source"]))
    else:
        print(text(arrange(sys.argv[1], sys.argv[2], sys.argv[3])))
