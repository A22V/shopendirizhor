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
import collections
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
VIOLIN_BAND = (55, 79)  # то же для скрипки, когда мелодию ведёт не она (только по плану)
SING_GAP = 1.0       # связная игра: нота тянется до следующей ноты той же партии, если пауза не длиннее доли
SING_BASS = 4.0      # ... у нижнего голоса — до следующего баса, если он не дальше 4 долей (как BASS_HOLD_MAX)
LEAD_MIN_BARS = 2    # план: ведущий держит мелодию не меньше двух тактов (у мастеров кусок — медиана 2,8 такта)
LEAD_FIT = 0.9       # план: ведущему (не верхнему) должны быть по диапазону не меньше 90% нот мелодии фразы
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


MONO_STRUM = 0.15    # мелодия одноголосна: две ноты «мелодии» ближе 0,15 доли — это перебор аккорда (рояльный свиток, арпеджио)


def mono_melody(notes, mel, tpb):
    """Мелодия для смычка и дыхания одноголосна (mono=True, по выбору, эвристика): если две ноты «мелодии» начались
    ближе MONO_STRUM доли (аккорд, сыгранный чуть вразнобой, как на рояльных свитках), мелодией остаётся верхняя,
    нижняя уходит в сопровождение (она всё равно звучит, у рояля или у другого инструмента). Возвращает новое множество."""
    ms = sorted((n for n in notes if n["id"] in mel), key=lambda n: (n["s"], -n["p"]))
    keep, win = set(), MONO_STRUM * tpb
    i = 0
    while i < len(ms):
        j = i
        while j + 1 < len(ms) and ms[j + 1]["s"] - ms[j]["s"] < win: j += 1
        keep.add(max(ms[i:j + 1], key=lambda n: n["p"])["id"])
        i = j + 1
    return keep


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


def distribute(notes, voices, mel, tpb, shift0=0, lead_at=None):
    """Составы без рояля: каждая нота рояля — одному голосу; голоса по высоте сверху вниз (voices: сверху вниз).
    lead_at(тик) -> номер голоса, который ведёт мелодию (по плану); без плана ведёт верхний голос (0).
    Ведущий не верхний голос играет мелодию на её высоте (без переноса), остальные идут под ним по порядку."""
    K = len(voices)
    keys = [INSTR[v][2] for v in voices]
    strings = [INSTR[v][3] for v in voices]
    center = [sum(COMFORT[k]) / 2.0 for k in keys]
    st = [{"last": None, "cur": [], "notes": []} for _ in range(K)]
    stat = {"skipped": 0, "skipped_dup": 0, "double": 0, "octave": 0, "crossings": 0, "cut_notes": 0}

    cur_lead = [0]

    def raw_of(n, i):
        return n["p"] + (shift0 if (i == 0 and cur_lead[0] == 0 and n["id"] in mel) else 0)

    def pitch_for(n, i):
        return fit(raw_of(n, i), keys[i])

    for g in _groups(notes, tpb):
        on = g[0]["s"]
        lead = lead_at(on) if lead_at else 0
        cur_lead[0] = lead
        ordv = [lead] + [i for i in range(K) if i != lead]      # порядок голосов сверху вниз в этот момент
        rank = {v: r for r, v in enumerate(ordv)}
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
            if n["id"] in mel and i != lead: c += MEL_PIN
            if p != raw_of(n, i): c += OCT_PEN
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
                        if (rank[k] < rank[i] and p > q_hi) or (rank[k] > rank[i] and p < q_lo): extra += CROSS
                if best[0] is None or total + extra < best[0]:
                    best[0], best[1] = total + extra, list(acc)
                return
            n = g[j]
            for r in range(imin, K):
                i = ordv[r]
                c, p = cost_one(n, i)
                if acc and acc[-1][2] < p: c += CROSS      # голос ниже оказался бы выше соседа
                acc.append((n, i, p)); rec(j + 1, r + 1, acc, total + c); acc.pop()
            rec(j + 1, imin, acc, total)                   # нота никому (штраф считается в конце)

        rec(0, 0, [], 0.0)
        acc = best[1] or []
        used = {}
        for n, i, p in acc:
            for c in st[i]["cur"]:
                if c["e"] > on:
                    c["e"] = on; stat["cut_notes"] += 1
            st[i]["notes"] = [c for c in st[i]["notes"] if c["e"] > c["s"]]
            if p != raw_of(n, i): stat["octave"] += 1
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
        for i in ordv:
            live = [c for c in st[i]["cur"] if c["e"] > on]
            if not live: continue
            top = max(c["p"] for c in live)
            if hi is not None and top > hi: stat["crossings"] += 1
            hi = min(c["p"] for c in live) if hi is None else min(hi, min(c["p"] for c in live))
    return {v: st[i]["notes"] for i, v in enumerate(voices)}, stat


def with_piano(notes, voices, mel, tpb, lead_at=None, mono=False):
    """Составы с роялем: верхний инструмент — мелодия; рояль — всё остальное; виолончель и альт удваивают бас и середину.
    lead_at(тик) -> название ведущего по плану ("Piano" — мелодию играет сам рояль). Кто не ведёт, тот сопровождает:
    виолончель — бас, альт — средний голос, скрипка — средний голос, если альта нет (эвристика); духовой молчит."""
    out = {v: [] for v in voices}
    stat = {"octave": 0, "piano_notes": 0, "bass_notes": 0, "inner_notes": 0}
    lead = voices[0]
    key = INSTR[lead][2]
    sh = melody_shift(notes, mel, key)
    stat["melody_shift"] = sh
    who = (lambda t: lead_at(t)) if lead_at else (lambda t: lead)
    piano_mel = set()
    for n in notes:
        if n["id"] in mel:
            w = who(n["s"])
            if w == "Piano":
                piano_mel.add(n["id"]); continue
            raw = n["p"] + (sh if w == lead else 0)
            p = fit(raw, INSTR[w][2])
            if p != raw: stat["octave"] += 1
            out[w].append({"s": n["s"], "e": n["e"], "p": p, "v": n["v"], "mel": True, "src": n["id"]})
    rest = [n for n in notes if n["id"] not in mel or n["id"] in piano_mel]
    stat["piano_notes"] = len(rest)
    stat["_piano_mel"] = piano_mel
    starts = [n["s"] for n in rest]
    if "Cello" in voices[1:] or (lead_at and "Cello" in voices):
        win = int(BASS_WIN * tpb)
        bass = []
        for n in rest:
            if n["p"] > BASS_TOP or n["id"] in piano_mel or who(n["s"]) == "Cello": continue
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
    inner = []
    if "Viola" in voices[1:]: inner.append(("Viola", VIOLA_BAND))
    elif lead_at and "Violin" in voices: inner.append(("Violin", VIOLIN_BAND))
    for name, band in inner:
        last, last_on, seq = None, -10 ** 9, []
        step = int(VIOLA_STEP * tpb)
        for g in _groups(rest, tpb):
            on = g[0]["s"]
            if who(on) == name:
                last = None; continue
            cand = [n for n in g if n["id"] not in bass_ids and n["id"] not in piano_mel and band[0] <= n["p"] <= band[1]]
            if not cand or on - last_on < step: continue
            n = min(cand, key=lambda n: abs(n["p"] - last)) if last is not None else max(cand, key=lambda n: n["p"])
            if seq and seq[-1]["e"] > on: seq[-1]["e"] = on
            seq.append({"s": n["s"], "e": n["e"], "p": n["p"], "v": max(20, n["v"] + INNER_VEL), "mel": False, "src": n["id"]})
            last, last_on = n["p"], on
        out[name] += seq
        stat["inner_notes"] += len(seq)
    if lead_at or mono:                          # у партии не больше одной ноты сразу (стыки ведущих, одноголосная мелодия)
        for v in voices:
            seq = sorted(out[v], key=lambda n: (n["s"], -n["p"]))
            for a, b in zip(seq, seq[1:]):
                if a["e"] > b["s"]: a["e"] = b["s"]
            out[v] = [n for n in seq if n["e"] > n["s"]]
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


def _sing(parts, voices, notes, tpb, when, bass_voice=None):
    """Связная игра (legato) во фразах, где when(тик) истинно: нота тянется до следующей ноты той же партии, если
    пауза не длиннее доли (у нижнего голоса без рояля — до следующего баса, не дальше 4 долей). Высоты и начала нот
    не меняются. Защита: нота не тянется дальше момента, где рояль берёт звук на полутон выше или ниже неё
    (иначе вышла бы резкая секунда, которой у рояля нет). Числа — эвристика."""
    on = sorted((n["s"], n["p"] % 12) for n in notes)
    t_on = [a for a, _ in on]
    k = stopped = 0
    for v in voices:
        seq = parts[v]
        starts = sorted({n["s"] for n in seq})
        nxt = dict(zip(starts, starts[1:]))
        lim = (SING_BASS if v == bass_voice else SING_GAP) * tpb
        for n in seq:
            b = nxt.get(n["s"])
            if b is None or not when(n["s"]): continue
            gap = b - n["e"]
            if gap <= 0 or gap > lim: continue
            target, pc = b, n["p"] % 12
            for j in range(bisect.bisect_right(t_on, n["e"]), bisect.bisect_left(t_on, b)):
                if (on[j][1] - pc) % 12 in (1, 11):
                    target = on[j][0]; stopped += 1; break
            if target > n["e"]:
                n["e"] = target; k += 1
    return k, stopped


# ---------------------------------------------------------------------------------------------------------------
# План ансамбля от модели (DeepSeek и др.): кто ведёт мелодию в каждой фразе и играть ли фразу связно.
# Ноты модель не пишет: раздаёт их программа. Что сказано модели и откуда это взято:
# - верхний инструмент ведёт большую часть пьесы, второй берёт мелодию целыми фразами, нижний почти никогда;
#   мелодия у другого инструмента звучит на своей высоте, без переноса на октаву: ИЗМЕРЕНО по базе IRCAM
#   (tools/ircam/chamber_lead.py, 18 выровненных камерных пар, из них 12 — медные квартеты: верхняя дорожка ведёт
#   72% нот мелодии (25–75%: 65–89), вторая 11%, нижняя 0%; в другой октаве 0–3%; кусок без смены ведущего —
#   медиана 2,8 такта, смена раз в 4,7 такта). Выборка мала и однобока: ориентир, не закон;
# - «ни один инструмент не главенствует», пианист — «равный партнёр»: Britannica, «chamber music» (подтверждено);
# - передавать мелодию на повторе темы, связно/отрывисто по характеру фразы: ЭВРИСТИКА (в книгах проекта не найдено).
# ---------------------------------------------------------------------------------------------------------------
def bar_table(meta, end, tpb):
    """Начала тактов в тиках по размерам из файла (без размера — 4/4)."""
    ts = sorted((t, m.numerator, m.denominator) for t, m in meta if m.type == "time_signature")
    if not ts or ts[0][0] > 0: ts.insert(0, (0, 4, 4))
    bars, t, i = [], 0, 0
    while t < end:
        while i + 1 < len(ts) and ts[i + 1][0] <= t: i += 1
        ln = max(1, int(round(tpb * 4.0 * ts[i][1] / ts[i][2])))
        bars.append(t); t += ln
    return bars or [0]


def _bar_of(bars, t):
    return max(1, bisect.bisect_right(bars, t))


def describe(notes, mel, bars, tpb, ensemble):
    """Короткое описание пьесы для модели (не все ноты): по тактам мелодия, нижний звук, число нот сопровождения."""
    ens = ENSEMBLES[ensemble]
    names = list(ens["voices"]) + (["Piano"] if ens["piano"] else [])
    per = {}
    for n in notes:
        d = per.setdefault(_bar_of(bars, n["s"]), {"mel": [], "acc": 0, "low": 127, "short": 0, "vel": []})
        if n["id"] in mel: d["mel"].append(n["p"])
        else: d["acc"] += 1
        d["low"] = min(d["low"], n["p"]); d["vel"].append(n["v"])
        if n["e"] - n["s"] < tpb // 2: d["short"] += 1
    L = ["Ensemble (top to bottom): " + ", ".join(names),
         "Ranges (MIDI): " + ", ".join("%s %d-%d" % (v, RANGE[INSTR[v][2]][0], RANGE[INSTR[v][2]][1]) for v in ens["voices"]),
         "Bars: %d" % len(bars),
         "Per bar: melody pitches (MIDI) | lowest note | accompaniment notes | short notes (shorter than half a beat) | loudness 1-127"]
    for b in range(1, len(bars) + 1):
        d = per.get(b)
        if not d: L.append("  %d: (rest)" % b); continue
        L.append("  %d: %s | %d | %d | %d | %d" % (b, d["mel"][:12], d["low"], d["acc"], d["short"], round(sum(d["vel"]) / len(d["vel"]))))
    L.append('Answer format: {"phrases":[{"bars":[1,8],"lead":"%s","articulation":"legato","why":"одно предложение по-русски"}]}' % names[0])
    L.append('lead is one of: %s. articulation is "legato" or "as_written".' % ", ".join('"%s"' % x for x in names))
    return "\n".join(L)


def system_text(ensemble):
    ens = ENSEMBLES[ensemble]
    t = ("You plan a chamber arrangement of a piano piece. You do NOT write notes: the program gives every note of the "
         "piano to exactly one instrument. Phrase by phrase you decide (a) which instrument LEADS, i.e. plays the melody, "
         "and (b) whether the phrase is played legato. Follow what the masters do. "
         "(1) Measured on chamber transcriptions by masters: the top instrument leads most of the piece (about 70 percent "
         "of the melody), the second instrument takes the melody for whole phrases (10 to 30 percent), the lowest instrument "
         "leads rarely. (2) Another instrument plays the melody at its written pitch, never transposed: give the lead to a "
         "lower instrument only if the melody of that phrase lies inside its range. (3) Change the leader only at a phrase "
         "border (after a long note or a rest of the melody), never in the middle of a musical thought. A leader keeps the "
         "melody for at least 2 bars, usually 4 to 8. A repeat of a theme is a good place to let another instrument answer: "
         "chamber music is a conversation of equal partners, no instrument dominates all the time, but do not change the "
         "leader in every phrase. (4) articulation: \"legato\" for singing, lyrical phrases (every part holds its note "
         "until its next note); \"as_written\" for dance-like, detached or staccato passages and for fast runs. "
         "(5) Phrases cover every bar from 1 to N, in order, without gaps or overlaps. ")
    if ens["piano"]:
        t += ("(6) The piano is an equal partner: lead \"Piano\" means the piano plays the melody itself and the other "
              "instruments accompany (cello doubles the bass, viola or violin doubles a middle voice). Give the piano the "
              "lead in some phrases, for example a first statement or a quiet answer, not in most of the piece. ")
    return t + "Answer with JSON only."


def check_plan(plan, ensemble, notes, mel, bars):
    """Проверка плана модели. Возвращает список замечаний по-английски (уходят модели на исправление)."""
    ens = ENSEMBLES[ensemble]
    names = list(ens["voices"]) + (["Piano"] if ens["piano"] else [])
    N = len(bars)
    ph = plan.get("phrases") if isinstance(plan, dict) else None
    if not isinstance(ph, list) or not ph: return ["plan has no phrases list"]
    problems, want = [], 1
    by_bar = {}
    for n in notes:
        if n["id"] in mel: by_bar.setdefault(_bar_of(bars, n["s"]), []).append(n["p"])
    for x in ph:
        try:
            a, b = int(x["bars"][0]), int(x["bars"][1])
        except Exception:
            return ["every phrase needs bars [first, last]"]
        if a != want or b < a or b > N:
            problems.append("phrase bars %s: phrases must go in order from bar 1 to bar %d without gaps or overlaps (expected a phrase starting at bar %d)" % ([a, b], N, want))
        want = b + 1
        if x.get("lead") not in names:
            problems.append("bars %s: lead %r is not one of %s" % ([a, b], x.get("lead"), names)); continue
        if x.get("articulation", "as_written") not in ("legato", "as_written"):
            problems.append("bars %s: articulation must be legato or as_written" % [a, b])
        ld = x["lead"]
        if ld != "Piano" and ld != ens["voices"][0]:
            lo, hi = RANGE[INSTR[ld][2]]
            ps = [p for k in range(a, b + 1) for p in by_bar.get(k, [])]
            if ps and sum(1 for p in ps if lo <= p <= hi) < LEAD_FIT * len(ps):
                problems.append("bars %s: the melody (MIDI %d-%d) does not fit the range of %s (%d-%d) at written pitch; choose another lead"
                                % ([a, b], min(ps), max(ps), ld, lo, hi))
    if want != N + 1 and not problems:
        problems.append("phrases end at bar %d but the piece has %d bars" % (want - 1, N))
    if not problems:
        runs = []
        for x in ph:
            if runs and runs[-1][0] == x["lead"]: runs[-1][2] = x["bars"][1]
            else: runs.append([x["lead"], x["bars"][0], x["bars"][1]])
        for ld, a, b in runs:
            if b - a + 1 < LEAD_MIN_BARS and len(runs) > 1:
                problems.append("bars %s: %s leads for less than %d bars; a leader must keep the melody for a whole phrase" % ([a, b], ld, LEAD_MIN_BARS))
    return problems


def _switch_tick(notes, mel, t_b, bar_len):
    """Где передать мелодию рядом с тактовой чертой t_b: на первой ноте после долгой ноты или паузы (конец мысли),
    в пределах такта до и после черты. Та же мера, что в texture_fix._switch_beat («Болеро»): эвристика."""
    m = [n for n in notes if n["id"] in mel and t_b - 2 * bar_len <= n["s"] <= t_b + bar_len]
    best = (None, t_b)
    for a, b in zip(m, m[1:]):
        if not (t_b - bar_len <= b["s"] <= t_b + bar_len): continue
        gap = max(0, b["s"] - a["e"])
        score = (a["e"] - a["s"]) + 3.0 * gap - 0.5 * abs(b["s"] - t_b)
        if best[0] is None or score > best[0]: best = (score, b["s"])
    return best[1]


def segments(plan, notes, mel, bars):
    """План -> (lead_name_at(тик), legato_at(тик), список передач мелодии [(такт, название)])."""
    ph = plan["phrases"]
    lt, ln, at, al, hand = [], [], [], [], []
    for i, x in enumerate(ph):
        t = bars[x["bars"][0] - 1]
        at.append(t); al.append(x.get("articulation") == "legato")
        if not ln or ln[-1] != x["lead"]:
            if ln:
                nxt = bars[x["bars"][0]] if x["bars"][0] < len(bars) else t + (t - bars[x["bars"][0] - 2])
                t = _switch_tick(notes, mel, t, max(1, nxt - t))
            lt.append(t); ln.append(x["lead"]); hand.append((x["bars"][0], x["lead"]))
    lt[0] = 0
    return (lambda t: ln[max(0, bisect.bisect_right(lt, t) - 1)]), (lambda t: al[max(0, bisect.bisect_right(at, t) - 1)]), hand


def plan_with_model(in_path, ensemble, provider, model, api_key, call=None, max_rounds=3):
    """Спрашивает модель, проверяет план, возвращает замечания модели на исправление (до 3 кругов).
    -> (план или None, журнал). План None = модель не справилась или сервис не ответил: ансамбль делается без плана,
    причина в журнале (ничего не прячем)."""
    import llm_planner
    call = call or llm_planner.call_model
    notes, meta, pedal, tpb = read(in_path)
    mel = melody_ids(notes, tpb)
    bars = bar_table(meta, max(n["e"] for n in notes), tpb)
    desc = describe(notes, mel, bars, tpb, ensemble)
    log = {"provider": provider, "model_requested": model, "rounds": [], "used": False}
    user = desc
    n0 = len(llm_planner.MODELS_SERVED)
    for r in range(1, max_rounds + 1):
        try:
            txt = call(provider, model, api_key, system_text(ensemble), user)
        except Exception as e:
            log["error"] = "сервис модели не ответил: %s" % e
            break
        try:
            plan = llm_planner.parse_plan(txt)
            problems = check_plan(plan, ensemble, notes, mel, bars)
        except Exception as e:
            plan, problems = None, ["answer is not valid JSON: %s" % e]
        log["rounds"].append({"round": r, "problems": problems})
        if not problems:
            log["used"] = True
            log["model_served_by_api"] = sorted(set(llm_planner.MODELS_SERVED[n0:]))
            return plan, log
        user = desc + "\n\nYour previous plan had these problems, fix them and answer with JSON only:\n- " + "\n- ".join(problems)
    log["model_served_by_api"] = sorted(set(llm_planner.MODELS_SERVED[n0:]))
    log.setdefault("error", "модель за %d попытки не дала годного плана" % max_rounds)
    return None, log


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


def arrange(in_path, out_stem, ensemble, plan=None, legato=False, mono=False):
    """Пишет <out_stem>.mid и возвращает отчёт (словарь). ensemble — ключ из ENSEMBLES.
    plan — проверенный план модели (кто ведёт мелодию по фразам, где legato) или None: тогда как в версии 1.
    legato=True — связная игра во всей пьесе (без плана) или там, где так решил план.
    mono=True — мелодия одноголосна: перебор аккорда не считается мелодией, ноты мелодии не налезают друг на друга."""
    ens = ENSEMBLES[ensemble]
    notes, meta, pedal, tpb = read(in_path)
    if not notes: raise ValueError("в файле нет нот")
    mel = melody_ids(notes, tpb)
    if mono:
        n_mel = len(mel); mel = mono_melody(notes, mel, tpb)
    voices = ens["voices"]
    lead_name = legato_at = hand = None
    if plan:
        bars = bar_table(meta, max(n["e"] for n in notes), tpb)
        lead_name, legato_at, hand = segments(plan, notes, mel, bars)
    elif legato:
        legato_at = lambda t: True
    if ens["piano"]:
        parts, piano, stat = with_piano(notes, voices, mel, tpb, lead_name, mono)
    else:
        sh = melody_shift(notes, mel, INSTR[voices[0]][2])
        parts, stat = distribute(notes, voices, mel, tpb, sh, (lambda t: voices.index(lead_name(t))) if lead_name else None)
        stat["melody_shift"] = sh
        piano = None
    piano_mel = stat.pop("_piano_mel", set())
    if mono: stat["mono_melody_dropped"] = n_mel - len(mel)
    stat["pedal_sustained"] = sum(_sustain(parts[v], pedal, tpb) for v in voices)
    stat["legato_extended"] = sum(_legato(parts[v], tpb) for v in voices)
    if legato_at:
        stat["sing_extended"], stat["sing_stopped"] = _sing(parts, voices, notes, tpb, legato_at,
                                                            None if ens["piano"] else voices[-1])
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
        mid.tracks.append(_track("Piano", ch, 0, 64, [dict(n, mel=n["id"] in piano_mel) for n in piano], ped))
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
    if plan:
        tot = collections.Counter()
        for n in notes:
            if n["id"] in mel: tot[lead_name(n["s"])] += 1
        rep["plan"] = {"phrases": [{"bars": list(x["bars"]), "lead": x["lead"], "articulation": x.get("articulation", "as_written"),
                                    "why": str(x.get("why", ""))[:300]} for x in plan["phrases"]],
                       "handoffs": hand, "lead_share": {k: round(v / float(max(1, len(mel))), 2) for k, v in tot.items()}}
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
        L.append("Виолончель удваивает бас: %d нот; средний голос удваивает альт (или скрипка, когда мелодию ведёт не она): %d нот; перенос на октаву: %d."
                 % (s.get("bass_notes", 0), s.get("inner_notes", 0), s["octave"]))
    if s.get("pedal_sustained"):
        L.append("Нот, которые у рояля держала педаль, продлено: %d (у смычка и дыхания педали нет)." % s["pedal_sustained"])
    if s.get("mono_melody_dropped"):
        L.append("Одноголосная мелодия: %d нот, начатых вразнобой с верхней (перебор аккорда), переданы в сопровождение."
                 % s["mono_melody_dropped"])
    if s.get("sing_extended"):
        L.append("Связная игра (legato): продлено до следующей ноты той же партии %d нот; %d остановлено раньше, чтобы не "
                 "вышло резкого созвучия, которого нет у рояля." % (s["sing_extended"], s.get("sing_stopped", 0)))
    pl = rep.get("plan")
    if pl:
        L.append("План модели — кто ведёт мелодию (у мастеров верхний инструмент ведёт около 70%% нот мелодии): %s."
                 % ", ".join("%s %.0f%%" % (RU.get(k, k), 100 * v) for k, v in sorted(pl["lead_share"].items(), key=lambda x: -x[1])))
        for x in pl["phrases"]:
            L.append("  такты %d–%d: ведёт %s, %s%s" % (x["bars"][0], x["bars"][1], RU.get(x["lead"], x["lead"]),
                     "связно" if x["articulation"] == "legato" else "как написано", (" — " + x["why"]) if x["why"] else ""))
    if s.get("melody_shift"):
        L.append("Мелодия перенесена на %d окт. (%s), чтобы лечь в удобную середину инструмента."
                 % (abs(s["melody_shift"]) // 12, "вверх" if s["melody_shift"] > 0 else "вниз"))
    L.append("Статус: составы и «один исполнитель на партию» — по источникам; раздача нот — по замеру у мастеров (без рояля) "
             "и эвристика (с роялем). Программа считает, а не слушает.")
    return "\n".join(L)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        for k, e in ENSEMBLES.items(): print("%-18s %s  [%s]" % (k, e["ru"], e["source"]))
    else:                                        # ... пьеса.mid выход состав [--legato] [--plan план.json]
        import json
        _plan = json.load(open(sys.argv[sys.argv.index("--plan") + 1], encoding="utf-8")) if "--plan" in sys.argv else None
        print(text(arrange(sys.argv[1], sys.argv[2], sys.argv[3], plan=_plan, legato="--legato" in sys.argv, mono="--mono" in sys.argv)))
