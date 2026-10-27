"""
Validator v0.6 for chamber orchestration output.
Pairwise voice checks (works when some instruments rest).
Implemented: HM32 parallel fifths (error), HM05 parallel octaves between violins
(warning), G01 range (warning, ranges UNVERIFIED), piano part is skipped.
"""
import json, sys, warnings, bisect
warnings.filterwarnings("ignore")
from music21 import converter, chord

RULES_PATH = "/mnt/user-data/outputs/orchestration_rules.json"
MAX_WIND_RUN_BEATS = 16  # author heuristic, not from the source book
MAX_DOUBLING_RATIO = 1.35  # beat-sampled; 25 classical quartets: mean 1.06, max 1.54 (author heuristic)

# Approximate sounding ranges (MIDI). UNVERIFIED: replace with a checked reference.
RANGES_UNVERIFIED = {
    "violin": (55, 103), "viola": (48, 91), "cello": (36, 76), "double_bass": (28, 67),
    "flute": (60, 96), "oboe": (58, 91), "clarinet": (50, 94), "bassoon": (34, 75),
    "horn": (41, 77),
}

def instrument_key(name):
    n = name.lower()
    if "piano" in n: return None
    if "double" in n or "contrabass" in n: return "double_bass"
    if "violoncello" in n or "cello" in n: return "cello"
    if "viola" in n: return "viola"
    if "violin" in n: return "violin"
    for k in ("flute", "oboe", "clarinet", "bassoon", "horn"):
        if k in n: return k
    return None

def voice_map(part):
    d = {}
    for el in part.flatten().notes:
        p = min(x.midi for x in el.pitches) if isinstance(el, chord.Chord) else el.pitch.midi
        d.setdefault(float(el.offset), p)
    return d


def doubling_ratio(plist):
    """Sounding notes per distinct pitch, sampled on every beat (only beats with 2+ notes)."""
    total = max((b for ns in plist.values() for _, b, _ in ns), default=0)
    notes = distinct = 0
    for beat in range(int(total) + 1):
        sounding = [p for ns in plist.values() for a, b, p in ns if a <= beat + 1e-6 < b]
        if len(sounding) >= 2:
            notes += len(sounding); distinct += len(set(sounding))
    return notes / distinct if distinct else None

def check_score(path):
    s0 = converter.parse(path)
    parts0 = list(s0.parts)
    names = [(p.partName or p.id or f"part{i}") for i, p in enumerate(parts0)]
    issues = []

    # QX03: transposing instruments must be written in transposed form
    for k, p in enumerate(parts0):
        if instrument_key(names[k]) in ("clarinet", "horn", "double_bass"):
            ins = p.getInstrument(returnDefault=False)
            tr = getattr(ins, "transposition", None) if ins is not None else None
            if tr is None or p.atSoundingPitch is True:
                issues.append(("warning", "QX03", None, f"{names[k]} is not written in transposed form"))

    # all further checks work on sounding (concert) pitch
    try:
        s = s0.toSoundingPitch(inPlace=False)
    except Exception:
        s = s0
    parts = list(s.parts)
    voices = [voice_map(p) for p in parts]
    sorted_on = [sorted(v) for v in voices]

    for x in range(len(parts)):
        for y in range(x + 1, len(parts)):
            if "piano" in names[x].lower() or "piano" in names[y].lower():
                continue
            common = sorted(set(voices[x]) & set(voices[y]))
            for a, b in zip(common, common[1:]):
                # consecutive in both voices: no other onset of x or y between a and b
                def has_between(lst):
                    i = bisect.bisect_right(lst, a)
                    return i < len(lst) and lst[i] < b
                if has_between(sorted_on[x]) or has_between(sorted_on[y]):
                    continue
                dx = voices[x][b] - voices[x][a]
                dy = voices[y][b] - voices[y][a]
                if not dx or dx != dy:
                    continue
                i0 = abs(voices[y][a] - voices[x][a]) % 12
                i1 = abs(voices[y][b] - voices[x][b]) % 12
                if i0 == 7 and i1 == 7:
                    issues.append(("error", "HM32", a, f"parallel fifths {names[x]}-{names[y]}"))
                is_vln = "violin" in names[x].lower() and "violin" in names[y].lower()
                if is_vln and abs(voices[y][a] - voices[x][a]) == 12 and abs(voices[y][b] - voices[x][b]) == 12:
                    issues.append(("warning", "HM05", a, f"parallel octaves {names[x]}-{names[y]}"))

    for k in range(len(parts)):
        key = instrument_key(names[k])
        if key:
            lo, hi = RANGES_UNVERIFIED[key]
            bad = [p for p in voices[k].values() if p < lo or p > hi]
            if bad:
                issues.append(("warning", "G01", None, f"{names[k]}: {len(bad)} notes outside approximate range"))

    # QX02: dynamics must exist
    if not list(s.recurse().getElementsByClass('Dynamic')):
        issues.append(("warning", "QX02", None, "score has no dynamics"))

    # QX01 monotony (repeated identical notes) and QX04 breath (wind parts)
    WINDS = ("flute", "oboe", "clarinet", "bassoon", "horn")
    for k, p in enumerate(parts):
        key = instrument_key(names[k])
        if key is None:
            continue
        ns = sorted((float(n.offset), float(n.quarterLength),
                     (min(x.midi for x in n.pitches) if isinstance(n, chord.Chord) else n.pitch.midi))
                    for n in p.flatten().notes)
        if len(ns) >= 8:
            rep = sum(1 for a, b in zip(ns, ns[1:]) if a[2] == b[2] and a[1] < 2.0 and abs(a[0] + a[1] - b[0]) < 1e-6)  # half notes and longer are rhythm, not monotony
            if rep / (len(ns) - 1) > 0.5:
                issues.append(("warning", "QX01", None, f"{names[k]}: {rep} of {len(ns)-1} notes repeat the previous one"))
        if key in WINDS and ns:
            run_start, run_end, longest = ns[0][0], ns[0][0] + ns[0][1], 0.0
            for off, dur, _ in ns[1:]:
                if off - run_end >= 1.0:
                    longest = max(longest, run_end - run_start); run_start = off
                run_end = max(run_end, off + dur)
            longest = max(longest, run_end - run_start)
            if longest > MAX_WIND_RUN_BEATS:
                issues.append(("warning", "QX04", None, f"{names[k]}: plays {longest:.0f} beats without a rest of 1 beat or more"))
    # per-part note lists (offset, end, midi), non-piano instruments only
    plist = {}
    for k, p in enumerate(parts):
        if instrument_key(names[k]) is None: continue
        plist[names[k]] = [(float(n.offset), float(n.offset + n.quarterLength),
                            (min(x.midi for x in n.pitches) if isinstance(n, chord.Chord) else n.pitch.midi))
                           for n in p.flatten().notes]
    ts = next(iter(s.recurse().getElementsByClass('TimeSignature')), None)
    bar = ts.barDuration.quarterLength if ts else 4.0

    # QX05: doubling density sampled on every beat (sounding notes per distinct pitch)
    ratio = doubling_ratio(plist)
    if ratio is not None and ratio > MAX_DOUBLING_RATIO:
        issues.append(("warning", "QX05", None, f"unison doubling density {ratio:.2f} (limit {MAX_DOUBLING_RATIO})"))

    # QX06: unused instruments
    for nm, ns in plist.items():
        if not ns: issues.append(("warning", "QX06", None, f"{nm} plays no notes"))

    # QX07: idiomatic speed (share of notes shorter than the instrument's comfortable minimum; author heuristic)
    MIN_DUR = {"double_bass": 0.5, "horn": 0.5, "bassoon": 0.25, "cello": 0.25}
    for nm, ns in plist.items():
        lim = MIN_DUR.get(instrument_key(nm))
        if lim and ns:
            fast = sum(1 for a, b, _ in ns if (b - a) < lim - 1e-6) / len(ns)
            if fast > 0.15:
                issues.append(("warning", "QX07", None, f"{nm}: {fast*100:.0f}% of notes shorter than {lim} beat"))

    # QX08: stable number of instruments per bar (author heuristic: swing at most 4), real measure boundaries
    ms = [(float(m.offset), float(m.offset + m.duration.quarterLength))
          for m in parts[0].getElementsByClass('Measure')] if parts else []
    if not ms:
        total = max((b for ns in plist.values() for _, b, _ in ns), default=0)
        import math
        ms = [(i * bar, (i + 1) * bar) for i in range(int(math.ceil(total / bar - 1e-9)))]
    counts = [sum(1 for ns in plist.values() if any(a < hi - 1e-6 and b > lo + 1e-6 for a, b, _ in ns)) for lo, hi in ms]
    counts = [c for c in counts]
    if counts and max(counts) - min(counts) > 4:
        issues.append(("warning", "QX08", None, f"number of playing instruments swings from {min(counts)} to {max(counts)} between bars"))
    return issues, names

if __name__ == "__main__":
    from collections import Counter
    issues, names = check_score(sys.argv[1])
    print("parts:", names)
    print("counts:", dict(Counter((sev, rid) for sev, rid, _, _ in issues)))
    for sev, rid, where, msg in issues[:15]:
        print(f"  [{sev}] {rid} at offset {where}: {msg}")
