"""
Разбор пьесы-образца для генератора (2026-11-22): «сочини новое в стиле этой пьесы».

analyze(midi) -> сведения о «почерке»: тональность, размер, темп, длина, фразы и разделы, аккорды по тактам,
ритм и регистр мелодии, фактура сопровождения, динамика. Модели уходят только эти сведения (шаблон), а не ноты.
template(res, bars) -> текст шаблона в формате генератора ([Паспорт], разделы, [Запреты]).
similarity(ref_res, new_midi) -> насколько новая пьеса похожа на образец: самый длинный совпавший кусок мелодии
(в нотах, без учёта транспонирования) и самый длинный совпавший ряд аккордов (в тактах, по ступеням тональности).

Все пороги и способы — эвристика, кроме профилей тональности: Krumhansl & Kessler (1982), по Krumhansl,
«Cognitive Foundations of Musical Pitch» (1990), — так называемый алгоритм Крумхансл–Шмуклера.
"""
import collections
import math
import os
import sys

import mido

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine2     # noqa: E402

# профили Крумхансл–Кесслер (мажор, минор), от тоники
KK_MAJ = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MIN = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
FLAT_KEYS_MAJ = {5, 10, 3, 8, 1}          # F, Bb, Eb, Ab, Db мажор
FLAT_KEYS_MIN = {2, 7, 0, 5, 10}          # d, g, c, f, bb минор
RU = {"C": "до", "C#": "до-диез", "Db": "ре-бемоль", "D": "ре", "D#": "ре-диез", "Eb": "ми-бемоль", "E": "ми",
      "F": "фа", "F#": "фа-диез", "Gb": "соль-бемоль", "G": "соль", "G#": "соль-диез", "Ab": "ля-бемоль", "A": "ля",
      "A#": "ля-диез", "Bb": "си-бемоль", "B": "си"}
# шаблоны аккордов: (название, интервалы от основного тона, вес)
CHORDS = [("", (0, 4, 7), 1.0), ("m", (0, 3, 7), 1.0), ("7", (0, 4, 7, 10), 0.9), ("dim", (0, 3, 6), 0.8),
          ("m7", (0, 3, 7, 10), 0.85), ("maj7", (0, 4, 7, 11), 0.8), ("dim7", (0, 3, 6, 9), 0.85)]
DYN = [(40, "pp"), (52, "p"), (64, "mp"), (78, "mf"), (92, "f"), (200, "ff")]     # средняя сила нажатия -> слово
MEL_RUN_MAX = 8        # столько нот мелодии подряд, совпавших с образцом, — уже заимствование (эвристика)
CHORD_RUN_MAX = 8      # столько тактов подряд с той же последовательностью аккордов (эвристика)


SPELL = {}     # класс высоты -> название по ладу текущей тональности (ставится в analyze)


def _pc_name(pc, flat):
    return SPELL.get(pc % 12) or (NAMES_FLAT if flat else NAMES_SHARP)[pc % 12]


def _spelling(tonic, mode, flat):
    """Названия ступеней лада (в миноре и VII повышенная): до-диез минор -> B# вместо C, E# вместо F."""
    letters, nat = "CDEFGAB", [0, 2, 4, 5, 7, 9, 11]
    tl = letters.index((NAMES_FLAT if flat else NAMES_SHARP)[tonic][0])
    steps = [0, 2, 4, 5, 7, 9, 11] if mode == "major" else [0, 2, 3, 5, 7, 8, 10]
    out = {}
    for i, st in enumerate(steps + ([11] if mode == "minor" else [])):
        li = (tl + (i if i < 7 else 6)) % 7
        pc = (tonic + st) % 12
        acc = (pc - nat[li] + 6) % 12 - 6
        if abs(acc) <= 2:
            out.setdefault(pc, letters[li] + ("#" * acc if acc > 0 else "b" * -acc))
    return out


def note_name(p, flat=False):
    return "%s%d" % (_pc_name(p, flat), p // 12 - 1)


def read(path):
    """Ноты: [(начало, конец, высота, дорожка, сила)] в долях (четвертях), плюс темп, размер, педаль."""
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat
    notes, tempo, ts, pedal = [], None, None, 0
    for ti, tr in enumerate(mid.tracks):
        t, on = 0, {}
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo" and tempo is None:
                tempo = mido.tempo2bpm(msg.tempo)
            elif msg.type == "time_signature" and ts is None:
                ts = (msg.numerator, msg.denominator)
            elif msg.type == "control_change" and msg.control == 64 and msg.value >= 64:
                pedal += 1
            elif msg.type == "note_on" and msg.velocity > 0:
                on.setdefault((msg.channel, msg.note), []).append((t, msg.velocity))
            elif msg.type in ("note_off", "note_on"):
                st = on.get((msg.channel, msg.note))
                if st:
                    s, v = st.pop(0)
                    if t > s and msg.channel != 9:
                        notes.append((s / tpb, t / tpb, msg.note, ti, v))
    notes.sort()
    return notes, tempo or 90.0, ts or (4, 4), pedal


MEL_ENV = {"ORCH_ENGINE": "2", "ORCH_MELODY_HELD": "1", "ORCH_MEL_TRACK": "1"}


def melody(path):
    """Мелодия, как её видит оркестратор с одобренными переключателями (движок 2, удержанные ноты, верхняя дорожка):
    на «Лунной» 108 нот с затакта к т. 5, без верхушек триолей. Переключатели ставятся только на время вызова."""
    old = {k: os.environ.get(k) for k in MEL_ENV}
    os.environ.update(MEL_ENV)
    try:
        import orchestrator
        _, _, mel, _ = orchestrator.analyze(path)
        return [{"offset": m["offset"], "dur": m["dur"], "pitch": m["pitch"]} for m in mel]
    except Exception:
        return []
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def find_key(notes):
    w = [0.0] * 12
    for s, e, p, _, _ in notes:
        w[p % 12] += e - s
    best = None
    for tonic in range(12):
        for mode, prof in (("major", KK_MAJ), ("minor", KK_MIN)):
            x = [prof[(i - tonic) % 12] for i in range(12)]
            mx, mw = sum(x) / 12, sum(w) / 12
            num = sum((a - mx) * (b - mw) for a, b in zip(x, w))
            den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - mw) ** 2 for b in w)) or 1
            r = num / den
            if best is None or r > best[0]:
                best = (r, tonic, mode)
    _, tonic, mode = best
    flat = tonic in (FLAT_KEYS_MAJ if mode == "major" else FLAT_KEYS_MIN)
    return tonic, mode, flat


def _chord(weights, bass_pc, flat):
    """Аккорд такта по весам классов высоты (длительность). Возвращает (символ, основной тон, тип) или None."""
    tot = sum(weights) or 1
    best = None
    for root in range(12):
        for suf, iv, k in CHORDS:
            pcs = {(root + i) % 12 for i in iv}
            inside = sum(weights[pc] for pc in pcs) / tot
            missing = sum(1 for pc in pcs if weights[pc] < 0.05 * tot) / len(pcs)
            sc = k * (inside - 0.6 * missing) + (0.08 if bass_pc == root else 0)
            if best is None or sc > best[0]:
                best = (sc, root, suf, pcs)
    sc, root, suf, pcs = best
    if sc < 0.25:
        return None
    if suf in ("maj7", "m7", "7") and bass_pc is not None and bass_pc == (root + CHORDS[[c[0] for c in CHORDS].index(
            suf)][1][3]) % 12:
        suf = "m" if suf == "m7" else ""          # D + C# в басу = D/C# (басовая педаль), а не Dmaj7/C#
        pcs = {(root + i) % 12 for i in ((0, 3, 7) if suf == "m" else (0, 4, 7))}
    iv = dict((c[0], c[1]) for c in CHORDS)[suf]
    rn = _pc_name(root, flat) if all(pc in SPELL for pc in pcs) else (NAMES_FLAT if flat else NAMES_SHARP)[root]
    sym = rn + suf
    if bass_pc is not None and bass_pc != root and bass_pc in pcs:
        k = [(root + i) % 12 for i in iv].index(bass_pc)     # какой звук аккорда в басу: буква от основного тона
        letters, nat = "CDEFGAB", [0, 2, 4, 5, 7, 9, 11]
        li = (letters.index(rn[0]) + 2 * k) % 7
        acc = (bass_pc - nat[li] + 6) % 12 - 6
        sym += "/" + (letters[li] + ("#" * acc if acc > 0 else "b" * -acc) if abs(acc) <= 2 else _pc_name(bass_pc, flat))
    return sym, root, suf


def _dur_word(d):
    for v, w in ((0.25, "шестнадцатая"), (1 / 3, "триольная восьмая"), (0.5, "восьмая"), (2 / 3, "две триольные восьмые"), (0.75, "восьмая с точкой"),
                 (1, "четверть"), (1.5, "четверть с точкой"), (2, "половинная"), (3, "половинная с точкой"),
                 (4, "целая")):
        if abs(d - v) < 0.04:
            return w
    return "%g доли" % round(d, 2)


def analyze(path, title=None):
    notes, tempo, (num, den), pedal = read(path)
    if not notes:
        raise ValueError("в файле нет нот")
    bar_len = num * 4.0 / den
    n_bars = max(1, int(math.ceil(max(e for _, e, *_ in notes) / bar_len - 1e-6)))
    tonic, mode, flat = find_key(notes)
    SPELL.clear()
    SPELL.update(_spelling(tonic, mode, flat))
    tracks = collections.defaultdict(list)
    for n in notes:
        tracks[n[3]].append(n[2])
    top = max(tracks, key=lambda t: sum(tracks[t]) / len(tracks[t])) if len(tracks) > 1 else None
    mel = [m for m in melody(path) if m["dur"] > 0.05] or [
        m for m in engine2.find_melody([(s, e, p, t) for s, e, p, t, _ in notes], top_part=top) if m["dur"] > 0.05]
    mel_keys = {(round(m["offset"], 3), m["pitch"]) for m in mel}
    acc = [n for n in notes if (round(n[0], 3), n[2]) not in mel_keys]
    bars = []
    for b in range(n_bars):
        t0, t1 = b * bar_len, (b + 1) * bar_len
        w = [0.0] * 12
        inbar = [n for n in notes if n[0] < t1 - 1e-6 and n[1] > t0 + 1e-6]
        for s, e, p, _, _ in inbar:
            w[p % 12] += min(e, t1) - max(s, t0)
        starts = [n for n in notes if t0 - 1e-6 <= n[0] < t1 - 1e-6]
        low = min(inbar, key=lambda n: (n[2], n[0])) if inbar else None
        ch = _chord(w, low[2] % 12 if low else None, flat) if inbar else None
        m = [x for x in mel if t0 - 1e-6 <= x["offset"] < t1 - 1e-6]
        a = [n for n in acc if t0 - 1e-6 <= n[0] < t1 - 1e-6]
        a_on = sorted({round(n[0] - t0, 3) for n in a})
        triplet = sum(1 for x in a_on if abs(x * 3 - round(x * 3)) < 0.02 and abs(x * 2 - round(x * 2)) > 0.02)
        groups = collections.Counter(round(n[0], 3) for n in a)
        bass_long = bool(low) and (min(low[1], t1) - max(low[0], t0)) >= bar_len / 2
        bars.append({
            "chord": ch[0] if ch else None, "root": ch[1] if ch else None, "qual": ch[2] if ch else None,
            "vel": sum(n[4] for n in starts) / len(starts) if starts else None,
            "mel": [(round(x["offset"] - t0, 3), round(x["dur"], 3), x["pitch"]) for x in m],
            "acc_per_beat": len(a_on) / max(1, num * 4 / den), "acc_triplet": triplet / max(1, len(a_on)),
            "acc_single": sum(1 for v in groups.values() if v == 1) / max(1, len(groups)),
            "acc_lo": min((n[2] for n in a), default=None), "acc_hi": max((n[2] for n in a), default=None),
            "bass": low[2] if low else None, "bass_long": bass_long,
        })
    # концы фраз: в такте мелодия кончается долгой нотой (от 1,5 доли) или паузой от доли до конца такта
    ends = []
    for i, b in enumerate(bars):
        mm = b["mel"]
        if not mm:
            continue
        last_on, last_d, _ = mm[-1]
        gap = bar_len - (last_on + last_d)
        if last_d >= 1.5 or gap >= 1 - 1e-6:
            ends.append(i + 1)
    phrases, prev = [], 0
    for e in ends:
        if e - prev >= 2:
            phrases.append((prev + 1, e))
            prev = e
    if prev < n_bars:
        if phrases and n_bars - prev < 2:
            phrases[-1] = (phrases[-1][0], n_bars)
        else:
            phrases.append((prev + 1, n_bars))
    # разделы: склеиваем фразы, пока раздел короче 6 тактов; такты без мелодии в начале и в конце — вступление и кода
    lead = next((i for i, b in enumerate(bars) if b["mel"]), 0)
    tail = next((i for i, b in enumerate(reversed(bars)) if b["mel"]), 0)
    sections = []
    if lead >= 1:
        phrases = [(1, lead)] + [(max(a, lead + 1), b) for a, b in phrases if b > lead]
    for a, b in phrases:
        if sections and sections[-1][1] - sections[-1][0] + 1 < 6 and not (lead >= 1 and sections[-1] == (1, lead)):
            sections[-1] = (sections[-1][0], b)
        else:
            sections.append((a, b))
    res = {"title": title or os.path.splitext(os.path.basename(path))[0], "tempo": round(tempo), "num": num,
           "den": den, "bar_len": bar_len, "bars": n_bars, "tonic": tonic, "mode": mode, "flat": flat,
           "pedal": pedal > 0, "bar_info": bars, "phrases": phrases, "sections": sections,
           "intro": lead, "outro": tail, "melody": [(m["offset"], m["dur"], m["pitch"]) for m in mel],
           "two_layers_rh": False}
    # ритм мелодии образца: если он сам не прошёл бы проверку генератора «ритм однообразный», её не требовать
    import composer
    rh = [tuple(round(m[1] * 4) / 4 for m in b["mel"]) for b in bars if b["mel"]]
    durs = [m["dur"] for m in mel]
    same = collections.Counter(rh).most_common(1)[0][1] / len(rh) if rh else 0
    short = sum(1 for d in durs if d < 0.99) / len(durs) if durs else 1
    res["rhythm_calm"] = same > composer.SAME_RHYTHM_MAX or short < composer.SHORT_MIN
    # мелодия и сопровождение в одной (верхней) дорожке — значит, у правой руки два слоя (как в «Лунной»)
    if top is not None:
        rh_acc = sum(1 for n in acc if n[3] == top)
        res["two_layers_rh"] = rh_acc > 0.3 * max(1, len(tracks[top]) - len(mel))
    return res


def key_text(res):
    name = _pc_name(res["tonic"], res["flat"])
    return RU[name] + (" мажор" if res["mode"] == "major" else " минор")


def _dyn(v):
    for lim, w in DYN:
        if v is not None and v < lim:
            return w
    return "mp"


def _section_text(res, a, b):
    """Описание куска образца (такты a..b) словами — без самих нот мелодии."""
    bi = res["bar_info"][a - 1:b]
    vel = [x["vel"] for x in bi if x["vel"]]
    dyn = _dyn(sum(vel) / len(vel)) if vel else "mp"
    chords = []
    for x in bi:
        if x["chord"] and (not chords or chords[-1] != x["chord"]):
            chords.append(x["chord"])
    per_bar = sum(1 for x in bi if x["chord"]) and len(chords) / max(1, len(bi))
    mel = [m for x in bi for m in x["mel"]]
    lines = ["Динамика: %s" % dyn]
    lines.append("Гармония образца здесь (для ориентира по звучанию, НЕ копировать по порядку): %s; смена аккорда "
                 "примерно %s." % (", ".join(chords[:10]) or "—",
                                   "раз в такт" if per_bar >= 0.8 else "раз в два такта" if per_bar >= 0.4 else
                                   "редко, аккорд держится несколько тактов"))
    if mel:
        ps = [m[2] for m in mel]
        durs = collections.Counter(round(m[1] * 12) / 12 for m in mel)
        common = ", ".join("%s" % _dur_word(d) for d, _ in durs.most_common(3))
        steps = [abs(ps[i + 1] - ps[i]) for i in range(len(ps) - 1)]
        rep = sum(1 for s in steps if s == 0) / max(1, len(steps))
        step = sum(1 for s in steps if 0 < s <= 2) / max(1, len(steps))
        lines.append("Мелодия: от %s до %s; %.1f ноты на такт; длительности чаще всего %s; повторы одной ноты %d%%, "
                     "шаги %d%%, скачки %d%%." % (note_name(min(ps), res["flat"]), note_name(max(ps), res["flat"]),
                                                    len(mel) / len(bi), common, 100 * rep, 100 * step,
                                                    100 * (1 - rep - step)))
    else:
        lines.append("Мелодия: нет (только сопровождение).")
    apb = sum(x["acc_per_beat"] for x in bi) / len(bi)
    trip = sum(x["acc_triplet"] for x in bi) / len(bi)
    single = sum(x["acc_single"] for x in bi) / len(bi)
    lo = [x["acc_lo"] for x in bi if x["acc_lo"] is not None]
    hi = [x["acc_hi"] for x in bi if x["acc_hi"] is not None]
    kind = ("ровные триоли восьмыми" if trip > 0.4 and apb >= 2.5 else "бегущие восьмые" if apb >= 1.8 else
            "аккорды на доли" if apb >= 0.8 else "долгие аккорды")
    shape = "по одной ноте (разложенный аккорд)" if single > 0.7 else "аккордами"
    long_bass = sum(1 for x in bi if x["bass_long"]) / len(bi)
    acc = "Сопровождение: %s, %s, от %s до %s" % (kind, shape, note_name(min(lo), res["flat"]) if lo else "—",
                                                   note_name(max(hi), res["flat"]) if hi else "—")
    if long_bass > 0.5:
        acc += "; бас тянется весь такт или полтакта (часто октавой)"
    lines.append(acc + ".")
    return lines


def template(res, bars=None):
    """Шаблон для генератора по образцу. bars — длина новой пьесы (по умолчанию как у образца, но не больше 32)."""
    n0 = res["bars"]
    n = int(bars or min(n0, 32))
    k = n / n0
    num, den = res["num"], res["den"]
    tempo_word = ("очень медленно" if res["tempo"] < 56 else "медленно" if res["tempo"] < 72 else
                  "умеренно" if res["tempo"] < 100 else "подвижно" if res["tempo"] < 130 else "быстро")
    vel = [b["vel"] for b in res["bar_info"] if b["vel"]]
    out = ["[Паспорт]",
           "Жанр и ориентир: новая оригинальная пьеса для фортепиано в стиле образца «%s» (тот же характер, гармонический "
           "язык, фактура и форма), но со своей мелодией и своей последовательностью аккордов" % res["title"],
           "Тональность: %s" % key_text(res),
           "Размер: %d/%d" % (num, den),
           "Темп: %d, %s" % (res["tempo"], tempo_word),
           "Длина: %d тактов" % n,
           "Характер: как у образца; общая динамика около %s" % (_dyn(sum(vel) / len(vel)) if vel else "mp"),
           "", "[Зерно — главный мотив]",
           "Свой мотив из 3–5 нот (не из образца) в ритме, типичном для мелодии образца; он возвращается в разных "
           "разделах, на разной высоте.", ""]
    if res.get("two_layers_rh"):
        out[-1:-1] = ["", "[Фактура правой руки]",
                      "Как в образце, правая рука ведёт два слоя: мелодию (\"rh\") и под ней фигурацию сопровождения "
                      "(\"rh2\"), обе в пределах одной руки (не шире 14 полутонов вместе). Левая рука — бас."]
    # разделы образца переносятся на новую длину пропорционально (вступление и кода — как есть, если помещаются)
    secs = list(res["sections"])
    bounds, acc, cuts = [], 0, []
    for a, b in secs:
        cuts.append(b)
    prev = 0
    for i, (a, b) in enumerate(secs):
        end = n if i == len(secs) - 1 else max(prev + 2, int(round(b * k)))
        end = min(end, n - 2 * (len(secs) - 1 - i))
        if end <= prev:
            continue
        bounds.append((prev + 1, end, a, b))
        prev = end
    letters = iter("ABCDEFGHIJ")
    for j, (na, nb, a, b) in enumerate(bounds):
        if j == 0 and res["intro"] >= 1 and b <= res["intro"]:
            title = "Вступление"
        elif j == len(bounds) - 1 and len(bounds) > 2:
            title = "Кода (как конец образца)"
        else:
            title = "Раздел %s" % next(letters)
        out.append("[%s — как такты %d–%d образца, такты %d–%d]" % (title, a, b, na, nb))
        out += _section_text(res, a, b)
        out.append("")
    out += ["[Запреты]",
            "Не брать мелодию образца: ни одного его мотива или такта, даже в другой тональности (это проверяется).",
            "Не повторять последовательность аккордов образца такт в такт: свой гармонический план в его духе.",
            "Без параллельных октав и квинт между мелодией и басом.",
            "Не больше 4 нот в руке, рука не шире 14 полутонов.",
            "Без джазовых аккордов и посторонних стилю приёмов."]
    return "\n".join(out)


# ---------- похожесть новой пьесы на образец ----------

def _tokens(mel):
    """Мелодия -> ряд (интервал до следующей ноты, отношение длительностей): не зависит от тональности и темпа."""
    t = []
    for i in range(len(mel) - 1):
        d0, d1 = mel[i][1], mel[i + 1][1]
        t.append((mel[i + 1][2] - mel[i][2], round(math.log2(max(d1, 0.05) / max(d0, 0.05)) * 2) / 2))
    return t


def _longest_common(a, b):
    """Самый длинный общий кусок двух рядов (динамическое программирование)."""
    best, prev = 0, [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b):
            if x == y:
                cur[j + 1] = prev[j] + 1
                if cur[j + 1] > best:
                    best = cur[j + 1]
        prev = cur
    return best


def _degrees(res):
    return [None if b["root"] is None else ((b["root"] - res["tonic"]) % 12, b["qual"]) for b in res["bar_info"]]


def similarity(ref, new_midi):
    """Похожесть новой пьесы на образец. Возвращает словарь и (серьёзные, мелкие) замечания для модели."""
    new = analyze(new_midi)
    a, b = _tokens(ref["melody"]), _tokens(new["melody"])
    run = _longest_common(a, b) + 1 if a and b else 0          # интервалов +1 = нот
    n5a = {tuple(a[i:i + 4]) for i in range(len(a) - 3)}
    n5b = [tuple(b[i:i + 4]) for i in range(len(b) - 3)]
    share = sum(1 for g in n5b if g in n5a) / len(n5b) if n5b else 0.0
    da, db = [x for x in _degrees(ref)], [x for x in _degrees(new)]
    crun = _longest_common([x for x in da if x], [x for x in db if x])
    info = {"melody_run": run, "melody_share": round(share, 3), "chord_run": crun}
    serious, minor = [], []
    if run >= MEL_RUN_MAX:
        serious.append("The melody copies the model piece: %d notes in a row have the same intervals and rhythm as the "
                       "original. Write your OWN melody (new motif, new contour), keep only the style." % run)
    if crun >= CHORD_RUN_MAX:
        serious.append("The chord progression copies the model piece for %d bars in a row. Keep the harmonic language "
                       "but write your own progression." % crun)
    if share > 0.2 and run < MEL_RUN_MAX:
        minor.append("Мелодия местами близка к образцу: %.0f%% коротких оборотов из 5 нот есть в образце." % (100 * share))
    return info, serious, minor


def similarity_text(info):
    return ("Похожесть на образец: самый длинный совпавший кусок мелодии — %d нот (порог %d), совпавших оборотов из "
            "5 нот %.0f%%, самый длинный совпавший ряд аккордов — %d тактов (порог %d)." % (
                info["melody_run"], MEL_RUN_MAX, 100 * info["melody_share"], info["chord_run"], CHORD_RUN_MAX))


if __name__ == "__main__":
    r = analyze(sys.argv[1])
    print(template(r, int(sys.argv[2]) if len(sys.argv) > 2 else None))
