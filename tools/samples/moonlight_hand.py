"""Ручная аранжировка-образец (Claude) первых 23 тактов «Лунной»: слои рояля розданы по ролям напрямую."""
import sys, mido
sys.path.insert(0, "/home/claude/shopendirizhor/src")
import orchestrator, performer
src, out = sys.argv[1], sys.argv[2]
m = mido.MidiFile(src); tpb = m.ticks_per_beat
def notes(tr):
    t, on, res = 0, {}, []
    for x in tr:
        t += x.time
        if x.type == "note_on" and x.velocity > 0: on[x.note] = (t, x.velocity)
        elif x.type in ("note_off", "note_on") and x.note in on:
            s, v = on.pop(x.note); res.append([s, t + 1, x.note, v])
    return sorted(res)
rh, lh = notes(m.tracks[1]), notes(m.tracks[2])
mel = [n for n in rh if n[3] > 60]; tri = [n for n in rh if n[3] <= 60]
B = tpb
# триоли по долям: (низ, середина, верх)
groups = {}
for n in tri: groups.setdefault(n[0] // B, []).append(n)
def pad(idx):
    """Тянущаяся линия из idx-й ноты каждой триоли; одинаковые подряд сливаются."""
    line = []
    for b in sorted(groups):
        g = sorted(groups[b], key=lambda n: n[2])
        if len(g) < 3: continue
        p = g[idx][2]
        if line and line[-1][2] == p and line[-1][1] == b * B: line[-1][1] = (b + 1) * B
        else: line.append([b * B, (b + 1) * B, p])
    return line
bass_lo, bass_hi, bass_mid = [], [], []
by = {}
for n in lh: by.setdefault(n[0], []).append(n)
for s, g in sorted(by.items()):
    g.sort(key=lambda n: n[2])
    bass_lo.append(g[0][:3]); bass_hi.append(g[-1][:3] if len(g) > 1 else g[0][:3])
    if len(g) > 2: bass_mid.append(g[1][:3])
first_mel = min(n[0] for n in mel)
parts = [  # имя дорожки, программа, ноты, сила нажатия
    ("Clarinet", 71, [n[:3] for n in mel], 80),
    ("Bassoon", 70, bass_mid, 50),
    ("Horn", 60, [n for n in pad(0) if n[0] >= (first_mel // (4 * B)) * 4 * B], 44),
    ("Violin", 40, pad(2), 46),
    ("Violin", 40, pad(1), 44),
    ("Viola", 41, [n[:3] for n in tri], 54),
    ("Violoncello", 42, bass_hi, 58),
    ("Contrabass", 43, [n for n in bass_lo if n[2] <= 55], 58),
]
o = mido.MidiFile(ticks_per_beat=tpb); o.tracks.append(m.tracks[0])
chans = [0, 1, 2, 3, 4, 5, 6, 7]
for (name, prog, ns, vel), ch in zip(parts, chans):
    ns = sorted(ns); ev = []
    for i, n in enumerate(ns):                      # один голос: нота не налезает на следующую
        e = n[1]
        nxt = [x[0] for x in ns[i + 1:] if x[0] > n[0]]
        if nxt and e > nxt[0] and name not in ("Clarinet",): e = nxt[0]
        if name == "Clarinet" and nxt and e > nxt[0]: e = nxt[0]
        ev.append((n[0], 1, mido.Message("note_on", channel=ch, note=n[2], velocity=vel)))
        ev.append((e - 1, 0, mido.Message("note_off", channel=ch, note=n[2], velocity=0)))
    ev.sort(key=lambda x: (x[0], x[1]))
    tr = mido.MidiTrack(); tr.append(mido.MetaMessage("track_name", name=name, time=0))
    tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
    prev = 0
    for t, _, msg in ev: tr.append(msg.copy(time=t - prev)); prev = t
    o.tracks.append(tr)
    print("%-12s нот %3d  %d–%d" % (name, len(ns), min(x[2] for x in ns), max(x[2] for x in ns)))
o.save(out)
orchestrator.mix_midi(out)
nb = int(max(n[1] for n in rh + lh) // (4 * B)) + 1
info = performer.apply(out, [4.0 * i for i in range(nb + 1)], [0.0, 16.0, 36.0, 56.0, 76.0], {"Clarinet": {n[0] / B for n in mel}})
print("исполнитель: фраз", info["phrases"], "CC11", info["cc11_events"])
