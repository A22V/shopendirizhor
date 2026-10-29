"""
Orchestrator v0.9 (skyline melody) (rule-based planner) for the 'chamber_mini' ensemble.
Pipeline: piano MIDI/MusicXML -> analysis -> plan -> realization -> validation.
v0.5: harmony is read per beat (works for broken-chord accompaniments), bass/inner voices are
sustained, 4-bar sections with a constant set of instruments, smoothed dynamics, per-instrument
loudness balancing measured on isolated renders, transposed MusicXML, MIDI at sounding pitch.
"""
import sys, json, copy, warnings, bisect, os, subprocess, tempfile
warnings.filterwarnings("ignore")
sys.path.insert(0, "/mnt/user-data/outputs")
from music21 import converter, stream, note, chord, instrument, meter, dynamics, tempo, volume
import validator

RANGES = validator.RANGES_UNVERIFIED  # UNVERIFIED sounding ranges (MIDI)
KEY = {"Flute": "flute", "Oboe": "oboe", "Clarinet": "clarinet", "Bassoon": "bassoon",
       "Horn": "horn", "Violin I": "violin", "Violin II": "violin", "Viola": "viola",
       "Cello": "cello", "Double Bass": "double_bass"}
CLASSES = {"Flute": instrument.Flute, "Oboe": instrument.Oboe, "Clarinet": instrument.Clarinet,
           "Bassoon": instrument.Bassoon, "Horn": instrument.Horn, "Piano": instrument.Piano,
           "Violin I": instrument.Violin, "Violin II": instrument.Violin, "Viola": instrument.Viola,
           "Cello": instrument.Violoncello, "Double Bass": instrument.Contrabass}
SCORE_ORDER = ["Flute", "Oboe", "Clarinet", "Bassoon", "Horn", "Piano",
               "Violin I", "Violin II", "Viola", "Cello", "Double Bass"]
WINDS = {"Flute", "Oboe", "Clarinet", "Bassoon", "Horn"}
MAX_WIND_RUN_BEATS = validator.MAX_WIND_RUN_BEATS
LEVELS = ["mp", "mf", "f"]
PHRASE_BARS = 4
SF2 = "/usr/share/sounds/sf2/FluidR3_GM.sf2"

def fit(m, name):
    lo, hi = RANGES[KEY[name]]
    while m < lo: m += 12
    while m > hi: m -= 12
    return m if lo <= m <= hi else None

# ---------- 1. analysis ----------
def bar_of(starts, off):
    return max(0, bisect.bisect_right(starts, off + 1e-9) - 1)

def analyze(path):
    s = converter.parse(path)
    ms = list(s.parts[0].getElementsByClass(stream.Measure))
    bars, tsigs = [], []
    for m in ms:
        bars.append((float(m.offset), float(m.duration.quarterLength)))
        for ts in m.getElementsByClass(meter.TimeSignature):
            tsigs.append((float(m.offset), ts.ratioString))
    allnotes = []
    for pi, p in enumerate(s.parts):
        for el in p.flatten().notes:
            for pt in (el.pitches if isinstance(el, chord.Chord) else [el.pitch]):
                if el.quarterLength > 0:
                    allnotes.append((float(el.offset), float(el.offset + el.quarterLength), pt.midi, pi))
    total = max(n[1] for n in allnotes)
    if not bars:                                   # no measures: uniform 4/4
        bars = [(float(x), 4.0) for x in range(0, int(total) + 4, 4)]
        tsigs = [(0.0, "4/4")]
    if not tsigs: tsigs = [(0.0, "4/4")]
    tempos = {}
    for mm in s.recurse().getElementsByClass(tempo.MetronomeMark):
        tempos[round(float(mm.getOffsetInHierarchy(s)), 3)] = mm.number     # last mark at an offset wins
    meta = {"bars": bars, "tsigs": tsigs, "tempos": sorted(tempos.items())}
    by_part = {}
    for n in allnotes: by_part.setdefault(n[3], []).append(n[2])
    top_pi = max(by_part, key=lambda k: sum(by_part[k]) / len(by_part[k]))
    # melody = top line across ALL piano tracks (the line can move between the right- and left-hand tracks)
    sky = {}
    for on, off_, midi, pi in allnotes:
        cur = sky.get(on)
        if cur is None or midi > cur[0]:
            sky[on] = (midi, off_ - on)
    melody = [{"offset": on, "dur": dur, "pitch": midi} for on, (midi, dur) in sorted(sky.items())]
    for i in range(len(melody) - 1):                 # trim each melody note so it never overlaps the next one
        gap = melody[i + 1]["offset"] - melody[i]["offset"]
        if melody[i]["dur"] > gap:
            melody[i]["dur"] = gap
    mel_on = [m["offset"] for m in melody]
    def melody_at(b):
        i = bisect.bisect_right(mel_on, b + 0.999) - 1
        while i >= 0:
            m = melody[i]
            if m["offset"] + m["dur"] > b: return m["pitch"]
            i -= 1
        return None
    events, prev1, prev2 = [], 67, 60
    for start, length in bars:
        k = 0
        while k < length - 1e-6:
            b, wl = start + k, min(1.0, length - k)
            k += 1
            ov = [n for n in allnotes if n[0] < b + wl - 1e-6 and n[1] > b + 1e-6]
            if not ov: continue
            on = [n for n in ov if b - 1e-6 <= n[0] < b + wl - 1e-6]
            bass = min(n[2] for n in (on or ov))
            w = {}
            for n in ov:
                amount = min(n[1], b + wl) - max(n[0], b)
                if n[3] != top_pi: amount *= 2
                w[n[2] % 12] = w.get(n[2] % 12, 0) + amount
            w.pop(bass % 12, None)
            pcs = [pc for pc, _ in sorted(w.items(), key=lambda kv: -kv[1])][:2]
            mel = melody_at(b)
            lo, hi = bass, (mel if mel is not None else 84)
            placed = []
            for pc, prev in zip(pcs, (prev1, prev2)):
                cands = [12 * o + pc for o in range(3, 8) if lo < 12 * o + pc < hi]
                if cands: placed.append(min(cands, key=lambda m: abs(m - prev)))
            placed = sorted(set(placed), reverse=True)
            if len(placed) > 0: prev1 = placed[0]
            if len(placed) > 1: prev2 = placed[1]
            events.append({"offset": float(b), "dur": float(wl), "pitches": sorted({n[2] for n in ov}),
                           "bass": bass, "melody": mel, "inner": placed})
    ev_on = [e["offset"] for e in events]
    fig = []
    for n in allnotes:
        if n[3] == top_pi: continue
        i = bisect.bisect_right(ev_on, n[0] + 1e-6) - 1
        if i >= 0 and n[2] > events[i]["bass"]:
            fig.append({"offset": n[0], "dur": n[1] - n[0], "pitch": n[2]})
    fig.sort(key=lambda f: f["offset"])
    meta["fig"] = fig
    return s, events, melody, meta

def bar_dynamics(melody, meta):
    """Smoothed dynamics from melody height: moving average, 3 levels, one step at a time, min 2 bars hold."""
    starts = [b[0] for b in meta["bars"]]
    num, den = {}, {}
    for m in melody:
        b = bar_of(starts, m["offset"])
        num[b] = num.get(b, 0) + m["pitch"] * m["dur"]; den[b] = den.get(b, 0) + m["dur"]
    if not num: return {}
    mean, last = [], None
    for b in range(max(num) + 1):
        if b in num: last = num[b] / den[b]
        mean.append(last)
    first = next(x for x in mean if x is not None)
    mean = [first if x is None else x for x in mean]
    sm = [sum(mean[max(0, i - 1):i + 2]) / len(mean[max(0, i - 1):i + 2]) for i in range(len(mean))]
    lo, hi = min(sm), max(sm)
    raw = []
    for x in sm:
        r = 0.5 if hi == lo else (x - lo) / (hi - lo)
        raw.append(0 if r < 0.33 else 1 if r < 0.66 else 2)
    out, cur, hold = {0: LEVELS[raw[0]]}, raw[0], 1
    for i in range(1, len(raw)):
        if raw[i] != cur and hold >= 2:
            cur += 1 if raw[i] > cur else -1; hold = 1
        else:
            hold += 1
        out[i] = LEVELS[cur]
    return out

# ---------- 2. plan (rule-based placeholder for the future LLM planner) ----------
def plan_for(phrase_idx):
    """Lean texture: the melody is always clear; the accompaniment builds up inside each 4-bar section
    (a spec is (instrument, octave shift[, first half-section in which it plays]))."""
    if phrase_idx % 2 == 0:
        return {"label": "A: melody violin+oboe; clarinet and cello accompany; horn and double bass join in the second half",
                "melody": [("Violin I", 0), ("Oboe", 0)],
                "inner1": [("Clarinet", 0)], "inner2": [("Horn", 0, 1)],
                "bass": [("Cello", 0), ("Double Bass", -12, 1)],
                "rules": ["G02 melody prominence (violin+oboe pair, MG04)", "OR03 harmony colour differs from melody",
                          "OR11 layers are added gradually", "G04 avoid compound timbres on every voice", "HM03 four real parts"]}
    return {"label": "B: melody clarinet+flute (octave up); violin II and bassoon accompany; viola and double bass join in the second half",
            "melody": [("Clarinet", 0), ("Flute", 12)],
            "inner1": [("Violin II", 0)], "inner2": [("Viola", 0, 1)],
            "bass": [("Bassoon", 0), ("Double Bass", -12, 1)],
            "rules": ["G05 rotate colours between phrases", "OR03 melody in winds -> harmony in strings",
                      "G03 flute an octave above the clarinet", "OR11 layers are added gradually", "HM03 four real parts"]}

# ---------- 3. realization ----------
def _is_par5(v0, v1, x, y):
    dx, dy = v1[x] - v0[x], v1[y] - v0[y]
    return bool(dx) and dx == dy and abs(v0[y] - v0[x]) % 12 == 7 and abs(v1[y] - v1[x]) % 12 == 7

def _try_fix(i, role, voices, events):
    v0, v1 = voices[i - 1], voices[i]
    prev = v0[role]
    pcs = {p % 12 for p in events[i]["pitches"]}
    top = v1.get("melody", 127)
    cands = sorted((12 * o + pc for o in range(2, 8) for pc in pcs
                    if v1["bass"] < 12 * o + pc < top and 12 * o + pc != v1[role]),
                   key=lambda m: abs(m - prev))
    for m in cands:
        trial = dict(v1); trial[role] = m
        if all(not _is_par5(v0, trial, role, r) for r in trial if r != role and r in v0):
            voices[i][role] = m
            return True
    return False

def repair_fifths(events, voices, log):
    """HM32: remove parallel fifths by changing inner voices only (melody and bass are never touched)."""
    for i in range(1, len(voices)):
        for _ in range(6):
            v0, v1 = voices[i - 1], voices[i]
            roles = [r for r in ("bass", "inner2", "inner1", "melody") if r in v0 and r in v1]
            hit = None
            for a in range(len(roles)):
                for b in range(a + 1, len(roles)):
                    if _is_par5(v0, v1, roles[a], roles[b]):
                        hit = (roles[a], roles[b]); break
                if hit: break
            if not hit: break
            fixed = False
            for r in hit:
                if r.startswith("inner") and _try_fix(i, r, voices, events):
                    fixed = True; log["fifths_fixed"] += 1; break
            if not fixed:
                log["fifths_unresolved"].append({"offset": events[i]["offset"], "between": list(hit)})
                break

def merge_sustains(lines, meta, log):
    bars = meta["bars"]; starts = [b[0] for b in bars]
    """Tie repeated identical notes of inner voices (within a bar) and bass (up to half notes)."""
    for name, ns in lines.items():
        out = []
        for n in ns:
            off, dur, midi, role = n
            if out:
                po, pd, pm, pr = out[-1]
                same_bar = bar_of(starts, po) == bar_of(starts, off)
                cap = bars[bar_of(starts, po)][1] if role.startswith("inner") else 2.0 if role == "bass" else 0.0
                if role == pr and role != "melody" and pm == midi and same_bar \
                        and abs(po + pd - off) < 1e-6 and pd + dur <= cap + 1e-6:
                    out[-1][1] = pd + dur; log["merged_notes"] += 1
                    continue
            out.append(n)
        lines[name] = out

def enforce_breath(lines, meta, log):
    bars = meta["bars"]; starts = [b[0] for b in bars]
    """W01/QX04: split long continuous wind runs by dropping an inner-voice bar (never a melody bar)."""
    for name in WINDS & set(lines):
        while True:
            used = sorted({bar_of(starts, n[0]) for n in lines[name]})
            runs, cur = [], []
            for b in used:
                if cur and b == cur[-1] + 1: cur.append(b)
                else:
                    if cur: runs.append(cur)
                    cur = [b]
            if cur: runs.append(cur)
            long = [r for r in runs if sum(bars[x][1] for x in r) > MAX_WIND_RUN_BEATS]
            if not long: break
            r = long[0]
            cands = [b for b in r if all(n[3] != "melody" for n in lines[name] if bar_of(starts, n[0]) == b)]
            if not cands:
                log["breath_unresolved"].append({"instrument": name, "bars": [x + 1 for x in r]}); break
            def worst(b):            # longest remaining run (in beats) if bar b is dropped
                rest = [x for x in r if x != b]; runs2, cur2 = [], []
                for x in rest:
                    if cur2 and x == cur2[-1] + 1: cur2.append(x)
                    else:
                        if cur2: runs2.append(cur2)
                        cur2 = [x]
                if cur2: runs2.append(cur2)
                return max((sum(bars[y][1] for y in rr) for rr in runs2), default=0)
            b = min(cands, key=worst)
            lines[name] = [n for n in lines[name] if bar_of(starts, n[0]) != b]
            log["breath_rests"].append({"instrument": name, "bar": b + 1})


ENABLE_WIND_BREATHS = False
def fix_bass_fifths(lines, log):
    """HM32 in the bass: if cello and double bass form a parallel fifth, move the double bass by an octave."""
    cel = sorted(lines.get("Cello", []), key=lambda n: n[0])
    db = sorted(lines.get("Double Bass", []), key=lambda n: n[0])
    if not cel or not db: return
    lo, hi = RANGES[KEY["Double Bass"]]
    def at(seq, off):
        best = None
        for n in seq:
            if n[0] <= off + 1e-9: best = n
        return best
    for i in range(len(db)):
        off = db[i][0]
        c_now, d_now = at(cel, off), db[i]
        if c_now is None: continue
        prev_off = db[i - 1][0] if i > 0 else None
        if prev_off is None: continue
        c_prev, d_prev = at(cel, prev_off), db[i - 1]
        if c_prev is None or c_prev is c_now: continue
        dx = c_now[2] - c_prev[2]; dy = d_now[2] - d_prev[2]
        if dx and dx == dy and abs(d_prev[2] - c_prev[2]) % 12 == 7 and abs(d_now[2] - c_now[2]) % 12 == 7:
            # an octave does not change the interval class, so move the note by a small step instead
            options = []
            for k in (-2, 2, -3, 3, -4, 4, -5, 5, -1, 1):
                cand = d_now[2] + k
                if not (lo <= cand <= hi): continue
                if abs(cand - c_now[2]) % 12 == 7 or abs(cand - c_now[2]) % 12 == 0: continue
                if abs(cand - d_prev[2]) % 12 == 0 and d_prev is not None: pass
                options.append(cand)
            if options:
                db[i][2] = options[0]
                log["bass_fifths_fixed"] = log.get("bass_fifths_fixed", 0) + 1
    lines["Double Bass"] = db

BREATH_RUN_LIMIT = 10.0   # beats of continuous wind playing before a breath (validator limit is 16)

def enforce_wind_breaths(lines, log):
    """QX04: insert a one-beat breath into long wind lines by shortening a note of at least 2 beats.
    Pitches are never changed; only the length of one note inside a long run is reduced."""
    for name in WINDS & set(lines):
        ns = lines[name]
        i = 0
        run = 0.0
        while i < len(ns):
            off, dur, midi, role = ns[i]
            if i > 0:
                po, pd = ns[i - 1][0], ns[i - 1][1]
                if off - (po + pd) >= 1.0 - 1e-6:
                    run = 0.0                      # already breathing
            run += dur
            if run > BREATH_RUN_LIMIT:
                # shorten the latest note (at most 4 notes back) that has room for a one-beat rest
                placed = False
                for j in range(i, max(-1, i - 5), -1):
                    if j - 0 < 1: break
                    o2, d2 = ns[j - 1][0], ns[j - 1][1]
                    if d2 >= 2.0 and ns[j - 1][3] != "bass":
                        ns[j - 1][1] = d2 - 1.0
                        log["breaths_added"] = log.get("breaths_added", 0) + 1
                        placed = True
                        break
                if placed:
                    run = dur + 0.0
                    # recompute run from the shortened note: the gap now breaks the run
                    run = 0.0
                    run += dur
                else:
                    log.setdefault("breath_failed", []).append({"instrument": name, "offset": off})
                    run = 0.0
            i += 1

def realize(s, events, melody, meta, plan):
    starts = [b[0] for b in meta["bars"]]
    log = {"octave_shifts": 0, "dropped": 0, "plans": {}, "fifths_fixed": 0, "fifths_unresolved": [],
           "merged_notes": 0, "breath_rests": [], "breath_unresolved": []}
    voices = []
    for e in events:
        v = {"bass": e["bass"]}
        if e["melody"] is not None: v["melody"] = e["melody"]
        if len(e["inner"]) > 0: v["inner1"] = e["inner"][0]
        if len(e["inner"]) > 1: v["inner2"] = e["inner"][1]
        voices.append(v)
    repair_fifths(events, voices, log)
    lines = {n: [] for n in SCORE_ORDER if n != "Piano"}
    phrase_of = {}
    for ph in plan["phrases"]:
        for bi in range(ph["bars"][0] - 1, ph["bars"][1]): phrase_of[bi] = ph
    def put(offset, dur, midi, role):
        bi = bar_of(starts, offset)
        ph = phrase_of.get(bi)
        if ph is None: return
        a_, b_ = ph["bars"]
        pos = (bi - (a_ - 1)) / (b_ - a_ + 1)
        for spec in ph.get(role, []):
            name, shift = spec[0], spec[1]
            if len(spec) > 2 and pos < spec[2] - 1e-9: continue
            if len(spec) > 3 and spec[3] is not None and pos >= spec[3] - 1e-9: continue
            fitted = fit(midi + shift, name)
            if fitted is None: log["dropped"] += 1; continue
            if fitted != midi + shift: log["octave_shifts"] += 1
            lines[name].append([offset, dur, fitted, role])
    for m in melody: put(m["offset"], m["dur"], m["pitch"], "melody")
    for e, v in zip(events, voices):
        for role in ("bass", "inner1", "inner2"):
            if role in v: put(e["offset"], e["dur"], v[role], role)
    for f in meta["fig"]: put(f["offset"], f["dur"], f["pitch"], "figuration")
    for name in lines: lines[name].sort(key=lambda n: n[0])
    for name, seq in lines.items():                  # a single instrument can't sound two notes at once
        for i in range(len(seq) - 1):
            gap = seq[i + 1][0] - seq[i][0]
            if seq[i][1] > gap:
                seq[i][1] = max(gap, 0.0)
        lines[name] = [n for n in seq if n[1] > 1e-6]
    merge_sustains(lines, meta, log)
    fix_bass_fifths(lines, log)
    enforce_breath(lines, meta, log)
    if ENABLE_WIND_BREATHS:
        enforce_wind_breaths(lines, log)   # off by default: it created parallel fifths (HM32) in tests
    return lines, log

# ---------- 4. score building ----------

def piece_key(s):
    """Concert key of the piece as a music21 Key (estimated from the source; check by eye)."""
    from music21 import key as m21key
    try:
        k = s.analyze("key")
        return m21key.Key(k.tonic.name, k.mode)
    except Exception:
        return m21key.Key("C")

def add_dynamics(score, dyn_by_bar):
    last = None
    for b in sorted(dyn_by_bar):
        d = dyn_by_bar[b]
        if d == last: continue
        last = d
        for p in score.parts:
            ms = list(p.getElementsByClass(stream.Measure))
            if b < len(ms):
                ms[b].insert(0, dynamics.Dynamic(d))

LEVEL_VEL = {"mp": 64, "mf": 80, "f": 96}
ROLE_VEL = {"melody": 14, "inner1": -14, "inner2": -14, "bass": -6, "figuration": -10}   # melody above accompaniment

def build_score(s, lines, dyn, piano_mode="off", meta=None):
    starts = [b[0] for b in meta["bars"]]
    out = stream.Score()
    piano_parts = [copy.deepcopy(p) for p in s.parts]
    tempo_done = False
    for name in SCORE_ORDER:
        if name == "Piano":
            if piano_mode == "off": continue
            for pp in piano_parts:
                pp.partName = "Piano"; pp.insert(0, CLASSES["Piano"]())
                out.insert(0, pp)
            continue
        p = stream.Part(); p.partName = name; p.insert(0, CLASSES[name]())
        for off, ratio in meta["tsigs"]: p.insert(off, meter.TimeSignature(ratio))
        if piano_mode == "off" and not tempo_done:
            for off, bpm in meta["tempos"]: p.insert(off, tempo.MetronomeMark(number=bpm))
            tempo_done = True
        for off, dur, midi, role in lines[name]:
            n = note.Note(midi, quarterLength=dur)
            v = max(20, min(120, LEVEL_VEL[dyn.get(bar_of(starts, off), "mf")] + ROLE_VEL.get(role, 0)))
            n.volume = volume.Volume(velocity=v); n.volume.velocityIsRelative = False
            p.insert(off, n)
        p.makeMeasures(inPlace=True)
        p.makeTies(inPlace=True)   # split notes that cross a barline into tied pieces (keeps exact rhythm, including tuplets)
        out.insert(0, p)
    add_dynamics(out, dyn)
    # explicit key signature per part: concert key from the piece, written key = concert key transposed
    from music21 import key as m21key
    concert = piece_key(s)
    for p in out.parts:
        if p.partName == "Piano":
            continue
        ins = p.getInstrument(returnDefault=False)
        tr = getattr(ins, "transposition", None) if ins is not None else None
        written = concert.transpose(tr) if tr is not None else concert
        for m in list(p.getElementsByClass(stream.Measure))[:1]:
            m.insert(0, m21key.KeySignature(written.sharps))
    for p in out.parts: p.atSoundingPitch = True
    return out

# ---------- 5. MIDI mix: seating, balance, reverb ----------
PAN = {"Flute": 50, "Oboe": 68, "Clarinet": 58, "Bassoon": 74, "Horn": 92, "Violin I": 20,
       "Violin II": 38, "Viola": 84, "Cello": 102, "Double Bass": 114, "Piano": 64}
VOL = {k: 100 for k in PAN}

def mix_midi(path):
    import mido
    mid = mido.MidiFile(path)
    names = {"Violin": "Violin", "Violoncello": "Cello", "Contrabass": "Double Bass"}
    violins_seen, free_channels = 0, [10, 11, 12, 13]
    for tr in mid.tracks:
        nm = next((m.name for m in tr if m.type == "track_name"), None)
        ch = next((m.channel for m in tr if hasattr(m, "channel")), None)
        if nm is None or ch is None: continue
        key = names.get(nm, nm)
        if key == "Violin":
            violins_seen += 1
            key = "Violin I" if violins_seen == 1 else "Violin II"
            if key == "Violin II":
                newch = free_channels.pop(0)
                for m in tr:
                    if hasattr(m, "channel"): m.channel = newch
                ch = newch
        if key not in PAN: continue
        idx = 0
        while idx < len(tr) and tr[idx].is_meta: idx += 1
        for cc, val in ((91, 40), (7, VOL[key]), (10, PAN[key])):
            tr.insert(idx, mido.Message("control_change", channel=ch, control=cc, value=val, time=0))
    mid.save(path)

def _active_db(wav_path):
    import wave, numpy as np
    w = wave.open(wav_path)
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768.0
    a = a.reshape(-1, w.getnchannels()).mean(axis=1)
    fr = 4410
    n = len(a) // fr
    rms = np.sqrt((a[:n * fr].reshape(n, fr) ** 2).mean(axis=1))
    act = rms[rms > 0.05 * rms.max()] if rms.max() > 0 else rms
    return 20 * np.log10(np.sqrt((act ** 2).mean()) + 1e-9)

def auto_balance(path):
    """Measure each instrument alone (active frames only) and equalize apparent loudness with CC7."""
    import mido, numpy as np
    mid = mido.MidiFile(path)
    meas = {}
    for i, tr in enumerate(mid.tracks):
        if not any(m.type == "note_on" and m.velocity > 0 for m in tr): continue
        single = mido.MidiFile(type=1, ticks_per_beat=mid.ticks_per_beat)
        fixed = mido.MidiTrack([(m.copy(velocity=80) if (m.type == 'note_on' and m.velocity > 0) else m) for m in tr])
        single.tracks.append(mid.tracks[0]); single.tracks.append(fixed)
        with tempfile.TemporaryDirectory() as d:
            mp, wp = os.path.join(d, "t.mid"), os.path.join(d, "t.wav")
            single.save(mp)
            subprocess.run(["fluidsynth", "-ni", "-F", wp, "-r", "44100", SF2, mp],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(wp): meas[i] = _active_db(wp)
    if not meas: return {}
    target = float(np.median(list(meas.values())))
    result = {}
    for i, db in meas.items():
        for m in mid.tracks[i]:
            if m.type == "control_change" and m.control == 7:
                new = int(round(min(127, max(30, m.value * 10 ** ((target - db) / 40)))))
                result[next((x.name for x in mid.tracks[i] if x.type == "track_name"), str(i))] = (m.value, new, round(db, 1))
                m.value = new
    mid.save(path)
    return result

def run(in_path, out_stem, piano_mode="off", plan_path=None):
    s, events, melody, meta = analyze(in_path)
    import phrase_planner
    plan = json.load(open(plan_path, encoding="utf-8")) if plan_path else phrase_planner.make_plan(s, events, melody, meta)
    json.dump(plan, open(out_stem + "_plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines, log = realize(s, events, melody, meta, plan)
    dyn = {bi: ph["level"] for ph in plan["phrases"] for bi in range(ph["bars"][0] - 1, ph["bars"][1])}
    log["dynamics_by_bar"] = {b + 1: d for b, d in sorted(dyn.items())}
    snd = build_score(s, lines, dyn, piano_mode, meta)
    snd.write("midi", fp=out_stem + ".mid")
    mix_midi(out_stem + ".mid")
    try:
        log["loudness_balance"] = auto_balance(out_stem + ".mid")
    except Exception as e:
        log["loudness_balance"] = {"error": str(e)}
    written = snd.toWrittenPitch(inPlace=False)
    add_dynamics(written, dyn)   # dynamics must be written into the MusicXML too (MuseScore shows them)
    written.write("musicxml", fp=out_stem + ".musicxml")
    issues, names = validator.check_score(out_stem + ".musicxml")
    json.dump({"plan_log": log, "issues": issues}, open(out_stem + "_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return log, issues, names

if __name__ == "__main__":
    log, issues, names = run(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "off", sys.argv[4] if len(sys.argv) > 4 else None)
    import phrase_planner
    print(phrase_planner.table(json.load(open(sys.argv[2] + "_plan.json", encoding="utf-8"))))
    from collections import Counter
    print("octave shifts:", log["octave_shifts"], "| dropped:", log["dropped"],
          "| fifths fixed:", log["fifths_fixed"], "| unresolved:", log["fifths_unresolved"])
    print("merged notes:", log["merged_notes"], "| breath rests:", log["breath_rests"])
    print("dynamics by bar:", log["dynamics_by_bar"])
    print("loudness (old CC7 -> new CC7, measured dB):", log["loudness_balance"])
    print("validator:", dict(Counter((a, b) for a, b, _, _ in issues)) or "no issues")
    for sev, rid, w, m in issues: print("  ", sev, rid, m)
