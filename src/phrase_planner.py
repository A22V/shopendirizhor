"""
Phrase planner v0.2 (viola in string-led phrases)
Phrase planner v0.1 for the 'chamber_mini' ensemble.

Step 1  map   : per-bar features -> phrase boundaries -> phrase kind (intro / lyric / figuration / run)
Step 2  plan  : one orchestration scene per phrase (melody colour, accompaniment, bass, figuration,
                dynamics). The plan is plain JSON, so a person or an LLM can edit it by hand and pass it
                back to the orchestrator.
All thresholds are author heuristics (not from the source book) and are listed in THRESHOLDS.
"""
import sys
sys.path.insert(0, "/mnt/user-data/outputs")
import validator

RANGES = validator.RANGES_UNVERIFIED            # UNVERIFIED sounding ranges (MIDI)
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
            cost = _oor(pitches, name, base + s) + (4 if s else 0) + (3 if c == prev else 0)
            if c == "cello+bassoon" and mean > 66: cost += 100      # low colour only for low melodies
            if c == "violin+flute" and mean < 76: cost += 100       # brilliant colour only for high melodies
            if c == "violin" and kind != "run" and mean < 80: cost += 50
            if best is None or cost < best[0]:
                best = (cost, c, s)
    return best[1], best[2]


def scene(kind, color, shift, climax):
    """Specs are [instrument, octave shift, share of the phrase after which the instrument enters]."""
    enter = 0.0 if climax else 0.5
    mel = [[n, b + shift] for n, b in COLORS[color]] if color else []
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
        out["melody"] = out["melody"] + [["Flute", 12 + shift, 0.0]]
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
        phrases.append({"id": k, "bars": [a, b], "kind": kind, "climax": False,
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
            p.update(scene(p["kind"], color, shift, p["climax"]))
            why.append("melody colour '%s' chosen by register fit, alternating colours (G02, G05, MG04)" % color)
            if shift: why.append("whole phrase moved by %+d semitones so the contour is kept (G01)" % shift)
            if p["kind"] == "figuration": why.append("arpeggio accompaniment passed on as figuration instead of static chords")
            if p["kind"] == "run": why.append("fast passage to one agile soloist, strings hold long notes (W04, QX07)")
            if p["climax"]: why.append("climax: all layers from the first bar, flute doubles the melody (OR11)")
            if color in STRING_LED: why.append("melody in strings -> harmony in clarinet/horn (OR03)")
            else: why.append("melody in winds -> harmony in strings (OR03)")
        p["why"] = why
    # breath fix (QX04): a wind melody in a long phrase hands over to strings halfway through
    WIND_MEL = {"Flute", "Oboe", "Clarinet", "Bassoon"}
    for p in phrases:
        if p["kind"] == "intro" or not p.get("melody"): continue
        a, b = p["bars"]
        if (b - a + 1) < 4: continue
        if not any(spec[0] in WIND_MEL for spec in p["melody"]): continue
        winds = [[spec[0], spec[1], 0.0, 0.5] for spec in p["melody"] if spec[0] in WIND_MEL]
        strings = [spec for spec in p["melody"] if spec[0] not in WIND_MEL]
        if not strings:
            strings = [["Violin I", 0, 0.0]]
        second_half = [[s[0], s[1], 0.5] for s in strings]
        p["melody"] = winds + second_half
        p["why"] = p.get("why", []) + ["wind melody hands over to strings halfway (breath, QX04)"]
    # bassoon bass (QX04): in longer phrases the bassoon stops halfway and the cello takes over
    for p in phrases:
        if p["kind"] == "intro" or not p.get("bass"): continue
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
    for p, lv in zip(phrases, levels):
        p["level"] = lv
        p.pop("_pit", None)
    return {"piece": {"bars": len(feats), "time_signatures": meta["tsigs"], "tempo_changes": len(meta["tempos"]),
                      "thresholds": THRESHOLDS},
            "phrases": phrases}


def table(plan):
    rows = ["bars      kind        colour            level  climax"]
    for p in plan["phrases"]:
        rows.append("%-9s %-11s %-17s %-6s %s" % ("%d-%d" % tuple(p["bars"]), p["kind"], p["color"] or "-",
                                                  p["level"], "yes" if p["climax"] else ""))
    return "\n".join(rows)
