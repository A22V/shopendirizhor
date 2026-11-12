"""
Phrase planner v0.2 (viola in string-led phrases)
Phrase planner v0.1 for the 'chamber_mini' ensemble.

Step 1  map   : per-bar features -> phrase boundaries -> phrase kind (intro / lyric / figuration / run)
Step 2  plan  : one orchestration scene per phrase (melody colour, accompaniment, bass, figuration,
                dynamics). The plan is plain JSON, so a person or an LLM can edit it by hand and pass it
                back to the orchestrator.
All thresholds are author heuristics (not from the source book) and are listed in THRESHOLDS.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # модули рядом (раньше здесь был путь старой среды)
import validator

RANGES = validator.RANGES_OLD                   # planner table (unchanged); the orchestrator may place notes by Berlioz ranges
KEYMAP = {"Flute": "flute", "Oboe": "oboe", "Clarinet": "clarinet", "Bassoon": "bassoon", "Horn": "horn",
          "Violin I": "violin", "Violin II": "violin", "Viola": "viola", "Cello": "cello",
          "Double Bass": "double_bass"}
LEVELS = ["mp", "mf", "f"]
THRESHOLDS = {"boundary_score": 3, "min_phrase_bars": 2, "max_phrase_bars": 8,
              "run_notes_per_beat": 3.0, "figuration_notes_per_beat": 1.2}

# melody colours: (instrument, octave shift) pairs
COLORS = {
    "strings+oboe":   [("Violin I", 0), ("Oboe", 0)],
    "clarinet+flute": [("Clarinet", 0), ("Flute", 12)],
    "cello+bassoon":  [("Cello", 0), ("Bassoon", 0)],
    "violin+flute":   [("Violin I", 0), ("Flute", 12)],
    "flute":          [("Flute", 0)],
    "clarinet":       [("Clarinet", 0)],
    "violin":         [("Violin I", 0)],
}
import os as _os
COMFORT = _os.environ.get("ORCH_COMFORT") == "1"   # optional, OFF by default; heuristic, not from a book
FLUTE_DOUBLE_TOP = 80                                # the flute doubles an octave up only while the doubled melody averages below G#5
COMFORT_TOP = 84                                     # C6: above this the flute doubling goes up an octave only if it stays below it


def _flute_up(mean, shift):
    """Octave by which the flute doubles the melody (12 by default). With ORCH_COMFORT=1 the flute stays in unison
    when the doubled melody would sit above C6 on average (heuristic: complaint about piercing high notes, 2026-10-31)."""
    if COMFORT and mean is not None and mean + shift + 12 > FLUTE_DOUBLE_TOP:
        return 0
    return 12


# ORCH_FAST_HOLD=1 (OFF by default): in a FAST phrase the melody is not handed from one timbre to another halfway through.
# "Fast" = melody notes per second of the phrase >= FAST_NPS. 4.0 is an author heuristic, not from a book:
# it falls between the K.545 excerpt (4.7 and 7.6 notes/s) and the nocturne (1.2-2.4 notes/s).
FAST_HOLD = _os.environ.get("ORCH_FAST_HOLD") == "1"
FAST_NPS = 4.0
# ORCH_MELODY_ONE=1 (OFF by default, 2026-11-07): the same rule for EVERY phrase, not only fast ones: the melody is not handed
# from a wind to a string halfway through a phrase; the strings carry the whole phrase and a wind only doubles it while the
# phrase fits into one breath. Reason: the user heard the melody "jumping" between instruments every two bars (built-in plan:
# about 24 handovers in 53 bars). Changing colour only at phrase boundaries is a heuristic; not confirmed by a book page.
MELODY_ONE = _os.environ.get("ORCH_MELODY_ONE") == "1"
# ORCH_FAST_VIOLIN=1 (OFF by default): in a fast phrase the melody is led by Violin I only (Czerny, School of Practical
# Composition vol. 3, p. 22: fast and brilliant passages go to the strings; confirmed). Clarinet, oboe, bassoon and horn get
# no fast melody but hold harmony (long notes) so they do not fall silent (QX06).
# ORCH_FAST_FLUTE=1 (needs ORCH_FAST_VIOLIN=1): the flute doubles that melody an octave up as colour (Berlioz calls the flute the
# most agile wind; the two books differ, so this is a separate switch). It rests one bar in every FLUTE_RUN_BEATS beats (breath).
FAST_VIOLIN = _os.environ.get("ORCH_FAST_VIOLIN") == "1"
FAST_FLUTE = FAST_VIOLIN and _os.environ.get("ORCH_FAST_FLUTE") == "1"
FLUTE_RUN_BEATS = 12.0                               # heuristic: stays under validator.MAX_WIND_RUN_BEATS (16)


STRING_LED = {"strings+oboe", "cello+bassoon", "violin+flute", "violin"}


def tempo_at(meta, off):
    cur = meta["tempos"][0][1] if meta["tempos"] else 60
    for o, bpm in meta["tempos"]:
        if o <= off + 1e-9:
            cur = bpm
    return cur


# ---------------------------------------------------------------- step 1: map
def bar_features(melody, meta):
    out = []
    for i, (st, ln) in enumerate(meta["bars"]):
        en = st + ln
        mel = [m for m in melody if st - 1e-6 <= m["offset"] < en - 1e-6]
        fig = [f for f in meta["fig"] if st - 1e-6 <= f["offset"] < en - 1e-6]
        pit = [m["pitch"] for m in mel]
        last_end = max((m["offset"] + m["dur"] for m in mel), default=None)
        out.append({"bar": i + 1, "start": st, "len": ln, "mel_notes": len(mel),
                    "mel_density": len(mel) / ln,
                    "mel_mean": (sum(pit) / len(pit)) if pit else None,
                    "last_long": bool(mel) and mel[-1]["dur"] >= 2.0,
                    "gap_end": max(0.0, en - last_end) if last_end is not None else ln,
                    "fig_density": len(fig) / ln,
                    "tempo_drop": tempo_at(meta, en - 0.01) < 0.9 * tempo_at(meta, st)})
    return out


def detect_phrases(feats):
    n = len(feats)
    lo_len, hi_len = THRESHOLDS["min_phrase_bars"], THRESHOLDS["max_phrase_bars"]
    score = [0] * n                                   # score[i]: boundary AFTER bar index i
    for i in range(n - 1):
        f, g = feats[i], feats[i + 1]
        s = 0
        if f["mel_notes"] and f["gap_end"] >= 1.0: s += 2     # melody stops before the barline
        if f["last_long"]: s += 2                              # long final note (cadence-like)
        if f["mel_notes"] == 0 and g["mel_notes"] > 0: s += 3  # melody enters
        if f["mel_notes"] > 0 and g["mel_notes"] == 0: s += 2  # melody drops out
        if abs(f["len"] - g["len"]) > 1e-6: s += 2             # meter change
        if f["tempo_drop"]: s += 2                             # ritardando
        if (i + 1) % 4 == 0: s += 1                            # weak metric prior
        score[i] = s
    cuts = []
    for i in sorted((i for i in range(n - 1) if score[i] >= THRESHOLDS["boundary_score"]), key=lambda i: -score[i]):
        if all(abs(i - c) >= lo_len for c in cuts):
            cuts.append(i)
    cuts.sort()
    changed = True
    while changed:                                    # split phrases that are too long
        changed = False
        bounds = [-1] + cuts + [n - 1]
        for a, b in zip(bounds, bounds[1:]):
            if b - a > hi_len:
                cand = [i for i in range(a + 3, min(a + hi_len - 2, b - 3) + 1) if 0 <= i < n - 1] or [a + 4]
                cut = max(cand, key=lambda i: (score[i], -abs(i - (a + 4))))
                cuts.append(cut); cuts.sort(); changed = True
                break
    bounds = [-1] + cuts + [n - 1]
    return [(a + 2, b + 1) for a, b in zip(bounds, bounds[1:])], score   # 1-based inclusive bar ranges


# ---------------------------------------------------------------- step 2: plan
def _oor(pitches, name, shift):
    lo, hi = RANGES[KEYMAP[name]]
    return sum(1 for p in pitches if not (lo <= p + shift <= hi))


def choose_color(kind, pitches, mean, prev):
    cands = ["flute", "clarinet", "violin"] if kind == "run" else list(COLORS)
    if kind == "run": cands = ["flute", "clarinet", "violin"]
    else: cands = ["strings+oboe", "clarinet+flute", "cello+bassoon", "violin+flute", "violin"]
    best = None
    for c in cands:
        name, base = COLORS[c][0]
        for s in (0, -12, 12, -24, 24):
            shift_cost = (4 * (abs(s) // 12) + (6 if mean + base + s > COMFORT_TOP else 0)) if COMFORT else (4 if s else 0)
            cost = _oor(pitches, name, base + s) + shift_cost + (3 if c == prev else 0)
            if c == "cello+bassoon" and mean > 66: cost += 100      # low colour only for low melodies
            if c == "violin+flute" and mean < 76: cost += 100       # brilliant colour only for high melodies
            if c == "violin" and kind != "run" and mean < 80: cost += 50
            if best is None or cost < best[0]:
                best = (cost, c, s)
    return best[1], best[2]


def scene(kind, color, shift, climax, mean=None):
    """Specs are [instrument, octave shift, share of the phrase after which the instrument enters]."""
    enter = 0.0 if climax else 0.5
    mel = [[n, (_flute_up(mean, shift) if (n == "Flute" and b == 12) else b) + shift] for n, b in COLORS[color]] if color else []
    string_led = color in STRING_LED
    if kind == "intro":
        return {"melody": [], "bass": [["Cello", 0, 0.0]], "figuration": [["Viola", 0, 0.0]],
                "inner2": [["Horn", 0, 0.5]]}
    if color == "cello+bassoon": bass = [["Double Bass", 0, 0.0]]
    elif string_led: bass = [["Cello", 0, 0.0], ["Double Bass", -12, enter]]
    else: bass = [["Bassoon", 0, 0.0], ["Double Bass", -12, enter]]
    out = {"melody": mel, "bass": bass}
    if kind == "figuration":
        if string_led: out.update(figuration=[["Clarinet", 0, 0.0]], inner2=[["Horn", 0, 0.0]])
        else: out.update(figuration=[["Viola", 0, 0.0]], inner1=[["Violin II", 0, 0.0]])
    elif kind == "run":
        if string_led: out.update(inner1=[["Clarinet", 0, 0.0]], inner2=[["Horn", 0, 0.0]])
        else: out.update(inner1=[["Violin II", 0, 0.0]], inner2=[["Viola", 0, 0.0]])
        out["bass"] = [["Cello", 0, 0.0]]
    else:                                                                     # lyric
        if string_led: out.update(inner1=[["Viola", 0, 0.0]], inner2=[["Horn", 0, enter]])
        else: out.update(inner1=[["Violin II", 0, 0.0]], inner2=[["Viola", 0, enter]])
    if climax and not any(n == "Flute" for n, _ in COLORS[color]) and kind != "run":
        out["melody"] = out["melody"] + [["Flute", _flute_up(mean, shift) + shift, 0.0]]
    return out


def phrase_levels(phrases):
    valid = [p["mel_mean"] for p in phrases if p["mel_mean"] is not None]
    lo, hi = min(valid), max(valid)
    raw = []
    for p in phrases:
        if p["mel_mean"] is None: r = 0
        else:
            x = 0.5 if hi == lo else (p["mel_mean"] - lo) / (hi - lo)
            r = 0 if x < 0.33 else 1 if x < 0.66 else 2
        raw.append(2 if p["climax"] else r)
    out = [raw[0]]
    for r in raw[1:]:                                 # at most one step between neighbouring phrases
        cur = out[-1]
        out.append(r if abs(r - cur) <= 1 else cur + (1 if r > cur else -1))
    return [LEVELS[x] for x in out]


ABS_MP, ABS_MF = 58, 84     # сила нажатия: ниже 58 — mp, ниже 84 — mf, иначе f (эвристика)


def velocity_levels(phrases, bar_velocity):
    """Уровень фразы по средней силе нажатия пианиста в её тактах; соседние фразы отличаются не больше чем на шаг."""
    means = []
    for p in phrases:
        a, b = p["bars"]
        vs = [bar_velocity[bi] for bi in range(a - 1, b) if bi in bar_velocity]
        means.append(sum(vs) / len(vs) if vs else None)
    valid = [m for m in means if m is not None]
    if not valid: return phrase_levels(phrases)
    if os.environ.get("ORCH_DYN_PIANO", "").strip().lower() == "abs":
        # 2026-11-12: ступень по самой силе нажатия, а не относительно пьесы (ровная тихая «Лунная» получала mf/f и
        # «кульминацию»). Пороги 58 и 84 — эвристика.
        mid = sum(valid) / len(valid)
        return [LEVELS[0 if (m if m is not None else mid) < ABS_MP else 1 if (m if m is not None else mid) < ABS_MF else 2]
                for m in means]
    lo, hi = min(valid), max(valid)
    raw = []
    for p, m in zip(phrases, means):
        x = 0.5 if m is None or hi - lo < 4 else (m - lo) / (hi - lo)
        r = 0 if x < 0.33 else 1 if x < 0.66 else 2
        raw.append(2 if p["climax"] else r)
    out = [raw[0]]
    for r in raw[1:]:
        cur = out[-1]
        out.append(r if abs(r - cur) <= 1 else cur + (1 if r > cur else -1))
    return [LEVELS[x] for x in out]


def make_plan(s, events, melody, meta):
    feats = bar_features(melody, meta)
    ranges, score = detect_phrases(feats)
    phrases = []
    for k, (a, b) in enumerate(ranges, 1):
        fs = feats[a - 1:b]
        beats = sum(f["len"] for f in fs)
        t0, t1 = fs[0]["start"], fs[-1]["start"] + fs[-1]["len"]
        pit = [m["pitch"] for m in melody if t0 - 1e-6 <= m["offset"] < t1 - 1e-6]
        dens = len(pit) / beats
        fig = sum(f["fig_density"] * f["len"] for f in fs) / beats
        if not pit: kind = "intro"
        elif dens >= THRESHOLDS["run_notes_per_beat"]: kind = "run"
        elif fig >= THRESHOLDS["figuration_notes_per_beat"]: kind = "figuration"
        else: kind = "lyric"
        secs = sum(f["len"] * 60.0 / tempo_at(meta, f["start"]) for f in fs)
        phrases.append({"id": k, "bars": [a, b], "kind": kind, "climax": False, "_nps": len(pit) / secs if secs else 0.0,
                        "mel_mean": (sum(pit) / len(pit)) if pit else None,
                        "mel_density": round(dens, 2), "fig_density": round(fig, 2), "_pit": pit})
    singing = [p for p in phrases if p["kind"] in ("lyric", "figuration") and p["mel_mean"] is not None
               and (p["bars"][1] - p["bars"][0] + 1) >= 3]          # a climax needs at least 3 bars
    if len(phrases) >= 4 and singing:
        max(singing, key=lambda p: p["mel_mean"])["climax"] = True
    prev = None
    for p in phrases:
        why = []
        if p["kind"] == "intro":
            p.update(scene("intro", None, 0, False)); p["color"] = None
            why.append("intro: no melody; left-hand figuration goes to viola, cello holds the bass (OR01)")
        else:
            color, shift = choose_color(p["kind"], p["_pit"], p["mel_mean"], prev)
            p["color"], prev = color, color
            p.update(scene(p["kind"], color, shift, p["climax"], p["mel_mean"]))
            why.append("melody colour '%s' chosen by register fit, alternating colours (G02, G05, MG04)" % color)
            if shift: why.append("whole phrase moved by %+d semitones so the contour is kept (G01)" % shift)
            if p["kind"] == "figuration": why.append("arpeggio accompaniment passed on as figuration instead of static chords")
            if p["kind"] == "run": why.append("fast passage to one agile soloist, strings hold long notes (W04, QX07)")
            if p["climax"]: why.append("climax: all layers from the first bar, flute doubles the melody (OR11)")
            if color in STRING_LED: why.append("melody in strings -> harmony in clarinet/horn (OR03)")
            else: why.append("melody in winds -> harmony in strings (OR03)")
        p["why"] = why
    # fast phrases led by Violin I (ORCH_FAST_VIOLIN): winds keep to long harmony notes, no fast melody
    if FAST_VIOLIN:
        flute_run = 0.0
        for p in phrases:
            if p["kind"] == "intro" or not p.get("melody") or p["_nps"] < FAST_NPS:
                flute_run = 0.0; continue
            a, b = p["bars"]
            def add(role, name, shift, enter=0.0, leave=None):
                specs = [list(s) for s in p.get(role, []) if s[0] != name]
                specs.append([name, shift, enter] if leave is None else [name, shift, enter, leave])
                p[role] = specs
            p["melody"] = [["Violin I", 0, 0.0]]
            # long harmony notes (roles pad1/pad2 = inner1/inner2 pitches held, see orchestrator.hold_pads); shifts keep the
            # winds below the melody and avoid unison with the strings (heuristic)
            p["pad1"] = [["Clarinet", -12, 0.0], ["Oboe", 0, 0.0]]
            p["pad2"] = [["Horn", -12, 0.0], ["Bassoon", -12, 0.0]]
            p["_fast"] = True
            why = ["fast phrase (%.1f notes/s): melody to Violin I (Czerny p.22); clarinet, oboe, horn and bassoon "
                   "hold long harmony notes (heuristic threshold)" % p["_nps"]]
            if FAST_FLUTE:                                   # flute colour, an octave up, resting one bar per FLUTE_RUN_BEATS
                spans, cur = [], None
                for bi in range(a, b + 1):
                    ln = feats[bi - 1]["len"]
                    if flute_run + ln > FLUTE_RUN_BEATS + 1e-9:
                        flute_run = 0.0; cur = None          # this bar is a rest for the flute
                        continue
                    flute_run += ln
                    if cur is None: cur = [bi, bi]; spans.append(cur)
                    else: cur[1] = bi
                n = b - a + 1
                up = _flute_up(p["mel_mean"], 0)
                p["melody"] += [["Flute", up, (s0 - a) / n, ((s1 - a + 1) / n if s1 < b else None)] for s0, s1 in spans]
                why.append("flute doubles the melody %+d semitones as colour, resting a bar after every %d beats (breath)"
                           % (up, FLUTE_RUN_BEATS))
            p["why"] = p.get("why", []) + why
    # breath fix (QX04): a wind melody in a long phrase hands over to strings halfway through
    WIND_MEL = {"Flute", "Oboe", "Clarinet", "Bassoon"}
    for p in phrases:
        if p["kind"] == "intro" or not p.get("melody") or p.get("_fast"): continue
        a, b = p["bars"]
        if (b - a + 1) < 4: continue
        if not any(spec[0] in WIND_MEL for spec in p["melody"]): continue
        winds = [[spec[0], spec[1], 0.0, 0.5] for spec in p["melody"] if spec[0] in WIND_MEL]
        strings = [spec for spec in p["melody"] if spec[0] not in WIND_MEL]
        if not strings:
            strings = [["Violin I", 0, 0.0]]
        if (FAST_HOLD and p["_nps"] >= FAST_NPS) or MELODY_ONE:
            # fast phrase: no handover halfway; the strings carry the whole phrase (no breath needed), a wind only doubles
            # while the phrase fits into one breath (MAX_WIND_RUN_BEATS)
            beats = sum(f["len"] for f in feats[a - 1:b])
            keep = [[s[0], s[1], 0.0] for s in p["melody"] if s[0] in WIND_MEL] if beats <= validator.MAX_WIND_RUN_BEATS else []
            p["melody"] = [[s[0], s[1], 0.0] for s in strings] + keep
            p["why"] = p.get("why", []) + ["fast phrase (%.1f notes/s): melody keeps one carrier, no handover halfway (heuristic)" % p["_nps"]]
            continue
        second_half = [[s[0], s[1], 0.5] for s in strings]
        p["melody"] = winds + second_half
        p["why"] = p.get("why", []) + ["wind melody hands over to strings halfway (breath, QX04)"]
    # bassoon bass (QX04): in longer phrases the bassoon stops halfway and the cello takes over
    for p in phrases:
        if p["kind"] == "intro" or not p.get("bass") or p.get("_fast"): continue
        a, b = p["bars"]
        if (b - a + 1) < 4: continue
        if not any(spec[0] == "Bassoon" for spec in p["bass"]): continue
        bassoon = [["Bassoon", s[1], 0.0, 0.5] for s in p["bass"] if s[0] == "Bassoon"]
        rest = [s for s in p["bass"] if s[0] != "Bassoon"]
        if not any(s[0] == "Cello" for s in rest):
            rest = rest + [["Cello", 0, 0.5]]
        else:
            rest = [[s[0], s[1], 0.5] if s[0] == "Cello" else s for s in rest]
        p["bass"] = bassoon + rest
        p["why"] = p.get("why", []) + ["bassoon bass hands over to cello halfway (breath, QX04)"]
    # viola must play in every phrase (QX06): in cello+bassoon phrases the viola takes the first inner voice
    for p in phrases:
        if p.get("color") == "cello+bassoon" and p.get("inner1") and p["inner1"][0][0] == "Clarinet":
            p["inner1"] = [["Viola", 0, 0.0]]
    levels = phrase_levels(phrases)
    if os.environ.get("ORCH_DYN_PIANO", "") not in ("", "0", "false", "False") and meta.get("bar_velocity"):
        # ORCH_DYN_PIANO=1 (2026-11-10, выкл. по умолчанию): громкость фразы берётся из силы нажатия пианиста
        # (измерение из файла), а не из высоты мелодии. Повод: тестовая пьеса, финал Vivace у рояля самый громкий
        # (нажатие 84–100), план дал «mp» -> провал громкости в оркестре со второй минуты (замер по MP3: −17 дБ у рояля,
        # −27…−31 дБ у оркестра). Шкала: трети между самой тихой и самой громкой фразой (эвристика); кульминация = f.
        levels = velocity_levels(phrases, meta["bar_velocity"])
    for p, lv in zip(phrases, levels):
        p["level"] = lv
        p.pop("_pit", None); p.pop("_nps", None); p.pop("_fast", None)
    return {"piece": {"bars": len(feats), "time_signatures": meta["tsigs"], "tempo_changes": len(meta["tempos"]),
                      "thresholds": THRESHOLDS},
            "phrases": phrases}


def table(plan):
    rows = ["bars      kind        colour            level  climax"]
    for p in plan["phrases"]:
        rows.append("%-9s %-11s %-17s %-6s %s" % ("%d-%d" % tuple(p["bars"]), p["kind"], p["color"] or "-",
                                                  p["level"], "yes" if p["climax"] else ""))
    return "\n".join(rows)
