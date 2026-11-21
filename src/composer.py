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

MAX_ROUNDS = 2          # запросов к модели на одну пьесу (второй — только если первая попытка с серьёзными замечаниями)
TPB = 480
DYN = {"pp": 36, "p": 46, "mp": 58, "mf": 70, "f": 84, "ff": 98}        # эвристика
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
3. Left hand: accompaniment that fits the style (waltz "bass-chord-chord", broken chords, Alberti bass, sustained chords,
   arpeggios). Left hand mostly between E1 and C5. Bass on strong beats.
4. Playability: in each hand the notes sounding together span at most 14 semitones and at most 4 notes.
5. Harmony: stay in the key with clear functional harmony (I, IV, V, ii, vi, secondary dominants allowed); modulate only
   if asked; avoid parallel fifths and octaves between melody and bass.
6. "dyn" per bar: pp, p, mp, mf, f or ff, following the shape of the music. Use "pedal": "bar" for lyrical pieces.
7. Write exactly the requested number of bars. No text outside the JSON."""


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
            if hand == "rh" and not notes:
                stats["empty_rh"] += 1
            for off, dur, ps in notes:
                for p in ps:
                    q = _fold(p, *rng)
                    if q != p:
                        stats["folded"] += 1
                    stats[hand].append(q)
                    s, e = int(round((start + off) * TPB)), int(round((start + off + dur) * TPB))
                    ev.append((s, 1, mido.Message("note_on", note=q, velocity=max(1, min(127, vel)), channel=0)))
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
    return info, fixes


def check(info, fixes, midi_path, want_bars):
    """Замечания к пьесе: (серьёзные, мелкие). Серьёзные уходят модели на переписывание."""
    serious, minor = [], []
    if want_bars and info["bars"] != want_bars:
        serious.append("Тактов %d, а просили %d." % (info["bars"], want_bars))
    if info["bars"] < 4:
        serious.append("Слишком коротко: %d тактов." % info["bars"])
    if info["empty_melody_bars"] > max(1, info["bars"] // 8):
        serious.append("В %d тактах у правой руки нет нот (нет мелодии)." % info["empty_melody_bars"])
    sh = info.get("scale_share")
    if sh is not None and sh < 0.85:
        minor.append("В гамме %s только %.0f%% нот (много случайных знаков)." % (info.get("key"), 100 * sh))
    bar_fix = [f for f in fixes if f.startswith("такт")]
    if len(bar_fix) > max(2, info["bars"] // 5):
        serious.append("Счёт в тактах не сходится в %d местах (длительности не складываются в размер)." % len(bar_fix))
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


def compose(request, bars=16, key=None, time_sig=None, tempo=None, variant=1, provider=None, model=None,
            api_key=None, call=llm_planner.call_model, out_dir=None):
    """Сочинить пьесу. Возвращает словарь: midi (путь), piece (JSON), info, fixes, serious, minor, rounds (что
    отвечала модель), served (имя модели из ответа сервиса). Исключение — если ни одна попытка не дала нот."""
    if not (provider and api_key and model):
        provider, api_key, model = llm_planner.configured_provider()
    if not (provider and api_key and model):
        raise RuntimeError("модель не настроена: в Secrets нужны PLANNER_PROVIDER, PLANNER_MODEL и ключ")
    out_dir = out_dir or tempfile.mkdtemp(prefix="compose_")
    user = user_text(request, bars, key, time_sig, tempo, variant)
    rounds, best = [], None
    llm_planner.MODELS_SERVED.clear()
    for r in range(MAX_ROUNDS):
        text = call(provider, model, api_key, SYSTEM, user)
        rec = {"round": r + 1}
        try:
            piece = llm_planner.parse_plan(text)
            path = os.path.join(out_dir, "piece_%d.mid" % (r + 1))
            info, fixes = to_midi(piece, path)
            serious, minor = check(info, fixes, path, bars)
            rec.update(ok=True, serious=serious, minor=minor)
            cand = {"midi": path, "piece": piece, "info": info, "fixes": fixes, "serious": serious, "minor": minor}
            if best is None or len(serious) < len(best["serious"]):
                best = cand
        except Exception as e:
            rec.update(ok=False, error="%s: %s" % (type(e).__name__, e), answer=text[:600])
            serious = ["Ответ не удалось прочитать как JSON пьесы (%s). Пришлите только JSON по формату." % type(e).__name__]
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
