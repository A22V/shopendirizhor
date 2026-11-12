import sys, mido
from music21 import converter
src, out, last = sys.argv[1], sys.argv[2], int(sys.argv[3])
s = converter.parse(src, format="humdrum")
TPB = 480
mel, tri, bass = [], [], []
for pi, p in enumerate(s.parts):
    for m in p.getElementsByClass('Measure'):
        if not (1 <= m.number <= last): continue
        base = (m.number - 1) * 4.0
        for el in m.recurse().notes:
            if el.duration.isGrace or el.quarterLength <= 0: continue
            off = base + float(el.getOffsetInHierarchy(m)); ql = float(el.quarterLength)
            if el.tie is not None and el.tie.type in ("stop", "continue"):
                tgt = mel if pi == 0 and abs(ql * 3 - round(ql * 3)) > 1e-6 or (pi == 0 and ql >= 0.5) else (tri if pi == 0 else bass)
                for n in tgt:                       # продлить связанную ноту
                    if abs(n[0] + n[1] - off) < 1e-6 and n[2] in [x.midi for x in el.pitches]: n[1] += ql
                continue
            is_tri = abs(ql - 1/3) < 0.02
            for pt in el.pitches:
                (bass if pi == 1 else tri if is_tri else mel).append([off, ql, pt.midi])
mel = [n for n in mel if n[0] < (last-1)*4+3.5]
mid = mido.MidiFile(ticks_per_beat=TPB)
t0 = mido.MidiTrack(); mid.tracks.append(t0)
t0.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(54), time=0))
t0.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
def track(notes_vel, pedal=None):
    ev = []
    for (o, q, p), v in notes_vel:
        ev.append((int(round(o * TPB)), 1, mido.Message("note_on", note=p, velocity=v)))
        ev.append((int(round((o + q) * TPB)) - 1, 0, mido.Message("note_off", note=p, velocity=0)))
    for t in (pedal or []):
        if t > 0: ev.append((t - 20, 0, mido.Message("control_change", control=64, value=0)))
        ev.append((t + 20, 2, mido.Message("control_change", control=64, value=127)))
    ev.sort(key=lambda x: (x[0], x[1]))
    tr = mido.MidiTrack(); tr.append(mido.MetaMessage("track_name", name="Piano", time=0)); tr.append(mido.Message("program_change", program=0, time=0))
    prev = 0
    for t, _, m in ev:
        tr.append(m.copy(time=max(0, t - prev))); prev = max(prev, t)
    return tr
ped = sorted({int(round(n[0] * TPB)) for n in bass})
mid.tracks.append(track([(n, 66) for n in mel] + [(n, 46) for n in tri]))
mid.tracks.append(track([(n, 52) for n in bass], ped))
mid.save(out)
print("мелодия", len(mel), "триоли", len(tri), "бас", len(bass), "длина с", round(mid.length, 1))
print("мелодия:", [(round(n[0]/4+1,2), n[2], round(n[1],2)) for n in sorted(mel)][:60])
