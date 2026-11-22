"""
Генератор фортепианной пьесы по запросу (2026-11-21, страница «Генератор»).

Модель (тот же поставщик, что пишет план оркестровки: PLANNER_PROVIDER / PLANNER_MODEL) сочиняет ФОРТЕПИАННУЮ пьесу
в простом JSON (такты, правая и левая рука, ноты по названиям, длительности в четвертях). Программа:
  1) переводит JSON в MIDI (две дорожки: правая и левая рука; один канал; педаль по тактам по желанию модели);
  2) чинит мелкие ошибки счёта (такт короче — пауза в конце, длиннее — обрезка) и пишет, что исправила;
  3) проверяет пьесу: число тактов, тональность (доля нот в гамме), растяжку рук (piano_review: P1 > 14 полутонов,
     P2 > 5 нот в руке), пустые такты мелодии; при серьёзных замечаниях отдаёт их модели и просит переписать
     (не больше MAX_ROUNDS запросов — каждый платный).
Оркестр, ансамбль или солиста из пьесы делает уже основная программа (кнопка на странице).

Статусы чисел: растяжка руки 14 полутонов — подтверждено (Берлиоз, гл. о фортепиано; Fujita/Chiu по Nakamura–Yoshii
2018, см. CLAUDE.md 4); «не больше 4 нот в руке», доля нот в гамме ≥ 85%, громкости ступеней, пороги «серьёзности» —
эвристика. Музыкальное качество программа не оценивает: судья — слушатель.
"""
import json, os, re, tempfile
import mido

import llm_planner

MAX_TOKENS = 48000      # лимит ответа модели для пьесы (Haiku 5.5 допускает до 128k; платится только использованное)
_LOW_EFFORT = [False]
CONT_MAX = 4           # дописываний оборванной пьесы (каждое — платный запрос, у Haiku доли цента)
MAX_ROUNDS = 2          # запросов к модели на одну пьесу (второй — только если первая попытка с серьёзными замечаниями)
TPB = 480
DYN = {"pp": 36, "p": 46, "mp": 58, "mf": 70, "f": 84, "ff": 98}        # эвристика
SAME_RHYTHM_MAX, SHORT_MIN = 0.4, 0.15   # эвристика: «однообразно», если один ритм в > 40% тактов или коротких нот < 15%
MEL_PLUS = 8            # мелодия (правая рука) громче сопровождения — иначе «все перекрикивают» (12.78)
RH_RANGE, LH_RANGE = (53, 96), (28, 72)                                 # эвристика: удобные регистры рук
NOTE_RE = re.compile(r"^\s*([A-Ga-g])\s*([#b♯♭]{0,2})\s*(-?\d)\s*$")
STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

SYSTEM = """You are a composer writing an ORIGINAL solo piano piece (two hands) on request. Reply with ONLY one JSON object.

Format:
{"title": "...", "key": "D major", "time": "3/4", "tempo": 92, "pedal": "bar" | "none",
 "bars": [ {"dyn": "mp", "rh": [["F#5", 1], ["E5", 0.5], ["D5", 0.5], ["r", 1]],
            "lh": [[["D3", "A3", "F#4"], 1], [["A3"], 2]]}, ... ]}

Rules:
1. Pitch names like C4 (middle C), F#5, Bb3; "r" is a rest; a chord is a list of names. Durations are in quarter notes
   (1 = quarter, 0.5 = eighth, 1.5 = dotted quarter, 0.333 = triplet eighth). In EVERY bar each hand's durations must add
   up exactly to the bar length (3/4 -> 3, 4/4 -> 4, 6/8 -> 3).
2. Right hand: a clear, singable melody (mostly steps, leaps followed by a step back), phrases of 4 or 8 bars with breathing
   points, a climax about two thirds through, a final cadence on the tonic. Right hand mostly between G3 and C7.
   Rhythm must be varied and alive: mix quarters with eighths, dotted rhythms, ties over the beat or syncopation where the
   style allows, occasional triplets and short ornaments (passing notes, neighbour notes, appoggiaturas, a turn written
   out in sixteenths). Do not repeat the same bar rhythm more than twice in a row except in a deliberate sequence; at
   least a quarter of the melody notes should be shorter than a quarter note. Longer notes at phrase ends.
   For 16 bars or more give the piece contrast: A section, a B section (other register, other harmony or a related key),
   and a varied return of A.
3. Left hand: accompaniment that fits the style (waltz "bass-chord-chord", broken chords, Alberti bass, sustained chords,
   arpeggios). Left hand mostly between E1 and C5. Bass on strong beats. Do not keep one pattern for the whole piece:
   change it between sections, and in some bars (before cadences, in the B section) let the bass or an inner voice move
   as a short counter-melody in eighths or quarters.
4. Playability: in each hand the notes sounding together span at most 14 semitones and at most 4 notes.
5. Harmony: stay in the key with clear functional harmony (I, IV, V, ii, vi, secondary dominants allowed); modulate only
   if asked; avoid parallel fifths and octaves between melody and bass.
6. "dyn" per bar: pp, p, mp, mf, f or ff, following the shape of the music. Use "pedal": "bar" for lyrical pieces.
7. Write exactly the requested number of bars, ALL of them in full: never abbreviate, never write "..." or "same as
   above". Keep the JSON compact (no line breaks or extra spaces). No text outside the JSON.
8. If the request is a structured template ([Паспорт], sections with bar numbers, chords, [Запреты]), follow it EXACTLY:
   key, time, tempo and length from [Паспорт]; each section in exactly its bars; the given chords in the given bars
   (chord symbols like Dm, A7, Gm/Bb, Cmaj7, E7sus4; "|" separates groups of bars, chords are spread evenly over the
   section's bars unless bar numbers are given); dynamics and tempo changes per section (write ritardando as longer
   notes and rests, the tempo itself stays fixed); obey every line of [Запреты]. Use the motif from [Зерно].
   Lines of lyrics inside a section are NOT sung: use their syllables and word stresses as a rhythm guide for the melody
   (about one note per syllable, stressed syllables on strong beats or longer notes).
   Instrument, voice and sound-design words describe the mood only: you still write for solo piano.
9. Optional per bar "rh2": a second right-hand layer UNDER the melody (inner figuration, e.g. triplet broken chords while
   the melody holds a note), same format as "rh", its durations also add up to the bar. Use it only when the request asks
   for two layers in the right hand; then "rh" is the melody alone. Melody and "rh2" sounding together must still fit
   one hand (at most 14 semitones, at most 4 notes)."""


def _pitch(name):
    """'F#5' -> 78; None for a rest or an unreadable name."""
    if not isinstance(name, str) or name.strip().lower() in ("r", "rest", ""):
        return None
    m = NOTE_RE.match(name.replace("♯", "#").replace("♭", "b"))
    if not m:
        return None
    p = STEP[m.group(1).upper()] + m.group(2).count("#") - m.group(2).count("b") + 12 * (int(m.group(3)) + 1)
    return p if 0 <= p <= 127 else None


def _meter(ts):
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", str(ts or "4/4"))
    num, den = (int(m.group(1)), int(m.group(2))) if m else (4, 4)
    if den not in (2, 4, 8, 16) or not 1 <= num <= 12:
        num, den = 4, 4
    return num, den, num * 4.0 / den


def _key(text):
    """'D major' / 'b minor' / 'ре мажор' -> (тоника 0..11, минор?) или None."""
    t = str(text or "").strip().lower().replace("♯", "#").replace("♭", "b")
    ru = {"до": "c", "ре": "d", "ми": "e", "фа": "f", "соль": "g", "ля": "a", "си": "b"}
    for k, v in ru.items():
        t = re.sub(r"^" + k + r"(?=[\s-]|$)", v, t)
    t = t.replace("-диез", "#").replace(" диез", "#").replace("-бемоль", "b").replace(" бемоль", "b")
    m = re.match(r"^([a-g])\s*(#|b|sharp|flat)?\s*-?\s*(major|minor|maj|min|мажор|минор|m)?", t)
    if not m:
        return None
    tonic = (STEP[m.group(1).upper()] + (1 if m.group(2) in ("#", "sharp") else -1 if m.group(2) in ("b", "flat") else 0)) % 12
    minor = (m.group(3) or "major") in ("minor", "min", "минор", "m")
    return tonic, minor


def scale_share(notes, key):
    """Доля нот в гамме (у минора — натуральный, гармонический и мелодический вместе)."""
    if not key or not notes:
        return None
    t, minor = key
    deg = {0, 2, 3, 5, 7, 8, 9, 10, 11} if minor else {0, 2, 4, 5, 7, 9, 11}
    return sum(1 for p in notes if (p - t) % 12 in deg) / len(notes)


def _events(items, bar_len, fixes, bno, hand):
    """[[название|список, длительность], ...] -> [(смещение, длительность, [высоты])]; такт точно bar_len долей."""
    out, t = [], 0.0
    for it in items or []:
        try:
            what, dur = it[0], float(it[1])
        except Exception:
            fixes.append("такт %d, %s: непонятная запись %r пропущена" % (bno, hand, it))
            continue
        if dur <= 0:
            continue
        if t + dur > bar_len + 1e-3:
            fixes.append("такт %d, %s: длиннее такта — конец обрезан" % (bno, hand))
            dur = bar_len - t
            if dur <= 1e-3:
                break
        names = what if isinstance(what, list) else [what]
        ps = [p for p in (_pitch(n) for n in names) if p is not None]
        bad = [n for n in names if _pitch(n) is None and str(n).strip().lower() not in ("r", "rest", "")]
        if bad:
            fixes.append("такт %d, %s: не понял ноту %s — пропущена" % (bno, hand, ", ".join(map(str, bad))))
        if ps:
            out.append((t, dur, sorted(set(ps))))
        t += dur
    if t < bar_len - 1e-3:
        fixes.append("такт %d, %s: короче такта на %.2g доли — дописана пауза" % (bno, hand, bar_len - t))
    return out


def _fold(p, lo, hi):
    while p < lo:
        p += 12
    while p > hi:
        p -= 12
    return p


def to_midi(piece, path):
    """JSON пьесы -> MIDI (дорожка 1 правая рука, дорожка 2 левая). Возвращает (сведения, список исправлений)."""
    fixes = []
    num, den, bar_len = _meter(piece.get("time"))
    tempo = int(min(200, max(30, float(piece.get("tempo") or 90))))
    bars = piece.get("bars") or []
    pedal = str(piece.get("pedal", "bar")).lower() != "none"
    mid = mido.MidiFile(ticks_per_beat=TPB)
    meta = mido.MidiTrack()
    mid.tracks.append(meta)
    meta.append(mido.MetaMessage("track_name", name="Piano", time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=num, denominator=den, time=0))
    stats = {"rh": [], "lh": [], "empty_rh": 0, "folded": 0}
    for hand, name, rng in (("rh", "Piano RH", RH_RANGE), ("lh", "Piano LH", LH_RANGE)):
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        tr.append(mido.Message("program_change", program=0, channel=0, time=0))
        ev = []                                           # (тик, порядок, сообщение)
        for i, b in enumerate(bars):
            b = b if isinstance(b, dict) else {}
            start = i * bar_len
            vel = DYN.get(str(b.get("dyn", "mp")).lower(), DYN["mp"]) + (MEL_PLUS if hand == "rh" else 0)
            notes = _events(b.get(hand), bar_len, fixes, i + 1, "правая рука" if hand == "rh" else "левая рука")
            inner = _events(b.get("rh2"), bar_len, fixes, i + 1, "правая рука, второй слой") if (
                hand == "rh" and b.get("rh2")) else []
            if hand == "rh" and not notes:
                stats["empty_rh"] += 1
            if hand == "rh":
                stats.setdefault("rhythms", []).append(tuple(round(d * 4) / 4 for _, d, _ in notes))
                stats.setdefault("durs", []).extend(d for _, d, _ in notes)
            for off, dur, ps, vv in [n + (vel,) for n in notes] + [n + (vel - MEL_PLUS,) for n in inner]:
                for p in ps:
                    q = _fold(p, *rng)
                    if q != p:
                        stats["folded"] += 1
                    stats[hand].append(q)
                    s, e = int(round((start + off) * TPB)), int(round((start + off + dur) * TPB))
                    ev.append((s, 1, mido.Message("note_on", note=q, velocity=max(1, min(127, vv)), channel=0)))
                    ev.append((max(s + 1, e - 1), 0, mido.Message("note_off", note=q, velocity=0, channel=0)))
            if pedal and hand == "lh":
                s = int(round(start * TPB))
                ev.append((s + TPB // 16, 2, mido.Message("control_change", control=64, value=127, channel=0)))
                ev.append((int(round((start + bar_len) * TPB)) - 1, 0, mido.Message("control_change", control=64, value=0, channel=0)))
        ev.sort(key=lambda x: (x[0], x[1]))
        last = 0
        for t, _, msg in ev:
            tr.append(msg.copy(time=t - last))
            last = t
        tr.append(mido.MetaMessage("end_of_track", time=TPB // 2))
    if stats["folded"]:
        fixes.append("нот, перенесённых на октаву в удобный регистр руки: %d" % stats["folded"])
    mid.save(path)
    info = {"bars": len(bars), "time": "%d/%d" % (num, den), "tempo": tempo, "key": piece.get("key"),
            "title": piece.get("title") or "Пьеса", "seconds": round(len(bars) * bar_len * 60.0 / tempo, 1),
            "notes": len(stats["rh"]) + len(stats["lh"]), "empty_melody_bars": stats["empty_rh"],
            "scale_share": scale_share(stats["rh"] + stats["lh"], _key(piece.get("key")))}
    rh_bars = [r for r in stats.get("rhythms", []) if r]
    if rh_bars:
        import collections
        info["same_rhythm_share"] = collections.Counter(rh_bars).most_common(1)[0][1] / len(rh_bars)
    durs = stats.get("durs", [])
    if durs:
        info["short_share"] = sum(1 for d in durs if d < 0.99) / len(durs)
    return info, fixes


def parallels(midi_path):
    """Параллельные октавы и квинты между мелодией (верхняя нота правой руки) и басом (нижняя нота левой руки)
    на первых долях соседних тактов. Запрет: учебник гармонии §11–13 (подтверждено, см. CLAUDE.md 12.52);
    «только первые доли соседних тактов» — эвристика (так их слышно сильнее всего). Возвращает [(такт, такт+1, вид)]."""
    m = mido.MidiFile(midi_path)
    tpb = m.ticks_per_beat
    num, den = 4, 4
    for t in m.tracks:
        for x in t:
            if x.type == "time_signature":
                num, den = x.numerator, x.denominator
    bar = num * 4.0 / den

    def starts(track):
        a, out = 0, []
        for x in track:
            a += x.time
            if x.type == "note_on" and x.velocity > 0:
                out.append((a / tpb, x.note))
        return out
    if len(m.tracks) < 3:
        return []
    rh, lh = starts(m.tracks[1]), starts(m.tracks[2])
    n = int(round(max([s for s, _ in rh + lh] or [0]) / bar)) + 1
    mel = [max([p for s, p in rh if abs(s - i * bar) < 1e-3] or [None]) if any(abs(s - i * bar) < 1e-3 for s, _ in rh) else None for i in range(n)]
    bas = [min([p for s, p in lh if abs(s - i * bar) < 1e-3]) if any(abs(s - i * bar) < 1e-3 for s, _ in lh) else None for i in range(n)]
    out = []
    for i in range(n - 1):
        if None in (mel[i], mel[i + 1], bas[i], bas[i + 1]) or mel[i] == mel[i + 1]:
            continue
        a, b = (mel[i] - bas[i]) % 12, (mel[i + 1] - bas[i + 1]) % 12
        if a == b and a in (0, 7):
            out.append((i + 1, i + 2, "октавы" if a == 0 else "квинты"))
    return out


def check(info, fixes, midi_path, want_bars, skip_rhythm=False):
    """Замечания к пьесе: (серьёзные, мелкие). Серьёзные уходят модели на переписывание."""
    serious, minor = [], []
    if want_bars and info["bars"] != want_bars:
        serious.append("Тактов %d, а просили %d." % (info["bars"], want_bars))
    if info["bars"] < 4:
        serious.append("Слишком коротко: %d тактов." % info["bars"])
    if info["empty_melody_bars"] > max(1, info["bars"] // 8):
        serious.append("В %d тактах у правой руки нет нот (нет мелодии)." % info["empty_melody_bars"])
    same, short = info.get("same_rhythm_share"), info.get("short_share")
    if same is not None and info["bars"] >= 8 and not skip_rhythm and (same > SAME_RHYTHM_MAX or (short is not None and short < SHORT_MIN)):
        serious.append("Ритм мелодии однообразный: один и тот же ритм в %.0f%% тактов, нот короче четверти %.0f%%. "
                       "Разнообразьте ритм (восьмые, пунктир, синкопы, украшения), сохранив мелодию и гармонию."
                       % (100 * same, 100 * (short or 0)))
    sh = info.get("scale_share")
    if sh is not None and sh < 0.85:
        minor.append("В гамме %s только %.0f%% нот (много случайных знаков)." % (info.get("key"), 100 * sh))
    bar_fix = [f for f in fixes if f.startswith("такт")]
    if len(bar_fix) > max(2, info["bars"] // 5):
        serious.append("Счёт в тактах не сходится в %d местах (длительности не складываются в размер)." % len(bar_fix))
    try:
        par = parallels(midi_path)
        if par:
            serious.append("Параллельные %s между мелодией и басом на первых долях тактов: %s. Перепишите эти такты "
                           "(другая нота мелодии или баса, лучше противоположное движение)." % (
                               " и ".join(sorted(set(k for _, _, k in par))),
                               ", ".join("%d–%d (%s)" % x for x in par)))
    except Exception as e:
        minor.append("Проверка параллелей не выполнилась: %s" % e)
    try:
        import piano_review
        rv = piano_review.review(midi_path)
        for _, code, _, text in rv["findings"]:
            (serious if code in ("P1", "P2") else minor).append("[%s] %s" % (code, text))
    except Exception as e:
        minor.append("Проверка рук не выполнилась: %s" % e)
    return serious, minor


def user_text(request, bars, key, time_sig, tempo, variant):
    parts = ["Request (from the user, may be in Russian): " + (request.strip() or "a lyrical piano piece")]
    parts.append("Number of bars: %d." % bars)
    if key:
        parts.append("Key: %s." % key)
    if time_sig:
        parts.append("Time signature: %s." % time_sig)
    if tempo:
        parts.append("Tempo: about %d quarter notes per minute." % tempo)
    parts.append("This is variant #%d: make it different from other variants (other melody and accompaniment)." % variant)
    parts.append("Write for solo piano even if the request mentions other instruments: the piece will be orchestrated later.")
    return "\n".join(parts)


def parse_piece(text):
    """JSON пьесы из ответа модели. Сначала как есть (llm_planner.parse_plan); если не читается — чиним частые
    опечатки моделей: дроби длительностей (1/3, 2/3 у триолей), комментарии //, запятые перед ] и }, «умные» кавычки.
    Возвращает (piece, [что починено])."""
    try:
        return llm_planner.parse_plan(text), []
    except Exception as first:
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
        raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
        fixed, notes = raw, []
        new = re.sub(r'(?<!["\w.])(\d+)\s*/\s*(\d+)(?![\w"])',
                     lambda g: repr(round(int(g.group(1)) / int(g.group(2)), 4)) if int(g.group(2)) else g.group(0), fixed)
        if new != fixed:
            fixed, notes = new, notes + ["дроби длительностей (например 1/3) заменены числами"]
        new = re.sub(r'(?m)\s*//[^\n"]*$', "", fixed)
        if new != fixed:
            fixed, notes = new, notes + ["убраны комментарии //"]
        new = re.sub(r",\s*([\]}])", r"\1", fixed)
        if new != fixed:
            fixed, notes = new, notes + ["убраны лишние запятые"]
        new = fixed.replace("\u201c", '"').replace("\u201d", '"')
        if new != fixed:
            fixed, notes = new, notes + ["заменены типографские кавычки"]
        try:
            return json.loads(fixed), notes
        except json.JSONDecodeError as e:
            a = max(0, e.pos - 60)
            raise ValueError("%s; место ошибки: …%s…" % (first, fixed[a:e.pos + 40].replace("\n", " "))) from None


def partial_piece(text):
    """Оборванный ответ (модель не дописала JSON или сократила его «...»): заголовок и все ЦЕЛЫЕ такты до обрыва.
    Возвращает (piece, число тактов) или (None, 0)."""
    i = text.find('"bars"')
    if i < 0:
        return None, 0
    j = text.find("[", i)
    dec, bars, pos = json.JSONDecoder(), [], j + 1
    while j >= 0:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        try:
            obj, pos = dec.raw_decode(text, pos)
        except ValueError:
            break
        if not isinstance(obj, dict):
            break
        bars.append(obj)
    if not bars:
        return None, 0
    head = {}
    for k in ("title", "key", "time", "pedal"):
        m = re.search(r'"%s"\s*:\s*"([^"]*)"' % k, text)
        if m:
            head[k] = m.group(1)
    m = re.search(r'"tempo"\s*:\s*(\d+)', text)
    if m:
        head["tempo"] = int(m.group(1))
    head["bars"] = bars
    return head, len(bars)


def _continue(call, provider, model, api_key, user, piece, want, rec):
    """Дописать оборванную пьесу: модель получает уже написанные такты и пишет следующие."""
    for _ in range(CONT_MAX):
        n = len(piece["bars"])
        if n >= want:
            break
        ask = (user + "\n\nYour previous answer stopped after bar %d of %d (it was cut off). Bars 1-%d are below; "
               "do NOT repeat them. Continue the SAME piece (same key, style, motifs, plan of sections) and write ONLY "
               "bars %d-%d as one JSON object {\"bars\": [...]}. Never abbreviate, never write '...'.\n"
               "Already written:\n%s" % (n, want, n, n + 1, want, json.dumps(piece["bars"], ensure_ascii=False,
                                                                          separators=(",", ":"))))
        text = call(provider, model, api_key, SYSTEM, ask)
        rec["continued"] = rec.get("continued", 0) + 1
        try:
            more = parse_piece(text)[0].get("bars") or []
        except Exception:
            more = (partial_piece(text)[0] or {}).get("bars") or []
        if not more:
            break
        piece["bars"].extend(more[: want - n])
    return piece


def compose(request, bars=16, key=None, time_sig=None, tempo=None, variant=1, provider=None, model=None,
            api_key=None, call=None, out_dir=None, extra_check=None, skip_rhythm=False):
    """Сочинить пьесу. extra_check(midi) -> (сведения, серьёзные, мелкие) — дополнительная проверка (похожесть на
    образец); skip_rhythm — не требовать «живого» ритма (образец сам спокойный, как «Лунная»). Возвращает словарь: midi (путь), piece (JSON), info, fixes, serious, minor, rounds (что
    отвечала модель), served (имя модели из ответа сервиса). Исключение — если ни одна попытка не дала нот."""
    if not (provider and api_key and model):
        provider, api_key, model = llm_planner.configured_provider()
    if call is None:      # длинная пьеса пишется дольше плана оркестровки: ждём до 4 минут
        # пьеса длиннее плана оркестровки, а размышления модели входят в лимит ответа (12.89): лимит 48000, ждём до 10 мин;
        # если ответ всё же пуст по лимиту — следующие запросы с меньшими размышлениями (effort low)
        call = lambda p, m, k, sy, us: llm_planner.call_model(   # noqa: E731
            p, m, k, sy, us, timeout=600, max_tokens=MAX_TOKENS,
            extra={"output_config": {"effort": "low"}} if _LOW_EFFORT[0] and p == "claude" else None)
    if not (provider and api_key and model):
        raise RuntimeError("модель не настроена: в Secrets нужны PLANNER_PROVIDER, PLANNER_MODEL и ключ")
    out_dir = out_dir or tempfile.mkdtemp(prefix="compose_")
    user = user_text(request, bars, key, time_sig, tempo, variant)
    rounds, best = [], None
    llm_planner.MODELS_SERVED.clear()
    _LOW_EFFORT[0] = False
    for r in range(MAX_ROUNDS):
        text = call(provider, model, api_key, SYSTEM, user)
        rec = {"round": r + 1}
        try:
            try:
                piece, repaired = parse_piece(text)
            except Exception as e0:
                piece, got = partial_piece(text)
                if not piece or got >= bars:
                    raise
                stop = llm_planner.LAST_STOP[0]
                rec["cut_after"] = got
                piece = _continue(call, provider, model, api_key, user, piece, bars, rec)
                repaired = ["ответ модели оборвался после такта %d%s; остальные такты дописаны отдельным запросом "
                            "(%d)" % (got, " (предел длины ответа)" if stop in ("max_tokens", "length") else "",
                                      rec.get("continued", 0))]
                if len(piece["bars"]) < bars:
                    repaired.append("дописать удалось только до такта %d" % len(piece["bars"]))
            path = os.path.join(out_dir, "piece_%d.mid" % (r + 1))
            info, fixes = to_midi(piece, path)
            fixes = ["в ответе модели: " + x for x in repaired] + fixes
            serious, minor = check(info, fixes, path, bars, skip_rhythm=skip_rhythm)
            extra = None
            if extra_check:
                try:
                    extra, s2, m2 = extra_check(path)
                    serious, minor = serious + s2, minor + m2
                except Exception as e:
                    minor = minor + ["Дополнительная проверка не выполнилась: %s" % e]
            rec.update(ok=True, serious=serious, minor=minor)
            cand = {"midi": path, "piece": piece, "info": info, "fixes": fixes, "serious": serious, "minor": minor,
                    "extra": extra}
            if best is None or len(serious) < len(best["serious"]):
                best = cand
        except Exception as e:
            if not (text or "").strip() and llm_planner.LAST_STOP[0] in ("max_tokens", "length"):
                _LOW_EFFORT[0] = True        # модель истратила лимит на размышления: дальше размышлять меньше
                rec["low_effort_next"] = True
            rec.update(ok=False, error="%s: %s (длина ответа %d знаков, причина конца: %s; конец ответа: …%s)" % (
                type(e).__name__, e, len(text or ""), llm_planner.LAST_STOP[0], (text or "")[-120:].replace("\n", " ")),
                answer=text[:600])
            serious = ["Your answer is not valid JSON (%s). Send ONLY the JSON object; durations as decimal numbers "
                       "(0.333 for a triplet eighth, never 1/3); no comments." % e]
        rounds.append(rec)
        if best is not None and not best["serious"]:
            break
        user = user + "\n\nYour previous answer had problems, please rewrite the whole piece:\n- " + "\n- ".join(serious)
    if best is None:
        raise RuntimeError("модель не прислала пьесу, которую можно прочитать: " + (rounds[-1].get("error") or ""))
    best["rounds"] = rounds
    best["served"] = sorted(set(llm_planner.MODELS_SERVED))
    best["provider"], best["model"] = provider, model
    return best


TARGETS = [   # что сделать с пьесой по словам запроса (эвристика): (слова, режим, состав ансамбля или солист)
    (("струнный квартет",), "ensemble", "quartet_string"),
    (("фортепианный квартет",), "ensemble", "quartet_piano"),
    (("квартет", "флейт"), "ensemble", "quartet_flute"),
    (("квартет", "гобо"), "ensemble", "quartet_oboe"),
    (("квартет",), "ensemble", "quartet_string"),
    (("струнное трио",), "ensemble", "trio_string"),
    (("трио",), "ensemble", "trio_piano"),
    (("дуэт", "виолончел", "скрипк"), "ensemble", "duo_violin_cello"),
    (("скрипк", "фортепиано"), "ensemble", "duo_violin_piano"),
    (("виолончел", "фортепиано"), "ensemble", "duo_cello_piano"),
    (("флейт", "фортепиано"), "ensemble", "duo_flute_piano"),
    (("флейт",), "orch", "Flute"), (("кларнет",), "orch", "Clarinet"), (("гобо",), "orch", "Oboe"),
    (("виолончел",), "orch", "Cello"), (("скрипк",), "orch", "Violin I"), (("болеро",), "orch", "Bolero"),
    (("оркестр",), "orch", None),
]


def suggest_target(request):
    """По словам запроса: ('orch', солист|None) / ('ensemble', состав) / ('piano', None)."""
    t = (request or "").lower()
    for words, mode, what in TARGETS:
        if all(w in t for w in words):
            if mode == "ensemble" and "оркестр" in t:
                continue
            return mode, what
    return "piano", None


# ---------------- шаблон запроса (2026-11-21): структура по образцу промтов Suno, но для нот ----------------
TEMPLATE = """[Паспорт]
Жанр и ориентир: русский романс-элегия, в духе Глинки и раннего Рахманинова
Тональность: ре минор
Размер: 3/4
Темп: 66, свободно, с дыханием в концах фраз
Длина: 32 такта
Характер: одиночество, тихая жалоба, в середине надежда, в конце смирение

[Зерно — главный мотив]
Три ноты: ля – си-бемоль – ля (вздох вниз), ритм «четверть с точкой, восьмая, четверть».
Мотив повторяется на разной высоте, но не дважды одинаково подряд.

[A — Жалоба, такты 1–8]
Динамика: pp
Гармония: Dm – Gm/Bb – A7 – Dm | Dm – Bb – Gm6 – A7 (полукаденция в такте 8)
Мелодия: средний регистр (ре первой – ре второй октавы), в основном шагами, вершина в такте 6
Левая рука: бас на первую долю, тихий аккорд на вторую и третью

[A' — Повтор с дыханием, такты 9–16]
Динамика: p → mp
Гармония: как в A, в такте 14 отклонение в фа мажор (C7 – F), возврат Gm – A7 – Dm
Мелодия: тот же мотив, вершина выше (фа второй октавы)
Левая рука: разложенные аккорды восьмыми

[B — Надежда, такты 17–24]
Динамика: mf, крещендо к такту 22
Гармония: F – C/E – Dm – Bb | Gm – C7 – F, затем E7 – A7
Мелодия: новая, светлая, шире; синкопы в тактах 19 и 21; кульминация в такте 22 (ля второй октавы)
Левая рука: подголосок восьмыми в среднем голосе

[A'' — Возвращение и смирение, такты 25–32]
Динамика: mp → pp, замедление в последних двух тактах
Гармония: Dm – Gm – Dm/A – A7 | Dm – Bb – A7 – Dm (полная каденция)
Мелодия: мотив из A, ниже и короче; последняя нота — ре первой октавы на весь такт
Левая рука: бас и тянущиеся аккорды, всё реже

[Запреты]
Без параллельных октав и квинт между мелодией и басом.
Без одинакового ритма больше двух тактов подряд.
Без скачков мелодии больше октавы.
Не больше 4 нот в руке.
Без джазовых аккордов и без модуляций дальше фа мажора."""


def template_params(text):
    """Из [Паспорт] шаблона: число тактов, тональность, размер, темп (None — не указано). Если [Паспорт] нет — {}."""
    t = text or ""
    if "[паспорт]" not in t.lower():
        return {}
    out = {}
    m = re.search(r"Длина\s*:\s*(\d+)", t, re.I)
    if m:
        out["bars"] = int(m.group(1))
    else:      # по последнему такту разделов «такты 25–32»
        ends = [int(x) for x in re.findall(r"такт\w*\s+\d+\s*[–—-]\s*(\d+)", t, re.I)]
        if ends:
            out["bars"] = max(ends)
    m = re.search(r"Тональность\s*:\s*([^\n]+)", t, re.I)
    if m and _key(m.group(1).strip()):
        out["key"] = m.group(1).strip()
    m = re.search(r"Размер\s*:\s*(\d+\s*/\s*\d+)", t, re.I)
    if m:
        out["time"] = m.group(1).replace(" ", "")
    m = re.search(r"Темп\s*:\s*(\d+)", t, re.I)
    if m:
        out["tempo"] = int(m.group(1))
    return out
