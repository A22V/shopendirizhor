import mido, os, glob, csv, bisect, collections
ROOT = "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop_db/LOP_database_06_09_17/LOP_database_06_09_17"

def load(path):
    """-> {track: [(start,end,pitch,vel)] in beats}, bpb (first time sig), length beats, n_pedal"""
    m = mido.MidiFile(path); tpb = m.ticks_per_beat; out = collections.OrderedDict(); bpb = None; ped = 0; ts = []
    for k, tr in enumerate(m.tracks):
        t = 0; on = {}; ns = []
        for x in tr:
            t += x.time
            if x.type == "time_signature":
                ts.append((t / tpb, x.numerator * 4.0 / x.denominator))
            if x.type == "control_change" and x.control == 64: ped += 1
            if x.type == "note_on" and x.velocity > 0:
                on.setdefault((x.channel, x.note), []).append((t, x.velocity))
            elif x.type in ("note_on", "note_off") and on.get((x.channel, x.note)):
                s, v = on[(x.channel, x.note)].pop(0)
                if t > s: ns.append((s / tpb, t / tpb, x.note, v))
        if ns:
            name = (tr.name or "track%d" % k).strip()
            while name in out: name += "'"
            out[name] = sorted(ns)
    ts.sort()
    bpb = ts[0][1] if ts else 4.0
    end = max((n[1] for v in out.values() for n in v), default=0)
    return out, bpb, end, ped, ts

def mapping(midpath):
    """csv next to midi: track name -> normalized instrument"""
    p = midpath[:-4] + ".csv"
    if not os.path.exists(p): return {}
    rows = list(csv.reader(open(p, encoding="utf-8", errors="replace"), delimiter=";"))
    if len(rows) < 2: return {}
    return {a.strip(): b.strip() for a, b in zip(rows[0], rows[1])}

FAM = {"Piccolo": "флейта", "Flute": "флейта", "Oboe": "гобой", "English horn": "гобой", "Clarinet": "кларнет", "Bass clarinet": "кларнет",
       "Bassoon": "фагот", "Contrabassoon": "фагот", "Horn": "валторна", "Trumpet": "медь", "Trombone": "медь", "Tuba": "медь",
       "Violin": "скрипки", "Viola": "альт", "Violoncello": "виолончель", "Contrabass": "контрабас", "Harp": "арфа",
       "Percussion": "ударные", "Timpani": "ударные", "Piano": "рояль"}

def pairs():
    res = []
    for folder in ("bouliane", "imslp", "liszt_classical_archives", "hand_picked_Spotify"):
        for d in sorted(glob.glob(os.path.join(ROOT, folder, "*")), key=lambda p: int(os.path.basename(p))):
            mids = sorted(glob.glob(os.path.join(d, "*.mid")))
            orch = [m for m in mids if m.lower().endswith("orch.mid")]
            solo = [m for m in mids if m.lower().endswith("solo.mid")]
            if len(orch) == 1 and len(solo) == 1:
                res.append((folder, os.path.basename(d), solo[0], orch[0]))
            else:
                res.append((folder, os.path.basename(d), None, None))
    return res
